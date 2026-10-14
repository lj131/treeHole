"""音色克隆引擎（OpenVoice V2）在主进程侧的封装。

## 架构（**为什么这么设计**）

克隆引擎跑在**独立 venv** `.venv-clone` 里，因为它要 `numpy 1.x` +
`transformers 4.x`，而主 venv 是 `numpy 2.x`（在跑 RAG/后端）——
**装进同一个 venv 会把 numpy 降级，很可能把正在用的东西搞挂**。

两个进程之间用 **JSON Lines over stdin/stdout** 通信（见 `voice_clone_worker.py`）：

- 常驻进程，**模型加载一次后复用**。每句合成都起进程的话，
  MeloTTS + converter 光加载就要好几秒，交互上不可接受。
- 不占端口、不需要额外 supervisor。进程崩了下次请求自动重启。
- asyncio 子进程（`create_subprocess_exec`），**不阻塞事件循环**。

## 失败策略：**明确报错，不静默降级**

用户选了克隆音色却听到默认音色，是比报错更糟的体验。
所以：sidecar 没装 → 报"怎么装"；合成失败 → 报失败。绝不回退到 edge。
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

#: 本文件在 backend/funcation/ 下，往上三层是仓库根
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: sidecar venv 的 python 路径（可被 VOICE_CLONE_VENV 覆盖）
SIDECAR_VENV = os.environ.get("VOICE_CLONE_VENV", os.path.join(_REPO_ROOT, ".venv-clone"))
SIDECAR_PYTHON = os.path.join(SIDECAR_VENV, "Scripts", "python.exe")
WORKER_SCRIPT = os.path.join(_BACKEND_DIR, "voice_clone_worker.py")

#: worker 的工作目录（backend/），让 data/openvoice、data/voice_refs 这些相对路径可解析
WORKER_CWD = _BACKEND_DIR

#: 单条合成的超时（模型冷启动 + 首句合成可能到几十秒，给足余量）
SYNTH_TIMEOUT_SEC = int(os.getenv("VOICE_CLONE_TIMEOUT", "180"))
#: worker 空闲多久后自动退出（省内存；下次请求会重新拉起）
IDLE_TIMEOUT_SEC = int(os.getenv("VOICE_CLONE_IDLE", "600"))


class CloneEngineError(RuntimeError):
    """克隆引擎不可用 / 合成失败。`hint` 里给可操作的下一步。"""

    def __init__(self, message: str, hint: Optional[str] = None):
        super().__init__(message)
        self.hint = hint


def is_installed() -> bool:
    """sidecar venv 是否已装好。

    只检查 python.exe 在不在，**不启动进程** —— 这个函数会被
    `/voice/voices` 频繁调用，启动进程要好几秒。
    """
    return os.path.isfile(SIDECAR_PYTHON)


def install_hint() -> str:
    return (
        "克隆引擎（OpenVoice V2）尚未安装。\n"
        "运行 backend/scripts/setup_clone_env.ps1 安装"
        "（需要约 4GB 磁盘：torch + 约 480MB 权重）。\n"
        "装好后重启后端即可，不需要改任何代码。"
    )


class CloneEngineManager:
    """管理 sidecar worker 进程的生命周期与请求/响应。

    单例：`voice_clone.engine`。
    """

    def __init__(self) -> None:
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._lock = asyncio.Lock()
        self._req_id = 0
        self._last_used = 0.0

    # ── 进程管理 ────────────────────────────────────────────────────

    async def _ensure_started(self) -> None:
        if not is_installed():
            raise CloneEngineError("克隆引擎未安装", install_hint())

        if self._proc is not None and self._proc.returncode is None:
            return

        worker = os.path.abspath(WORKER_SCRIPT)
        if not os.path.isfile(worker):
            raise CloneEngineError(f"worker 脚本不存在：{worker}")

        logger.info("[voice-clone] 启动 sidecar worker: %s", SIDECAR_PYTHON)
        self._proc = await asyncio.create_subprocess_exec(
            SIDECAR_PYTHON,
            worker,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=None,          # 直接继承，日志就进后端 stderr
            cwd=WORKER_CWD,
            env={
                **os.environ,
                # 主进程可能是中文 locale；sidecar 的 strptime 日期解析在非英文
                # locale 下会失效（会掩盖真错误），所以强制 C locale
                "LC_ALL": "C",
                "PYTHONIOENCODING": "utf-8",
                "PYTHONUTF8": "1",
            },
        )
        self._req_id = 0
        # 等 worker 就绪（模型是**惰性**加载的，ready 只代表进程起来了）。
        # 注意：worker 的 ready 事件在 stdout 上，但可能夹在第三方库的 print 里，
        # 所以一直读到出现带 `event` 的行为止。
        payload: Dict[str, Any] = {}
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            line = await self._read_line(timeout=min(5.0, deadline - time.monotonic()))
            if line is None:
                continue
            try:
                candidate = json.loads(line)
            except json.JSONDecodeError:
                logger.debug("[voice-clone] 启动时跳过非协议行: %s", line[:80])
                continue
            if isinstance(candidate, dict) and candidate.get("event"):
                payload = candidate
                break
        if not payload.get("event"):
            raise CloneEngineError(
                "克隆引擎启动失败（未收到就绪事件）",
                "看后端 stderr 里 [voice-clone-worker] 开头的日志",
            )
        logger.info(
            "[voice-clone] worker 就绪 pid=%s ckpt=%s hf=%s",
            payload.get("pid"),
            payload.get("ckpt"),
            payload.get("hf"),
        )

    async def _read_response(self, timeout: float) -> Optional[Dict[str, Any]]:
        """读一条协议响应。

        **会跳过非 JSON 行** —— 第三方库（OpenVoice/MeloTTS）偶尔会直接 `print()`
        到 stdout，把协议流弄脏。宁可跳过这一行，也不要让整个请求失败。
        """
        if self._proc is None or self._proc.stdout is None:
            return None
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                raw = await asyncio.wait_for(self._proc.stdout.readline(), timeout=remaining)
            except asyncio.TimeoutError:
                return None
            if not raw:
                return None
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                resp = json.loads(line)
            except json.JSONDecodeError:
                logger.debug("[voice-clone] 跳过非协议行（%d 字符）: %s", len(line), line[:80])
                continue
            if not isinstance(resp, dict) or resp.get("id") is None:
                continue
            return resp

    async def _read_line(self, timeout: float) -> Optional[str]:
        if self._proc is None or self._proc.stdout is None:
            return None
        try:
            raw = await asyncio.wait_for(self._proc.stdout.readline(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
        if not raw:
            return None
        return raw.decode("utf-8", errors="replace").strip()

    async def stop(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            if proc.returncode is None:
                # 优雅关闭，不行了就杀
                proc.stdin.write(b'{"op":"close"}\n')
                await proc.stdin.drain()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=10)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
        except (ProcessLookupError, BrokenPipeError, OSError):
            pass
        logger.info("[voice-clone] worker 已停止")

    # ── 请求 ────────────────────────────────────────────────────────

    async def _rpc(self, payload: Dict[str, Any], timeout: float) -> Dict[str, Any]:
        """发一条请求，等一条响应。进程崩了自动重启重试一次。"""
        await self._ensure_started()
        assert self._proc is not None and self._proc.stdin and self._proc.stdout

        self._req_id += 1
        req = {"id": self._req_id, **payload}

        last_err = ""
        for attempt in (0, 1):
            try:
                self._proc.stdin.write((json.dumps(req, ensure_ascii=False) + "\n").encode("utf-8"))
                await self._proc.stdin.drain()
            except (BrokenPipeError, ConnectionResetError, OSError) as e:
                last_err = f"写入失败：{e}"
                self._proc = None
                if attempt == 0:
                    await self._ensure_started()
                    continue
                break

            resp = await self._read_response(timeout)
            if resp is None:
                last_err = "worker 没有响应（超时或进程退出）"
                self._proc = None
                if attempt == 0:
                    await self._ensure_started()
                    continue
                break

            self._last_used = time.monotonic()
            if not resp.get("ok", False):
                raise CloneEngineError(str(resp.get("error") or "克隆合成失败"))
            return resp

        raise CloneEngineError(
            f"克隆引擎无响应：{last_err}",
            "看后端 stderr 里 [voice-clone-worker] 开头的日志",
        )

    async def status(self) -> Dict[str, Any]:
        if not is_installed():
            return {"installed": False, "hint": install_hint()}
        try:
            resp = await self._rpc({"op": "status"}, timeout=30)
        except CloneEngineError as e:
            return {"installed": True, "error": str(e), "hint": e.hint}
        return {"installed": True, **{k: v for k, v in resp.items() if k != "ok"}}

    async def synthesize(
        self,
        text: str,
        reference_audio: str,
        *,
        lang: str = "ZH",
        speed: float = 1.0,
    ) -> bytes:
        """合成克隆音色的音频，返回 **wav 字节**。"""
        # **先查装没装**，再查参考音频 —— 否则"没装引擎"会被"参考音频不存在"掩盖，
        # 用户照着错误信息去重新上传参考音频，白忙一场（实测踩过）。
        if not is_installed():
            raise CloneEngineError("克隆引擎未安装", install_hint())

        if not text or not text.strip():
            raise CloneEngineError("要合成的文本为空")
        ref = (reference_audio or "").replace("\\", "/").lstrip("/")
        ref_path = ref if os.path.isabs(ref) else os.path.join(os.getcwd(), ref)
        if not os.path.isfile(ref_path):
            raise CloneEngineError(
                f"参考音频不存在：{ref}",
                "在系统配置/语音包里重新上传一段参考音频（10 秒左右、安静环境）",
            )

        async with self._lock:      # worker 是单线程的，别并发打
            resp = await self._rpc(
                {
                    "op": "synth",
                    "text": text,
                    "ref": ref_path,
                    "lang": lang,
                    "speed": speed,
                },
                timeout=SYNTH_TIMEOUT_SEC,
            )

        # worker 把音频写在文件里、只回路径（音频几百 KB，走 stdout 会撞
        # asyncio readline 的 64KB 上限）。读出来就删。
        wav_path = resp.get("wav_path")
        if not wav_path:
            raise CloneEngineError("克隆引擎没有返回音频路径")
        try:
            with open(wav_path, "rb") as fh:
                audio = fh.read()
        except OSError as e:
            raise CloneEngineError(f"读取克隆音频失败：{e}")
        finally:
            try:
                os.remove(wav_path)
            except OSError:
                pass

        if len(audio) < 1024:
            raise CloneEngineError(f"克隆音频异常小（{len(audio)} 字节）")
        logger.info(
            "[voice-clone] 合成完成：%d 字节 / %.2f 秒（文本 %d 字）",
            len(audio),
            float(resp.get("seconds") or 0),
            len(text),
        )
        return audio

    async def close(self) -> None:
        await self.stop()


#: 全局单例
engine = CloneEngineManager()
