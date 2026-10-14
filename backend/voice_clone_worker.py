"""OpenVoice V2 音色克隆 sidecar（**在独立 venv `.venv-clone` 里跑**）。

## 为什么要有独立 venv

主 venv 是 `numpy 2.4.6`，而 MeloTTS / OpenVoice 的 requirements 钉的是
`numpy==1.22.0` + `transformers==4.27.4`。**装进同一个 venv 会把 numpy 降级，
很可能把正在跑的 RAG / 后端搞挂。** 所以克隆引擎整个隔离到 `.venv-clone`。

## 协议（JSON Lines，一行一请求一行一响应）

```jsonc
// 请求（stdin）
{"id": 1, "op": "synth", "text": "你好", "ref": "data/voice_refs/a.wav", "lang": "ZH", "speed": 1.0}
// 响应（stdout）
{"id": 1, "ok": true, "wav_b64": "UklGR..."}
{"id": 1, "ok": false, "error": "..."}
```

**stdout 只走协议**；日志打到 stderr（`{"event": "ready", ...}`）。

## 合成流程（OpenVoice V2 标准三步，但绕开了两个重依赖）

1. MeloTTS 用**中性 base speaker** 合成中间音频
2. `converter.extract_se(ref)` → 参考音色 embedding（**不走 `get_se()`**：
   它内部调 `whisper_timestamped.get_vad_segments`，会拖进 faster-whisper +
   一堆模型；`extract_se` 直接用 librosa 加载，等价但不引入那些依赖）
3. `converter.convert(中间音频, base_se, ref_se)` → 目标音色

两个刻意的取舍：
- **`enable_watermark=False`**：默认 True 会 import `wavmark`（我们没装）
- **`disable_bert=True`**：关掉中文 RoBERTa，省 ~1.3GB 下载，也更快。
  代价是韵律略差；对"角色念台词"完全够。
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import io
import json
import logging
import os
import sys
import tempfile
import time
import traceback

# 必须在 import openvoice/melo **之前**设置：它俩走 huggingface_hub 下模型，
# 国内直连 huggingface.co 不通，必须走镜像
os.environ.setdefault("HF_ENDPOINT", os.environ.get("OPENVOICE_HF_ENDPOINT", "https://hf-mirror.com"))
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="[voice-clone-worker] %(levelname)s %(message)s",
)
log = logging.getLogger("voice-clone-worker")

# 进程根目录（backend/）—— 让相对路径的权重/参考音频能解析
os.chdir(os.environ.get("VOICE_CLONE_CWD", os.getcwd()))

_state: dict = {
    "melo": None,
    "converter": None,
    "base_se": None,
    "se_cache": {},     # sha256(ref bytes) -> tensor
    "device": "cpu",
    "lang": "ZH",
    "sample_rate": 44100,
}


def _log_event(event: str, **payload) -> None:
    """给主进程看的就绪/错误事件。

    走 **stdout**（协议流），因为主进程是在 stdout 上等它的。
    普通日志一律走 stderr，绝不混进 stdout。
    """
    payload.setdefault("event", event)
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# 模型加载
# ---------------------------------------------------------------------------

def _ckpt_dir() -> str:
    return os.environ.get(
        "VOICE_CLONE_CKPT",
        os.path.join("data", "openvoice"),
    )


def _load_models(lang: str) -> float:
    """惰性加载。返回耗时（秒）。重复调用直接返回。"""
    if _state["melo"] is not None:
        return 0.0

    t0 = time.time()
    import torch
    from melo.api import TTS as MeloTTS
    from openvoice.api import ToneColorConverter

    device = _state["device"]
    ckpt = _ckpt_dir()

    # 1) MeloTTS（中性中间音频）
    melo = MeloTTS(language=lang, device=device)
    # 关掉 BERT：省 ~1.3GB 的 RoBERTa 下载，也更快（代价是韵律略差）
    if hasattr(melo, "hps") and getattr(melo.hps, "data", None) is not None:
        melo.hps.data.disable_bert = True
    _state["melo"] = melo
    _state["sample_rate"] = melo.hps.data.sampling_rate
    log.info("MeloTTS 就绪 (%.1fs, sr=%s)", time.time() - t0, _state["sample_rate"])

    # 2) 音色转换器
    # enable_watermark 必须是 False：默认 True 会 import wavmark（没装）
    converter = ToneColorConverter(
        os.path.join(ckpt, "checkpoints", "converter", "config.json"),
        device=device,
        enable_watermark=False,
    )
    converter.load_ckpt(os.path.join(ckpt, "checkpoints", "converter", "checkpoint.pth"))
    _state["converter"] = converter

    # 3) base speaker 的音色 embedding（它是"转换前"那一侧的 embedding）
    se_path = os.path.join(ckpt, "checkpoints", "base_speakers", lang, f"{lang.lower()}_default_se.pth")
    if os.path.isfile(se_path):
        import torch as _torch

        _state["base_se"] = _torch.load(se_path, map_location=device)
        log.info("base_speaker se 已加载: %s", se_path)
    else:
        log.warning("找不到 base se（%s），将用参考音频自身作为 src（效果差一些）", se_path)

    return time.time() - t0


# ---------------------------------------------------------------------------
# 合成
# ---------------------------------------------------------------------------

def _hash_file(path: str) -> str:
    """按**内容**哈希 —— 文件换名字但内容不变时仍能命中缓存"""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _to_wav(ref_path: str) -> str:
    """参考音频统一转成临时 wav。

    为什么不用 pydub：它读 mp3/m4a/ogg 需要 **ffmpeg**，而我们不想为克隆
    再引入一个系统级依赖。librosa + soundfile 能直接读这些格式。
    已经 wav 就直接返回原路径。
    """
    if ref_path.lower().endswith(".wav"):
        return ref_path

    import librosa
    import soundfile as sf

    audio, sr = librosa.load(ref_path, sr=22050, mono=True)
    fd, tmp = tempfile.mkstemp(suffix=".wav", prefix="ref_")
    os.close(fd)
    sf.write(tmp, audio, sr)
    return tmp


def _speaker_se(ref_path: str):
    """参考音色的 speaker embedding，按内容哈希缓存。

    这一步是整条链路最慢的（要对整段参考音频跑一遍编码器），
    同一个角色的参考音频不该每次重算。
    """
    import torch

    key = _hash_file(ref_path)
    cached = _state["se_cache"].get(key)
    if cached is not None:
        return cached

    wav = _to_wav(ref_path)
    try:
        se = _state["converter"].extract_se(wav)
    finally:
        if wav != ref_path:
            try:
                os.remove(wav)
            except OSError:
                pass

    _state["se_cache"][key] = se
    # 缓存上限：参考音频不会太多，但也别无限涨
    if len(_state["se_cache"]) > 8:
        _state["se_cache"].pop(next(iter(_state["se_cache"])))
    return se


def _speaker_table() -> dict:
    """MeloTTS 的说话人表（名字 → id），来自 `hps.data.spk2id`。

    **不要硬编码 speaker_id。** ZH 模型的配置是：
        "n_speakers": 256,   ← 架构上的槽位数
        "spk2id": {"ZH": 1}  ← 实际**只训练了 1 个**，id 是 1
    其余 255 个槽位是未训练的，喂进去**产出全静音**（实测 peak=0.0001）。
    踩过：把默认写死成 0，于是合成"成功"返回一个静音 wav ——
    只检查文件格式和大小根本发现不了。

    官方用法就是 `model.tts_to_file(text, spk2id['ZH'], ...)`，跟着它走。
    """
    melo = _state.get("melo")
    if melo is None:
        return {}
    try:
        table = dict(melo.hps.data.spk2id)
    except (AttributeError, TypeError):
        return {}
    return table


def _default_speaker_id() -> int:
    """唯一（或第一个）已训练的说话人 id。拿不到就退回 0。"""
    table = _speaker_table()
    if not table:
        return 0
    return int(next(iter(table.values())))


def _speaker_count() -> int:
    """**已训练**的说话人数量（不是 `n_speakers`，那个是槽位数）"""
    return len(_speaker_table())


def _resolve_speaker_id(raw) -> int:
    """把请求里的 speaker_id 夹到**已训练**的范围内。

    越界不能直接透给模型 —— 未训练的槽位会产出静音，而且不报错，
    用户只会觉得"克隆出来没声音"。
    """
    table = _speaker_table()
    valid = set(int(v) for v in table.values())
    default = _default_speaker_id()

    try:
        sid = int(raw)
    except (TypeError, ValueError):
        return default

    if valid and sid not in valid:
        log.warning(
            "speaker_id=%s 不在已训练集合 %s 里（喂进去会出静音），退回 %s",
            sid, sorted(valid), default,
        )
        return default
    return sid


def _normalize(audio, target_rms: float = 0.1, max_gain: float = 20.0):
    """把克隆输出拉到正常响度。

    OpenVoice 的转换输出实测只有约 **-43 dBFS**（rms 0.007），比 edge-tts 小 20 多 dB ——
    直接用的话用户会觉得"克隆的声音特别小"，跟别的音色完全不是一个音量档。

    用 **RMS 归一**而不是峰值归一：峰值会被单个瞬态带偏，导致整体还是偏小。
    增益上限 `max_gain`（默认 +26dB）防止把近乎静音的输出放大成噪声 ——
    实测那个 -43dBFS 需要约 14 倍才能到目标，所以上限给到 20 才够用。
    """
    import numpy as np

    a = np.asarray(audio, dtype=np.float32)
    cur = float(np.sqrt(np.mean(a ** 2))) if a.size else 0.0
    if cur <= 1e-6:
        return a                      # 真是静音就别放大了

    gain = min(target_rms / cur, max_gain)
    a = a * gain
    peak = float(np.max(np.abs(a))) if a.size else 0.0
    if peak > 0.99:                   # 峰值保护，别削顶
        a = a * (0.99 / peak)
    return a


def _op_synth(req: dict) -> dict:
    text = (req.get("text") or "").strip()
    ref = req.get("ref") or ""
    lang = (req.get("lang") or "ZH").upper()
    speed = float(req.get("speed") or 1.0)

    if not text:
        return {"ok": False, "error": "text 不能为空"}
    if not ref:
        return {"ok": False, "error": "ref（参考音频）不能为空"}
    if not os.path.isfile(ref):
        return {"ok": False, "error": f"参考音频不存在：{ref}"}

    # 把模型加载期间的 stdout 重定向到 stderr：
    # OpenVoice 的 `load_ckpt()` 直接 `print()`（"Loaded checkpoint ..."），
    # 会污染 JSON-lines 协议流，必须按掉
    with contextlib.redirect_stdout(sys.stderr):
        t_load = _load_models(lang)
    if t_load:
        log.info("模型已加载，本次耗时 %.1fs", t_load)

    melo = _state["melo"]
    converter = _state["converter"]

    # 1) MeloTTS 合成中间音频（用 base speaker 的中性音）
    with tempfile.TemporaryDirectory(prefix="clone_") as tmpdir:
        raw_path = os.path.join(tmpdir, "raw.wav")
        speaker_id = _resolve_speaker_id(req.get("speaker_id"))
        melo.tts_to_file(text, speaker_id, raw_path, speed=speed, quiet=True)

        if not os.path.isfile(raw_path) or os.path.getsize(raw_path) == 0:
            return {"ok": False, "error": "MeloTTS 没有产出音频"}

        # 2) 目标音色 embedding
        tgt_se = _speaker_se(ref)
        # 注意不能写 `base_se or tgt_se` —— Tensor 的布尔值是歧义的（多元素时直接 RuntimeError）
        src_se = _state["base_se"] if _state["base_se"] is not None else tgt_se

        # 3) 转换
        audio = converter.convert(raw_path, src_se=src_se, tgt_se=tgt_se)

    # 编码成 wav 文件，把**路径**回给主进程。
    #
    # 为什么不用 base64 塞进 stdout：音频动辄几百 KB，base64 再涨 33%，
    # 而且单行 JSON 会超过 asyncio readline 的默认 64KB 上限（踩过）。
    import numpy as np
    import soundfile as sf

    out_dir = os.environ.get("VOICE_CLONE_OUT_DIR", os.path.join("data", "tmp", "clone"))
    os.makedirs(out_dir, exist_ok=True)
    fd, out_path = tempfile.mkstemp(prefix="clone_", suffix=".wav", dir=out_dir)
    os.close(fd)
    arr = _normalize(audio)
    sf.write(out_path, arr, _state["sample_rate"], format="WAV")

    return {
        "wav_path": os.path.abspath(out_path),
        "bytes": os.path.getsize(out_path),
        "seconds": round(arr.size / float(_state["sample_rate"]), 3),
    }


def _op_status(_req: dict | None = None) -> dict:
    return {
        "ok": True,
        "loaded": _state["melo"] is not None,
        "device": _state["device"],
        "lang": _state["lang"],
        "sample_rate": _state["sample_rate"],
        # 已训练的说话人数量（不是 n_speakers，那是架构槽位数）
        "speakers": _speaker_count(),
        "se_cache": len(_state["se_cache"]),
        "ckpt_dir": _ckpt_dir(),
    }


def _op_speakers(req: dict | None = None) -> dict:
    """列出**已训练**的 base speaker。

    实测 ZH 模型只有 1 个（`spk2id = {"ZH": 1}`），所以这里通常只返回一项 ——
    别在前端做成"256 选一"的下拉，那 255 个喂进去只会出静音。
    """
    with contextlib.redirect_stdout(sys.stderr):
        _load_models(_state["lang"])
    table = _speaker_table()
    return {
        "ok": True,
        "total": _speaker_count(),
        "slots": _state["melo"].hps.data.n_speakers if _state.get("melo") else 0,
        "default": _default_speaker_id(),
        "speakers": [{"name": k, "id": int(v)} for k, v in table.items()],
    }


_OPS = {
    "synth": _op_synth,
    "status": _op_status,
    "speakers": _op_speakers,
}


# ---------------------------------------------------------------------------
# 主循环：两种模式
# ---------------------------------------------------------------------------
#
# 默认（stdio）：一行一请求，进程随父进程死。测试与手工调试用这个。
#
# `--daemon`：绑 127.0.0.1 的随机端口，把端口写进 `worker.json`。
#   **这是给生产用的** —— 后端重启时守护进程活着，模型不用重新加载
#   （省掉 20 秒的冷启动）。所以它**故意不是后端的子进程语义**。

#: 守护进程把「我在哪个端口」写在这里，后端靠它找到活着的 worker
ENDPOINT_FILE = os.environ.get(
    "VOICE_CLONE_ENDPOINT", os.path.join("data", "tmp", "clone", "worker.json")
)

#: 守护进程空闲多久自动退出（秒）。默认 20 分钟：
#: 够跨过后端重启，又不会在没人用克隆时白占 480MB 内存。
IDLE_EXIT_SEC = int(os.environ.get("VOICE_CLONE_IDLE_EXIT", "1200"))


def _endpoint_path() -> str:
    return os.path.abspath(ENDPOINT_FILE)


def _write_endpoint(port: int) -> None:
    path = _endpoint_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(
            {"pid": os.getpid(), "port": port, "host": "127.0.0.1", "started": time.time()},
            fh,
        )
    os.replace(tmp, path)   # 原子替换，避免后端读到写了一半的文件


def _remove_endpoint() -> None:
    try:
        path = _endpoint_path()
        # 只删自己写的那个（别把刚起来的另一个 worker 的记录删掉）
        with open(path, encoding="utf-8") as fh:
            if json.load(fh).get("pid") != os.getpid():
                return
        os.remove(path)
    except (OSError, ValueError):
        pass


def _handle_line(line: str) -> dict:
    """处理一条请求，返回响应（不含 id）。异常一律转成 ok:false。"""
    try:
        req = json.loads(line)
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"JSON 解析失败: {e}"}

    op = req.get("op")
    handler = _OPS.get(op)
    if handler is None:
        return {"ok": False, "error": f"未知 op: {op!r}"}
    try:
        return {"ok": True, **handler(req)}
    except Exception as e:  # noqa: BLE001 - 单条失败不能让进程死掉
        log.error("op=%s 失败: %s\n%s", op, e, traceback.format_exc())
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _run_stdio() -> int:
    _log_event("ready", mode="stdio", pid=os.getpid(), cwd=os.getcwd(), ckpt=_ckpt_dir())
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        req = {}
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            pass
        if req.get("op") == "close":
            sys.stdout.write(json.dumps({"id": req.get("id"), "ok": True}) + "\n")
            sys.stdout.flush()
            return 0
        resp = {"id": req.get("id"), **_handle_line(line)}
        sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    return 0


async def _run_daemon(port: int) -> int:
    """TCP 守护进程。**不是**后端的子进程语义 —— 后端重启它继续活着。"""
    last_active = time.monotonic()
    #: 收到 shutdown 时置位，让主循环退出。
    #: 不能在连接回调里直接抛异常了事 —— 那个异常是 asyncio 内部 task 的，
    #: 没人接，主循环照跑不误（踩过：shutdown 之后进程还在）。
    stop = asyncio.Event()

    async def _client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        nonlocal last_active
        try:
            while True:
                raw = await reader.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                last_active = time.monotonic()
                try:
                    req = json.loads(line)
                except json.JSONDecodeError:
                    req = {}
                if req.get("op") == "shutdown":
                    writer.write((json.dumps({"id": req.get("id"), "ok": True}) + "\n").encode())
                    await writer.drain()
                    stop.set()
                    return
                resp = {"id": req.get("id"), **_handle_line(line)}
                writer.write((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
                await writer.drain()
        except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError):
            pass
        finally:
            with contextlib.suppress(Exception):
                writer.close()

    server = await asyncio.start_server(_client, "127.0.0.1", port)
    actual_port = server.sockets[0].getsockname()[1]
    _write_endpoint(actual_port)
    _log_event(
        "ready",
        mode="daemon",
        pid=os.getpid(),
        port=actual_port,
        cwd=os.getcwd(),
        ckpt=_ckpt_dir(),
        idle_exit=IDLE_EXIT_SEC,
    )
    log.info("守护进程监听 127.0.0.1:%d（空闲 %ds 后退出）", actual_port, IDLE_EXIT_SEC)

    try:
        async with server:
            while not stop.is_set():
                # 空闲回收：没人连、且超过阈值就自己退出，别白占内存
                if IDLE_EXIT_SEC > 0 and time.monotonic() - last_active > IDLE_EXIT_SEC:
                    log.info("空闲超过 %ds，退出", IDLE_EXIT_SEC)
                    break
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=5)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        _remove_endpoint()
        log.info("守护进程退出，已清理端点文件")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--daemon" in argv:
        port = 0
        for i, a in enumerate(argv):
            if a == "--port" and i + 1 < len(argv):
                port = int(argv[i + 1])
        return asyncio.run(_run_daemon(port))
    return _run_stdio()


if __name__ == "__main__":
    sys.exit(main())
