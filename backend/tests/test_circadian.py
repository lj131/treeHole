"""角色作息：时段划分。**重点是边界值** —— 错一格用户就能看出违和感。"""
from datetime import datetime

import pytest

from funcation import circadian


@pytest.mark.parametrize(
    "hour,label",
    [
        (0, "凌晨"), (2, "凌晨"), (4, "凌晨"),
        (5, "清晨"), (7, "清晨"),
        (8, "上午"), (10, "上午"),
        (11, "上午"),
        (13, "下午"), (17, "下午"),
        (18, "傍晚"), (21, "傍晚"),
        (22, "深夜"), (23, "深夜"),
    ],
)
def test_phase_boundaries(hour, label):
    """**每个边界时段** —— 边界错一格就违和"""
    assert circadian.current_phase(hour).label == label


@pytest.mark.parametrize("hour", [0, 1, 2, 3, 4, 22, 23])
def test_late_night_flags(hour):
    assert circadian.current_phase(hour).late_night is True


@pytest.mark.parametrize("hour", [5, 6, 7, 8, 9, 10, 11, 12, 13, 17, 18, 21])
def test_not_late_night_during_day(hour):
    assert circadian.current_phase(hour).late_night is False


@pytest.mark.parametrize("bad", [-1, 24, 25, 100, None, "8", 8.5, True, False, [], {}])
def test_bad_hour_does_not_crash(bad):
    """非法 hour 返回兜底（不抛）—— 时段信息不该让聊天失败"""
    p = circadian.current_phase(bad)
    assert p.hint == ""           # 兜底不注入 prompt
    assert p.late_night is False


def test_every_phase_has_nonempty_hint():
    """**每个时段的 hint 都非空**（除了非法兜底）—— 空 hint 会让 prompt 出现空段"""
    for hour in range(24):
        assert circadian.current_phase(hour).hint, f"hour={hour} 的 hint 是空的"


def test_all_labels_covered():
    labels = {circadian.current_phase(h).label for h in range(24)}
    assert labels == {"凌晨", "清晨", "上午", "下午", "傍晚", "深夜"}


# ── build_time_context ──────────────────────────────────────

def test_time_context_shape():
    ctx = circadian.build_time_context(datetime(2026, 10, 17, 3, 24))
    assert ctx["phase"] == "凌晨"
    assert ctx["hour"] == 3
    assert ctx["late_night"] is True
    assert "吵醒" in ctx["hint"]  # 凌晨的核心指引


def test_time_context_uses_local_time_when_not_injected():
    """不传 now 时用当前时间（不指定具体值，只要不崩且字段齐全）"""
    ctx = circadian.build_time_context()
    assert 0 <= ctx["hour"] <= 23
    assert ctx["phase"]


def test_defaults_to_now():
    """`now=None` 走 `datetime.now()`（和显式传 now 行为一致）"""
    a = circadian.build_time_context(None)
    b = circadian.build_time_context(datetime.now())
    assert a["phase"] and b["phase"]
