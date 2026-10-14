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
import subprocess
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


def _try_remove(path: str) -> None:
    """best-effort 删文件，**绝不向上抛**。

    这个环境的 CLI shim 会拦截 `os.remove`（删较大文件时触发"批量删除保护"），
    而且抛的可能是 `SystemExit` —— 它继承 `BaseException`，`except Exception` 接不住。
    清理失败最多是占点磁盘（有 `sweep_stale_wavs` 兜底），不能因此把合成搞挂。
    """
    try:
        os.remove(path)
    except (Exception, SystemExit) as e:  # noqa: BLE001
        logger.warning("[voice-clone] 清理临时音频失败（不影响结果）：%s（%s）", path, e)


def sweep_stale_wavs(max_age_sec: float = 3600) -> int:
    """清掉一小时前的残留音频。

    正常情况下 manager 读一次就删；但删除可能被环境拦掉，
    不兜底的话 `data/tmp/clone/` 会无限涨。
    """
    d = os.path.join(WORKER_CWD, "data", "tmp", "clone")
    if not os.path.isdir(d):
        return 0
    now, n = time.time(), 0
    for name in os.listdir(d):
        if not name.endswith(".wav"):
            continue
        p = os.path.join(d, name)
        try:
            if now - os.path.getmtime(p) > max_age_sec:
                _try_remove(p)
                n += 1
        except OSError:
            continue
    return n


def install_hint() -> str:
    return (
        "克隆引擎（OpenVoice V2）尚未安装。\n"
        "运行 backend/scripts/setup_clone_env.ps1 安装"
        "（需要约 4GB 磁盘：torch + 约 480MB 权重）。\n"
        "装好后重启后端即可，不需要改任何代码。"
    )


class CloneEngineManager:
    """管理 sidecar worker 的生命周期与请求/响应。

    单例：`voice_clone.engine`。

    ## worker 是**守护进程**，不是后端的子进程

    生产模式下 worker 绑 127.0.0.1 的随机端口，并把端口写进
    `data/tmp/clone/worker.json`。后端启动/重启时**先按这个文件去找活着的 worker**，
    找到就直接连（省掉 20 秒的模型加载）；找不到才拉起新的。

    所以 `stop()` **只断开连接，不杀 worker** —— 杀了就白费了"跨重启保活"这件事。
    worker 自己有空闲超时（`VOICE_CLONE_IDLE_EXIT`，默认 20 分钟）会退出。
    """

    def __init__(self) -> None:
        # stdio 模式用的子进程句柄（测试 / 手工调试）；daemon 模式下为 None
        self._proc: Optional[asyncio.subprocess.Process] = None
        # daemon 模式的长连接
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._lock = asyncio.Lock()
        self._req_id = 0
        self._last_used = 0.0

    # ── 端点发现 ────────────────────────────────────────────────────

    @staticmethod
    def _endpoint_path() -> str:
        return os.path.join(WORKER_CWD, "data", "tmp", "clone", "worker.json")

    def _read_endpoint(self) -> Optional[Dict[str, Any]]:
        try:
            with open(self._endpoint_path(), encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict) or not data.get("port"):
            return None
        return data

    async def _connect_existing(self) -> bool:
        """按 worker.json 去连一个**已经在跑的** worker。连上返回 True。"""
        info = self._read_endpoint()
        if not info:
            return False
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(info["host"], int(info["port"])), timeout=3
            )
        except (OSError, asyncio.TimeoutError, ValueError):
            return False

        # 端口通了不代表是我们的 worker（可能被别的进程占了）—— 问一句确认
        try:
            self._reader, self._writer = reader, writer
            resp = await self._rpc({"op": "status"}, timeout=15)
        except CloneEngineError:
            await self._drop_connection()
            return False
        logger.info(
            "[voice-clone] 复用已在运行的 worker（pid=%s port=%s loaded=%s）",
            info.get("pid"), info.get("port"), resp.get("loaded"),
        )
        return True

    async def _spawn_daemon(self) -> None:
        """拉起一个**脱离后端**的守护进程。

        两个关键点：
        1. `stdout/stderr` **不能接管道** —— 父进程一死管道就断，worker 会写崩。
           所以重定向到日志文件。
        2. Windows 上用 `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`，
           让它在**后端优雅退出**（Ctrl+C / lifespan 关闭）后继续活着。

        ⚠️ **已知局限**：后端被**强杀**（kill -9 / 容器整体重启 / 上层 Job Object
        连坐）时，worker 会一起没。这不是应用层能解决的 —— 要跨那种重启保活，
        得把 worker 做成独立的服务（systemd unit / 单独容器），那是部署的事。
        优雅重启（最常见）是能保住的，实测重连后首句 1.3s（冷启动 30s）。
        """
        worker = os.path.abspath(WORKER_SCRIPT)
        if not os.path.isfile(worker):
            raise CloneEngineError(f"worker 脚本不存在：{worker}")

        log_dir = os.path.join(WORKER_CWD, "data", "tmp", "clone")
        os.makedirs(log_dir, exist_ok=True)
        log_file = open(os.path.join(log_dir, "worker.log"), "ab", buffering=0)

        env = {
            **os.environ,
            # 主进程可能是中文 locale；sidecar 的 strptime 日期解析在非英文
            # locale 下会失效（会掩盖真错误），所以强制 C locale
            "LC_ALL": "C",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        }

        logger.info("[voice-clone] 拉起 sidecar 守护进程: %s", SIDECAR_PYTHON)
        # 三级降级，从"最独立"试到"最保守"：
        #   1) DETACHED | NEW_GROUP | BREAKAWAY_FROM_JOB —— 连上层 Job Object 也脱离
        #      （否则上层一关 Job，worker 会被连坐杀掉，实测踩过）
        #   2) DETACHED | NEW_GROUP —— Job 不允许 breakaway 时的退路
        #   3) 不带标志 —— 至少还能跑，只是跟随父进程生命周期
        flags_tried = [
            0x00000008 | 0x00000200 | 0x01000000,   # DETACHED|NEW_GROUP|BREAKAWAY_FROM_JOB
            0x00000008 | 0x00000200,                # DETACHED|NEW_GROUP
            0,                                      # 裸启动
        ] if os.name == "nt" else [0]

        last_err: Optional[BaseException] = None
        for i, flags in enumerate(flags_tried):
            try:
                self._proc = await self._spawn(
                    worker, log_file, env, {"creationflags": flags} if flags else {}
                )
                if i > 0:
                    logger.warning(
                        "[voice-clone] 前 %d 种 detached 标志被环境拒绝，"
                        "用了第 %d 种（flags=0x%x）—— worker 可能无法跨后端重启存活",
                        i, i + 1, flags,
                    )
                return
            except (OSError, ValueError) as e:
                last_err = e
                logger.debug("[voice-clone] creationflags=0x%x 启动失败：%s", flags, e)
        raise CloneEngineError(f"克隆引擎启动失败：{last_err}")

    async def _spawn(self, worker: str, log_file, env: Dict[str, str], kwargs: Dict[str, Any]):
        """用**普通 `subprocess.Popen`** 启动守护进程，不用 asyncio 的子进程 API。

        这是个踩出来的关键点：`asyncio.create_subprocess_exec` 返回的 transport
        在**事件循环关闭时会 kill 子进程** —— 于是"跨后端重启保活"完全失效，
        父进程一退出 worker 就死（实测：父进程正常 exit 后 worker 也死了）。

        守护进程走的是 socket，不需要 asyncio 的管道管理，用 Popen 反而干净。
        它也不会被 Popen 回收（我们不 wait 它）。
        """
        return await asyncio.to_thread(
            subprocess.Popen,
            [SIDECAR_PYTHON, worker, "--daemon"],
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=log_file,
            cwd=WORKER_CWD,
            env=env,
            close_fds=True,
            **kwargs,
        )

    @staticmethod
    def _proc_alive(proc) -> bool:
        """`Popen` 用 poll()，asyncio 的 Process 用 returncode"""
        if proc is None:
            return False
        if hasattr(proc, "poll"):
            return proc.poll() is None
        return getattr(proc, "returncode", None) is None

    @staticmethod
    def _proc_code(proc):
        if proc is None:
            return None
        if hasattr(proc, "poll"):
            return proc.poll()
        return getattr(proc, "returncode", None)

    async def _ensure_started(self) -> None:
        if not is_installed():
            raise CloneEngineError("克隆引擎未安装", install_hint())

        if self._writer is not None and not self._writer.is_closing():
            return

        # 1) 先找已经在跑的（跨后端重启保活的关键路径）
        if await self._connect_existing():
            return

        # 2) 没有就拉起一个，等它把 worker.json 写出来
        await self._spawn_daemon()
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if await self._connect_existing():
                return
            # 进程已经退了就别再等
            if self._proc is not None and not self._proc_alive(self._proc):
                raise CloneEngineError(
                    f"克隆引擎启动即退出（code={self._proc_code(self._proc)}）",
                    f"看日志 {os.path.join(WORKER_CWD, 'data', 'tmp', 'clone', 'worker.log')}",
                )
            await asyncio.sleep(0.5)

        raise CloneEngineError(
            "克隆引擎启动超时（60s）",
            f"看日志 {os.path.join(WORKER_CWD, 'data', 'tmp', 'clone', 'worker.log')}",
        )

    async def _drop_connection(self) -> None:
        writer, self._writer, self._reader = self._writer, None, None
        if writer is not None:
            try:
                writer.close()
            except (OSError, RuntimeError):
                pass

    async def _read_response(self, timeout: float) -> Optional[Dict[str, Any]]:
        """从当前连接读一条协议响应。

        **会跳过非 JSON 行** —— 第三方库（OpenVoice/MeloTTS）偶尔会直接 `print()`，
        把协议流弄脏。宁可跳过这一行，也不要让整个请求失败。
        """
        reader = self._reader
        if reader is None:
            return None
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                raw = await asyncio.wait_for(reader.readline(), timeout=remaining)
            except (asyncio.TimeoutError, ConnectionResetError, OSError):
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

    async def stop(self) -> None:
        """**只断开连接，不杀 worker。**

        worker 是守护进程 —— 杀掉就白费了"跨后端重启保活"这件事。
        它会按 `VOICE_CLONE_IDLE_EXIT`（默认 20 分钟）自己空闲退出。
        要立刻停掉用 `scripts/stop_clone_worker.ps1`。
        """
        proc, self._proc = self._proc, None
        await self._drop_connection()
        if proc is not None and self._proc_alive(proc):
            # 只可能出现在 stdio 模式（测试里）；daemon 模式是 detached，不该被我们杀
            logger.debug("[voice-clone] 保留 worker 进程 pid=%s", proc.pid)
        logger.info("[voice-clone] 已断开 worker 连接（worker 继续存活）")

    async def shutdown_worker(self) -> bool:
        """真正把 worker 停掉（给运维脚本/测试用）。

        返回是否成功发出去。
        """
        try:
            await self._ensure_started()
            await self._rpc({"op": "shutdown"}, timeout=10)
        except CloneEngineError:
            return False
        finally:
            await self._drop_connection()
        return True

    # ── 请求 ────────────────────────────────────────────────────────

    async def _rpc(self, payload: Dict[str, Any], timeout: float) -> Dict[str, Any]:
        """发一条请求，等一条响应。连接断了就重连重试一次。"""
        await self._ensure_started()
        writer = self._writer
        if writer is None:
            raise CloneEngineError("克隆引擎未连接")

        self._req_id += 1
        req = {"id": self._req_id, **payload}

        last_err = ""
        for attempt in (0, 1):
            try:
                writer.write((json.dumps(req, ensure_ascii=False) + "\n").encode("utf-8"))
                await writer.drain()
            except (BrokenPipeError, ConnectionResetError, OSError) as e:
                last_err = f"写入失败：{e}"
                await self._drop_connection()
                if attempt == 0:
                    await self._ensure_started()
                    writer = self._writer
                    if writer is None:
                        break
                    continue
                break

            resp = await self._read_response(timeout)
            if resp is None:
                last_err = "worker 没有响应（超时或连接断开）"
                await self._drop_connection()
                if attempt == 0:
                    await self._ensure_started()
                    writer = self._writer
                    if writer is None:
                        break
                    continue
                break

            self._last_used = time.monotonic()
            if not resp.get("ok", False):
                raise CloneEngineError(str(resp.get("error") or "克隆合成失败"))
            return resp

        raise CloneEngineError(
            f"克隆引擎无响应：{last_err}",
            f"看日志 {os.path.join(WORKER_CWD, 'data', 'tmp', 'clone', 'worker.log')}",
        )

    async def status(self) -> Dict[str, Any]:
        if not is_installed():
            return {"installed": False, "hint": install_hint()}
        try:
            resp = await self._rpc({"op": "status"}, timeout=30)
        except CloneEngineError as e:
            return {"installed": True, "error": str(e), "hint": e.hint}
        return {"installed": True, **{k: v for k, v in resp.items() if k != "ok"}}

    async def speakers(self) -> Dict[str, Any]:
        """可选的 base speaker 列表（预置 + 总数）。

        **会加载模型**（要读 `n_speakers`），所以别在高频接口里调。
        """
        if not is_installed():
            return {"installed": False, "hint": install_hint()}
        try:
            resp = await self._rpc({"op": "speakers"}, timeout=SYNTH_TIMEOUT_SEC)
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
        speaker_id: int = 0,
    ) -> bytes:
        """合成克隆音色的音频，返回 **wav 字节**。

        `speaker_id` 是 MeloTTS 的 base speaker 编号（ZH 有 256 个）——
        它决定"转换前的中间音"，最终音色仍由参考音频决定，但**韵律和音高基线**会跟着变。
        """
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

        # 顺手清一次陈旧残留：本环境的删除可能被拦（见 _try_remove），不兜底会涨满磁盘
        sweep_stale_wavs()

        async with self._lock:      # worker 是单线程的，别并发打
            resp = await self._rpc(
                {
                    "op": "synth",
                    "text": text,
                    "ref": ref_path,
                    "lang": lang,
                    "speed": speed,
                    "speaker_id": speaker_id,
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
            _try_remove(wav_path)

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
