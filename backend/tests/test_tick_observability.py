"""tick 可观测性（2026-10-23）—— `/health` 的 `tick` 段。

**为什么需要它**：`RUN_BACKGROUND_TICK=0` 时调度器**静默不启动**，
只有一行 INFO 日志。我曾因此三天没发现本地 tick 从没跑过，
而世界演化/梦境/NPC 互动全挂在它上面 —— 看起来"做完了"，实际一次没执行。

和 RAG 隔离事件一个道理：**没有可观测点 = 没有**。
"""
import pytest

from funcation import world_tick_scheduler as wts


@pytest.fixture(autouse=True)
def _reset_status():
    """每个用例从干净的初始状态开始（模块级 dict，必须手动重置）"""
    saved = dict(wts._tick_status)
    wts._tick_status.clear()
    wts._tick_status.update({
        "enabled": False,
        "started": False,
        "started_at": None,
        "last_loop_at": None,
        "last_ticked_users": 0,
        "last_active_users": 0,
        "loops_total": 0,
        "last_error": None,
    })
    yield
    wts._tick_status.clear()
    wts._tick_status.update(saved)


# ── 三种状态必须能区分 ──────────────────────────────────────

def test_disabled_state_is_visible():
    """**最关键**：禁用了必须能一眼看出来（我就是因为这个信号缺失糊了三天）"""
    wts._tick_status["enabled"] = False
    snap = wts.tick_status()
    assert snap["enabled"] is False
    assert "已禁用" in snap["summary"]
    assert "RUN_BACKGROUND_TICK=0" in snap["summary"]


def test_enabled_but_not_started():
    """启用了但还没跑（刚启动 60s 内）—— 和"禁用"是不同状态"""
    wts._tick_status["enabled"] = True
    snap = wts.tick_status()
    assert snap["enabled"] is True
    assert snap["started"] is False
    assert "还没启动" in snap["summary"]


def test_running_state():
    wts._mark_tick_loop(loops_total=3, ticked=1, active=9)
    snap = wts.tick_status()
    assert snap["started"] is True
    assert snap["loops_total"] == 3
    assert snap["last_ticked_users"] == 1
    assert snap["last_active_users"] == 9
    assert snap["last_loop_at"]
    assert "运行中" in snap["summary"]
    assert "3 轮" in snap["summary"]


def test_error_state_is_visible():
    """**主循环异常也要落状态** —— 否则 /health 看着正常，其实每轮都在炸"""
    wts._mark_tick_loop(loops_total=5, ticked=0, active=0, error="boom")
    snap = wts.tick_status()
    assert snap["last_error"] == "boom"
    assert "异常" in snap["summary"]


# ── 启动函数的落状态 ────────────────────────────────────────

def test_start_marks_disabled_when_env_zero(monkeypatch):
    """RUN_BACKGROUND_TICK=0 → 落 enabled=False（不只是打日志）"""
    monkeypatch.setenv("RUN_BACKGROUND_TICK", "0")
    assert wts.start_world_tick_scheduler() is None
    assert wts.tick_status()["enabled"] is False


def test_start_marks_enabled():
    """正常启动 → enabled=True + started_at 有值。

    ⚠️ `start_world_tick_scheduler` 内部用 `asyncio.create_task`，
    **必须有运行中的事件循环**，所以这个用例是 async 的
    （同步调会 RuntimeError: no running event loop）。
    """
    import asyncio
    import os

    async def _run():
        os.environ["RUN_BACKGROUND_TICK"] = "1"
        task = wts.start_world_tick_scheduler()
        try:
            assert task is not None
            snap = wts.tick_status()
            assert snap["enabled"] is True
            assert snap["started_at"]
        finally:
            # 清理：停掉调度器 + 复位状态（否则污染同会话其他用例）
            await wts.stop_world_tick_scheduler()
            wts._scheduler_task = None
            wts._stop_event = None
            wts._tick_status.update({"enabled": False, "started_at": None})

    asyncio.run(_run())


# ── 快照隔离 ────────────────────────────────────────────────

def test_snapshot_is_a_copy():
    """返回副本 —— 调用方改不到内部状态"""
    wts._mark_tick_loop(1, 1, 1)
    snap = wts.tick_status()
    snap["loops_total"] = 999
    assert wts.tick_status()["loops_total"] == 1


# ── /health 端点真的带 tick 段 ──────────────────────────────

def test_health_endpoint_includes_tick():
    from fastapi.testclient import TestClient

    from api import api as api_mod

    client = TestClient(api_mod.app)
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "rag" in body            # 原有段还在
    assert "tick" in body           # 新段
    assert "enabled" in body["tick"]
    assert "summary" in body["tick"]
