"""utils 单测 —— get_time_diff_minutes / retry_sync / retry_async。"""
import asyncio

from funcation import utils


# ---------- get_time_diff_minutes ----------

def test_time_diff_empty_returns_zero():
    assert utils.get_time_diff_minutes(None) == 0
    assert utils.get_time_diff_minutes("") == 0


def test_time_diff_past_is_positive():
    from datetime import datetime, timedelta
    past = (datetime.now() - timedelta(hours=2)).isoformat()
    diff = utils.get_time_diff_minutes(past)
    # 约 120 分钟，允许小误差
    assert 115 <= diff <= 125


# ---------- retry_sync ----------

def test_retry_sync_success_first_try():
    calls = {"n": 0}

    def op():
        calls["n"] += 1
        return "ok"

    assert utils.retry_sync(op, max_retries=3, base_delay=0) == "ok"
    assert calls["n"] == 1


def test_retry_sync_retries_then_succeeds():
    state = {"n": 0}

    def op():
        state["n"] += 1
        if state["n"] < 3:
            raise ConnectionError("transient")
        return "recovered"

    assert utils.retry_sync(op, max_retries=3, base_delay=0) == "recovered"
    assert state["n"] == 3


def test_retry_sync_non_retryable_raises_immediately():
    calls = {"n": 0}

    def op():
        calls["n"] += 1
        raise ValueError("boom")   # 非可重试

    try:
        utils.retry_sync(op, max_retries=3, base_delay=0)
        assert False, "应抛 ValueError"
    except ValueError:
        pass
    assert calls["n"] == 1   # 不重试


def test_retry_sync_exhausts_retries():
    def op():
        raise ConnectionError("always fails")

    try:
        utils.retry_sync(op, max_retries=2, base_delay=0)
        assert False, "应抛 ConnectionError"
    except ConnectionError:
        pass


# ---------- retry_async（用 asyncio.run 跑，base_delay=0 避免真 sleep）----------

def test_retry_async_success():
    async def op():
        return 42

    assert asyncio.run(utils.retry_async(op, max_retries=3, base_delay=0)) == 42


def test_retry_async_retries_then_succeeds():
    state = {"n": 0}

    async def op():
        state["n"] += 1
        if state["n"] < 2:
            raise ConnectionError("transient")
        return "ok"

    assert asyncio.run(utils.retry_async(op, max_retries=3, base_delay=0)) == "ok"
    assert state["n"] == 2


def test_retry_async_non_retryable_raises():
    async def op():
        raise TypeError("bad")

    try:
        asyncio.run(utils.retry_async(op, max_retries=3, base_delay=0))
        assert False, "应抛 TypeError"
    except TypeError:
        pass
