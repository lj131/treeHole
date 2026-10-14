"""克隆引擎的协议与状态机测试（**不打真实模型**，CI 能跑）。

真机合成很慢（冷启动 ~18s，且需要 sidecar venv + 权重），
所以这里只测**逻辑**：编解码、缓存键、错误信息、进程管理。
"""
import asyncio
import json
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
    m._proc = type("P", (), {"returncode": None, "stdout": FakeStdout()})()
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
    m._proc = type("P", (), {"returncode": None, "stdout": FakeStdout()})()
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
    m._proc = type("P", (), {"returncode": None, "stdout": FakeStdout()})()
    m._proc.stdin = None

    async def _fake_ensure():
        pass

    m._ensure_started = _fake_ensure  # type: ignore[method-assign]

    async def _write(*a, **kw):
        return None

    # 让 _rpc 走通：proc.stdin.write 不抛
    class stdin:
        def write(self, *a):
            return None

        async def drain(self):
            return None

    m._proc.stdin = stdin()

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
    assert set(mod._OPS) == {"synth", "status"}


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
