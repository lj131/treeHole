"""lifespan 的磁盘清理任务：完成回调不能炸。

**回归测试**：回调里直接 `task.exception()` 在任务**被取消**时会抛
`CancelledError`（asyncio 语义），而 done_callback 里没人接住 →
进程退出时吐一大坨 traceback。

触发场景很常见：启动失败（端口被占）时 lifespan 被取消 → cleanup 任务被取消。
2026-10-15 实测到，已修（先判 `cancelled()`）。
"""
import asyncio

import pytest

from api import api


def test_callback_survives_cancelled_task():
    """**核心**：被取消的任务走回调不能抛"""

    async def _forever():
        await asyncio.sleep(3600)

    async def _run():
        task = asyncio.create_task(_forever())
        await asyncio.sleep(0)      # 让它跑起来
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # 修复前这里会抛 CancelledError
        api._log_cleanup_done(task)

    asyncio.run(_run())


def test_callback_handles_failed_task():
    """失败的任务：记 warning，不抛"""

    async def _boom():
        raise RuntimeError("清理炸了")

    async def _run():
        task = asyncio.create_task(_boom())
        with pytest.raises(RuntimeError):
            await task
        api._log_cleanup_done(task)   # 不能抛

    asyncio.run(_run())


def test_callback_handles_success():
    async def _ok():
        return None

    async def _run():
        task = asyncio.create_task(_ok())
        await task
        api._log_cleanup_done(task)

    asyncio.run(_run())
