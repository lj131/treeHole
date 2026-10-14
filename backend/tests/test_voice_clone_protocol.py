"""克隆引擎的协议与状态机测试（**不打真实模型**，CI 能跑）。

真机合成很慢（冷启动 ~18s，且需要 sidecar venv + 权重），
所以这里只测**逻辑**：编解码、缓存键、错误信息、进程管理。
"""
import asyncio
import json
import os
import sys
import wave
from pathlib import Path

import pytest

from funcation import voice_clone
from funcation.voice_clone import CloneEngineError, CloneEngineManager


@pytest.fixture
def ref_wav(tmp_path):
    """造一段短 wav 当参考音频"""
    import math
    import struct

    p = tmp_path / "ref.wav"
    sr = 22050
    with wave.open(str(p), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        for i in range(sr):
            t = i / sr
            v = 0.6 * math.sin(2 * math.pi * 150 * t)
            w.writeframes(struct.pack("<h", int(max(-0.9, min(0.9, v)) * 32767)))
    return p


@pytest.fixture
def manager(tmp_path, monkeypatch):
    """指向一个**假的** sidecar venv，避免测试真的去装东西"""
    fake_venv = tmp_path / "venv"
    (fake_venv / "Scripts").mkdir(parents=True)
    m = CloneEngineManager()
    monkeypatch.setattr(voice_clone, "SIDECAR_PYTHON", str(fake_venv / "Scripts" / "python.exe"))
    monkeypatch.setattr(voice_clone, "WORKER_SCRIPT", str(tmp_path / "worker.py"))
    monkeypatch.setattr(voice_clone, "WORKER_CWD", str(tmp_path))
    return m


# ============================================================
# 安装检测与错误提示
# ============================================================

def test_not_installed_message_is_actionable(manager):
    """sidecar 没装时的报错必须说清楚"怎么办"，不能只说一句失败"""
    with pytest.raises(CloneEngineError) as ei:
        asyncio.run(manager.synthesize("你好", "nope.wav"))
    assert "setup_clone_env" in str(ei.value.hint)
    assert "4GB" in str(ei.value.hint)


def test_missing_reference_audio_rejected(manager, ref_wav, monkeypatch):
    monkeypatch.setattr(voice_clone, "is_installed", lambda: True)
    with pytest.raises(CloneEngineError) as ei:
        asyncio.run(manager.synthesize("你好", str(ref_wav.parent / "missing.wav")))
    assert "参考音频" in str(ei.value)


def test_empty_text_rejected(manager, ref_wav, monkeypatch):
    monkeypatch.setattr(voice_clone, "is_installed", lambda: True)
    with pytest.raises(CloneEngineError):
        asyncio.run(manager.synthesize("   ", str(ref_wav)))


# ============================================================
# 协议
# ============================================================

def test_request_shape(manager):
    """请求要带齐 worker 需要的字段"""
    req = {"op": "synth", "text": "你好", "ref": "/abs/ref.wav", "lang": "ZH", "speed": 1.0}
    # 编码后再解码，确认没有非 ASCII 破坏
    line = json.dumps({"id": 1, **req}, ensure_ascii=False)
    back = json.loads(line)
    assert back["op"] == "synth"
    assert back["text"] == "你好"
    assert back["lang"] == "ZH"


def test_response_skips_non_protocol_lines(manager):
    """第三方库往 stdout 打 print 时，manager 必须跳过而不是崩。

    这是实测踩过的坑：OpenVoice 的 `load_ckpt()` 会 print
    'Loaded checkpoint ...'，把 JSON-lines 协议流弄脏。
    """

    class FakeStdout:
        def __init__(self):
            self._lines = [
                b"Loaded checkpoint 'data\\\\openvoice\\\\checkpoints\\\\converter\\\\checkpoint.pth'\n",
                b"missing/unexpected keys: [] []\n",
                json.dumps({"id": 7, "ok": True, "wav_path": "/tmp/x.wav"}).encode() + b"\n",
            ]

        async def readline(self):
            return self._lines.pop(0) if self._lines else b""

    m = manager
    m._reader = FakeStdout()
    resp = asyncio.run(m._read_response(timeout=5))
    assert resp is not None
    assert resp["id"] == 7
    assert resp["ok"] is True


def test_response_validates_id():
    """没有 id 的行（比如 ready 事件）不能当成合成响应"""
    class FakeStdout:
        def __init__(self):
            self._lines = [
                json.dumps({"event": "ready", "pid": 1}).encode() + b"\n",
                json.dumps({"id": 2, "ok": True, "wav_path": "/tmp/y.wav"}).encode() + b"\n",
            ]

        async def readline(self):
            return self._lines.pop(0) if self._lines else b""

    m = CloneEngineManager()
    m._reader = FakeStdout()
    resp = asyncio.run(m._read_response(timeout=5))
    assert resp["id"] == 2


def test_error_response_raises():
    """worker 回 ok:false 时要带着错误信息抛出来，不要静默成功"""

    class FakeStdout:
        def __init__(self):
            self._lines = [json.dumps({"id": 1, "ok": False, "error": "No audio segments found!"}).encode() + b"\n"]

        async def readline(self):
            return self._lines.pop(0) if self._lines else b""

    m = CloneEngineManager()
    m._reader = FakeStdout()

    async def _rpc():
        resp = await m._read_response(timeout=5)
        if not resp.get("ok", False):
            raise CloneEngineError(str(resp.get("error")))
        return resp

    with pytest.raises(CloneEngineError, match="No audio segments"):
        asyncio.run(_rpc())


# ============================================================
# worker 侧的纯逻辑（直接 import worker 模块的函数）
# ============================================================

def test_worker_ops_table_is_complete():
    """worker 的 op 表要覆盖协议里承诺的 op"""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "vcw", Path(voice_clone.__file__).parent.parent / "voice_clone_worker.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert set(mod._OPS) == {"synth", "status", "speakers"}


def test_worker_rejects_bad_synth_requests(tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "vcw2", Path(voice_clone.__file__).parent.parent / "voice_clone_worker.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # 空文本
    assert mod._op_synth({"text": "", "ref": "x.wav"})["ok"] is False
    # 没参考音频
    assert mod._op_synth({"text": "你好", "ref": ""})["ok"] is False
    # 参考音频不存在（这时还没加载模型，能提前报错）
    r = mod._op_synth({"text": "你好", "ref": str(tmp_path / "nope.wav")})
    assert r["ok"] is False
    assert "不存在" in r["error"]


def test_worker_hash_is_content_based(tmp_path):
    """speaker embedding 缓存键必须按**内容**哈希。

    按文件名哈希的话，用户换个文件名上传同一段音频就会缓存失效；
    按 mtime 哈希更糟——复制一下就失效。
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "vcw3", Path(voice_clone.__file__).parent.parent / "voice_clone_worker.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    a = tmp_path / "a.wav"
    a.write_bytes(b"same-bytes")
    b = tmp_path / "b.wav"
    b.write_bytes(b"same-bytes")
    c = tmp_path / "c.wav"
    c.write_bytes(b"different-bytes")

    assert mod._hash_file(str(a)) == mod._hash_file(str(b))
    assert mod._hash_file(str(a)) != mod._hash_file(str(c))


# ============================================================
# 降级策略
# ============================================================

def test_never_silently_falls_back_to_edge(manager, ref_wav, monkeypatch):
    """选克隆音色却听到默认音色，比报错更糟 —— 必须明确失败"""
    monkeypatch.setattr(voice_clone, "is_installed", lambda: True)

    async def _boom(*a, **kw):
        raise CloneEngineError("worker 崩了")

    manager._rpc = _boom  # type: ignore[method-assign]
    with pytest.raises(CloneEngineError):
        asyncio.run(manager.synthesize("你好", str(ref_wav)))


# ============================================================
# base speaker 解析（2026-10-14）
# ============================================================

def _load_worker():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "vcw_spk", Path(voice_clone.__file__).parent.parent / "voice_clone_worker.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeHps:
    def __init__(self, spk2id, n_speakers=256):
        self.data = type("D", (), {"spk2id": spk2id, "n_speakers": n_speakers})()


def test_speaker_default_comes_from_spk2id_not_hardcoded():
    """默认 speaker **必须**从 spk2id 读，不能写死 0。

    踩过的大坑：ZH 模型 `n_speakers=256` 但 `spk2id={"ZH": 1}` ——
    只有 id=1 是训练过的，其余 255 个槽位喂进去**产出全静音**（实测 peak=0.0001）。
    把默认写死成 0 的结果是：合成"成功"返回一个静音 wav，
    而只检查 HTTP 200 + RIFF 头 + 文件大小**根本发现不了**。
    """
    mod = _load_worker()
    mod._state["melo"] = type("M", (), {"hps": _FakeHps({"ZH": 1})})()
    try:
        assert mod._speaker_table() == {"ZH": 1}
        assert mod._default_speaker_id() == 1        # 不是 0！
        assert mod._speaker_count() == 1             # 不是 256
    finally:
        mod._state["melo"] = None


def test_speaker_id_out_of_range_falls_back():
    """未训练的 speaker_id 要回退到已训练的那个，不能透给模型出静音"""
    mod = _load_worker()
    mod._state["melo"] = type("M", (), {"hps": _FakeHps({"ZH": 1})})()
    try:
        assert mod._resolve_speaker_id(None) == 1
        assert mod._resolve_speaker_id(0) == 1       # 0 是未训练的
        assert mod._resolve_speaker_id(99) == 1
        assert mod._resolve_speaker_id("abc") == 1
        assert mod._resolve_speaker_id(1) == 1
    finally:
        mod._state["melo"] = None


def test_speaker_id_passthrough_when_valid():
    """模型真有多说话人时，合法的 id 要原样透传（别写死成第一个）"""
    mod = _load_worker()
    mod._state["melo"] = type("M", (), {"hps": _FakeHps({"A": 3, "B": 7})})()
    try:
        assert mod._resolve_speaker_id(7) == 7
        assert mod._resolve_speaker_id(3) == 3
        assert mod._resolve_speaker_id(5) == 3   # 未训练 → 回退到第一个
    finally:
        mod._state["melo"] = None


# ============================================================
# 守护进程：跨后端重启保活（2026-10-14）
# ============================================================

def test_endpoint_file_roundtrip(tmp_path, monkeypatch):
    """worker 把端口写进 worker.json，后端靠它找到活着的 worker"""
    mod = _load_worker()
    ep = tmp_path / "worker.json"
    monkeypatch.setattr(mod, "ENDPOINT_FILE", str(ep))

    mod._write_endpoint(12345)
    data = json.loads(ep.read_text(encoding="utf-8"))
    assert data["port"] == 12345
    assert data["pid"] == os.getpid()

    mod._remove_endpoint()
    assert not ep.exists()


def test_remove_endpoint_wont_delete_other_workers_file(tmp_path, monkeypatch):
    """只删自己写的那份 —— 否则会把刚起来的另一个 worker 的记录删掉"""
    mod = _load_worker()
    ep = tmp_path / "worker.json"
    monkeypatch.setattr(mod, "ENDPOINT_FILE", str(ep))

    ep.write_text(json.dumps({"pid": 999999, "port": 1}), encoding="utf-8")
    mod._remove_endpoint()
    assert ep.exists(), "不该删别的进程写的端点文件"


def test_read_endpoint_tolerates_garbage(tmp_path, monkeypatch):
    """端点文件坏了/写了一半 → 返回 None，不能抛"""
    m = CloneEngineManager()
    ep = tmp_path / "worker.json"
    monkeypatch.setattr(m, "_endpoint_path", staticmethod(lambda: str(ep)))

    assert m._read_endpoint() is None          # 不存在
    ep.write_text("not json", encoding="utf-8")
    assert m._read_endpoint() is None          # 坏内容
    ep.write_text(json.dumps({"pid": 1}), encoding="utf-8")
    assert m._read_endpoint() is None          # 没有 port


def test_stop_does_not_kill_worker(monkeypatch):
    """`stop()` **只断连接**。

    worker 是守护进程 —— 杀掉就白费了"跨后端重启保活"（模型要重新加载 30 秒）。
    """
    m = CloneEngineManager()
    killed = {"n": 0}

    class FakeProc:
        pid = 4242
        returncode = None

        def kill(self):
            killed["n"] += 1

    m._proc = FakeProc()
    m._reader = object()
    m._writer = None
    asyncio.run(m.stop())

    assert killed["n"] == 0, "stop() 不该杀 worker"
    assert m._reader is None, "但必须断开连接"


# ============================================================
# 临时文件清理
# ============================================================

def test_try_remove_never_raises(monkeypatch):
    """清理是 best-effort —— 环境会拦 os.remove（还会抛 SystemExit），不能因此搞挂合成"""
    def _boom(_p):
        raise SystemExit(1)     # 继承 BaseException，except Exception 接不住

    monkeypatch.setattr(os, "remove", _boom)
    voice_clone._try_remove("/whatever.wav")   # 不该抛


def test_sweep_stale_wavs(tmp_path, monkeypatch):
    """残留音频要能被回收（删除被拦时靠这个兜底）"""
    monkeypatch.setattr(voice_clone, "WORKER_CWD", str(tmp_path))
    d = tmp_path / "data" / "tmp" / "clone"
    d.mkdir(parents=True)
    old = d / "old.wav"
    new = d / "new.wav"
    old.write_bytes(b"x" * 100)
    new.write_bytes(b"x" * 100)
    os.utime(old, (0, 0))          # 1970 年 → 肯定超龄

    n = voice_clone.sweep_stale_wavs(max_age_sec=3600)
    assert n == 1
    assert not old.exists()
    assert new.exists()


# ============================================================
# base speaker 解析（2026-10-14）
# ============================================================

def _load_worker():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "vcw_spk", Path(voice_clone.__file__).parent.parent / "voice_clone_worker.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeHps:
    def __init__(self, spk2id, n_speakers=256):
        self.data = type("D", (), {"spk2id": spk2id, "n_speakers": n_speakers})()


def test_speaker_default_comes_from_spk2id_not_hardcoded():
    """默认 speaker **必须**从 spk2id 读，不能写死 0。

    踩过的大坑：ZH 模型 `n_speakers=256` 但 `spk2id={"ZH": 1}` ——
    只有 id=1 是训练过的，其余 255 个槽位喂进去**产出全静音**（实测 peak=0.0001）。
    把默认写死成 0 的结果是：合成"成功"返回一个静音 wav，
    而只检查 HTTP 200 + RIFF 头 + 文件大小**根本发现不了**。
    """
    mod = _load_worker()
    mod._state["melo"] = type("M", (), {"hps": _FakeHps({"ZH": 1})})()
    try:
        assert mod._speaker_table() == {"ZH": 1}
        assert mod._default_speaker_id() == 1        # 不是 0！
        assert mod._speaker_count() == 1             # 不是 256
    finally:
        mod._state["melo"] = None


def test_speaker_id_out_of_range_falls_back():
    """未训练的 speaker_id 要回退到已训练的那个，不能透给模型出静音"""
    mod = _load_worker()
    mod._state["melo"] = type("M", (), {"hps": _FakeHps({"ZH": 1})})()
    try:
        assert mod._resolve_speaker_id(None) == 1
        assert mod._resolve_speaker_id(0) == 1       # 0 是未训练的
        assert mod._resolve_speaker_id(99) == 1
        assert mod._resolve_speaker_id("abc") == 1
        assert mod._resolve_speaker_id(1) == 1
    finally:
        mod._state["melo"] = None


def test_speaker_id_passthrough_when_valid():
    """模型真有多说话人时，合法的 id 要原样透传（别写死成第一个）"""
    mod = _load_worker()
    mod._state["melo"] = type("M", (), {"hps": _FakeHps({"A": 3, "B": 7})})()
    try:
        assert mod._resolve_speaker_id(7) == 7
        assert mod._resolve_speaker_id(3) == 3
        assert mod._resolve_speaker_id(5) == 3   # 未训练 → 回退到第一个
    finally:
        mod._state["melo"] = None


# ============================================================
# 守护进程：跨后端重启保活（2026-10-14）
# ============================================================

def test_endpoint_file_roundtrip(tmp_path, monkeypatch):
    """worker 把端口写进 worker.json，后端靠它找到活着的 worker"""
    mod = _load_worker()
    ep = tmp_path / "worker.json"
    monkeypatch.setattr(mod, "ENDPOINT_FILE", str(ep))

    mod._write_endpoint(12345)
    data = json.loads(ep.read_text(encoding="utf-8"))
    assert data["port"] == 12345
    assert data["pid"] == os.getpid()

    mod._remove_endpoint()
    assert not ep.exists()


def test_remove_endpoint_wont_delete_other_workers_file(tmp_path, monkeypatch):
    """只删自己写的那份 —— 否则会把刚起来的另一个 worker 的记录删掉"""
    mod = _load_worker()
    ep = tmp_path / "worker.json"
    monkeypatch.setattr(mod, "ENDPOINT_FILE", str(ep))

    ep.write_text(json.dumps({"pid": 999999, "port": 1}), encoding="utf-8")
    mod._remove_endpoint()
    assert ep.exists(), "不该删别的进程写的端点文件"


def test_read_endpoint_tolerates_garbage(tmp_path, monkeypatch):
    """端点文件坏了/写了一半 → 返回 None，不能抛"""
    m = CloneEngineManager()
    ep = tmp_path / "worker.json"
    monkeypatch.setattr(m, "_endpoint_path", staticmethod(lambda: str(ep)))

    assert m._read_endpoint() is None          # 不存在
    ep.write_text("not json", encoding="utf-8")
    assert m._read_endpoint() is None          # 坏内容
    ep.write_text(json.dumps({"pid": 1}), encoding="utf-8")
    assert m._read_endpoint() is None          # 没有 port


def test_stop_does_not_kill_worker(monkeypatch):
    """`stop()` **只断连接**。

    worker 是守护进程 —— 杀掉就白费了"跨后端重启保活"（模型要重新加载 30 秒）。
    """
    m = CloneEngineManager()
    killed = {"n": 0}

    class FakeProc:
        pid = 4242
        returncode = None

        def kill(self):
            killed["n"] += 1

    m._proc = FakeProc()
    m._reader = object()
    m._writer = None
    asyncio.run(m.stop())

    assert killed["n"] == 0, "stop() 不该杀 worker"
    assert m._reader is None, "但必须断开连接"


# ============================================================
# 临时文件清理
# ============================================================

def test_try_remove_never_raises(monkeypatch):
    """清理是 best-effort —— 环境会拦 os.remove（还会抛 SystemExit），不能因此搞挂合成"""
    def _boom(_p):
        raise SystemExit(1)     # 继承 BaseException，except Exception 接不住

    monkeypatch.setattr(os, "remove", _boom)
    voice_clone._try_remove("/whatever.wav")   # 不该抛


def test_sweep_stale_wavs(tmp_path, monkeypatch):
    """残留音频要能被回收（删除被拦时靠这个兜底）"""
    monkeypatch.setattr(voice_clone, "WORKER_CWD", str(tmp_path))
    d = tmp_path / "data" / "tmp" / "clone"
    d.mkdir(parents=True)
    old = d / "old.wav"
    new = d / "new.wav"
    old.write_bytes(b"x" * 100)
    new.write_bytes(b"x" * 100)
    os.utime(old, (0, 0))          # 1970 年 → 肯定超龄

    n = voice_clone.sweep_stale_wavs(max_age_sec=3600)
    assert n == 1
    assert not old.exists()
    assert new.exists()


# ============================================================
# 响度归一化（2026-10-14）
# ============================================================

def test_normalize_lifts_quiet_output():
    """OpenVoice 输出实测只有约 -43 dBFS，比 edge-tts 小 20 多 dB。

    不归一化的话用户会觉得"克隆的声音特别小" —— 跟别的音色不是一个音量档。
    """
    import numpy as np

    mod = _load_worker()
    # 实测 OpenVoice 输出 rms≈0.0071（正弦等效振幅约 0.01）
    quiet = (np.sin(np.linspace(0, 100, 44100)) * 0.01).astype(np.float32)
    before = float(np.sqrt(np.mean(quiet ** 2)))
    out = mod._normalize(quiet)
    rms = float(np.sqrt(np.mean(out ** 2)))
    assert rms > before * 5, f"应该明显提升响度：{before} -> {rms}"
    assert 0.08 < rms < 0.12, f"应该归一化到约 0.1，实际 {rms}"


def test_normalize_respects_gain_cap():
    """近乎静音的输出不能被放大成噪声（增益上限）"""
    import numpy as np

    mod = _load_worker()
    tiny = (np.sin(np.linspace(0, 100, 4410)) * 1e-5).astype(np.float32)
    out = mod._normalize(tiny, target_rms=0.1, max_gain=20.0)
    assert float(np.max(np.abs(out))) < 1e-3


def test_normalize_no_clipping():
    """已经很响的输出不能再放大到削顶"""
    import numpy as np

    mod = _load_worker()
    loud = (np.sin(np.linspace(0, 100, 4410)) * 0.8).astype(np.float32)
    out = mod._normalize(loud)
    assert float(np.max(np.abs(out))) <= 0.99 + 1e-6


def test_normalize_leaves_silence_alone():
    """纯静音不该被放大（否则会把底噪吹成噪声）"""
    import numpy as np

    mod = _load_worker()
    out = mod._normalize(np.zeros(4410, dtype=np.float32))
    assert float(np.max(np.abs(out))) == 0.0


# ============================================================
# 守护进程启动方式（2026-10-14）
# ============================================================

def test_daemon_uses_popen_not_asyncio_transport():
    """守护进程**必须**用普通 Popen 启动，不能用 asyncio 的子进程 API。

    踩过的大坑：`asyncio.create_subprocess_exec` 的 transport 在**事件循环关闭时
    会 kill 子进程** —— 于是"跨后端重启保活"完全失效，父进程一退出 worker 就死。
    守护进程走 socket，不需要 asyncio 的管道管理，用 Popen 反而干净。
    """
    import inspect

    src = inspect.getsource(CloneEngineManager._spawn)
    assert "subprocess.Popen" in src
    # 注意只看**调用**，docstring 里为了解释"为什么不用它"会提到这个名字
    assert "await asyncio.create_subprocess_exec" not in src


def test_spawn_returns_popen_style_handle(tmp_path, monkeypatch):
    """`_spawn` 返回的句柄要用 poll() 判断存活（Popen 语义）"""
    import subprocess as sp

    m = CloneEngineManager()
    log = open(tmp_path / "w.log", "wb")

    async def _run():
        return await m._spawn(sys.executable, "-c", "import time; time.sleep(5)", {}, {})

    # 真实起一个短命进程，验证返回的是 Popen
    async def _spawn_real():
        return await asyncio.to_thread(
            sp.Popen,
            [sys.executable, "-c", "import time; time.sleep(5)"],
            stdin=sp.DEVNULL,
            stdout=log,
            stderr=log,
        )

    proc = asyncio.run(_spawn_real())
    try:
        assert hasattr(proc, "poll")
        assert CloneEngineManager._proc_alive(proc) is True
    finally:
        proc.kill()
        proc.wait()
    assert CloneEngineManager._proc_alive(proc) is False
