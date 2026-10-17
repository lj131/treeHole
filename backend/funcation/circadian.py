"""角色作息 —— 让角色知道现在几点。

## 为什么需要它

实测（2026-10-17 查证）：`prompt.py` 只用了 `world_state.time_period`（**世界的**时间，
由 world tick 每天更新一次），角色设定里**没有任何作息字段**。
所以用户凌晨 3 点打开 App，看到的仍然是"傍晚的林婉"在精神饱满地秒回。

## 关键决策：用哪个时间？

用**用户本地时间**（`datetime.now().hour`），不用世界的 `time_period`。
理由：陪伴类产品的体感是"我半夜打开 App，她应该也在半夜"。
世界的 `time_period` 是设定在"夏天的校园"，且一天才 tick 一次，和用户当下无关。

## 边界必须明确

时段是"分档"，边界值错一格会让用户看到明显的违和感（比如夜里 11 点半显示"下午"）。
所有边界都写进单测。

## 语气要克制

**角色设定优先，时段只影响状态与语气。** 凌晨她可以说"有点困"，但不能变成
"我在睡觉别烦我" —— 用户还得得到回复（可用性优先，所以**不做"深夜不回复"**）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Phase:
    label: str          # 给用户/日志看的
    hint: str           # 给 LLM 的行为指引（空串 = 不注入，省 token）
    late_night: bool = False


#: 时段表。**按起始小时升序**，`_phase_for_hour` 靠它查表。
#: 边界（改了必须同步 `test_circadian.py` 的边界用例）：
#:   凌晨 0-4 / 清晨 5-7 / 上午 8-10 / 午前 11-12 /
#:   下午 13-17 / 傍晚 18-21 / 深夜 22-23
_PHASES = [
    (
        0,
        Phase(
            label="凌晨",
            hint=(
                "现在是凌晨，你本来应该在睡觉，是被用户吵醒的。"
                "回复应该更短、带困意（可以有点迷糊或打字慢半拍），但不要因此拒绝回话。"
            ),
            late_night=True,
        ),
    ),
    (
        5,
        Phase(
            label="清晨",
            hint=(
                "现在是清晨，你刚醒来不久，还没完全清醒。"
                "语气可以松一点，不要像白天那样利落。"
            ),
        ),
    ),
    (
        8,
        Phase(
            label="上午",
            hint="现在是上午，你精神不错，可以正常聊天。",
        ),
    ),
    (
        11,
        Phase(
            label="上午",
            hint="现在是上午快结束的时候，你可能在想午饭，别聊得太紧绷。",
        ),
    ),
    (
        13,
        Phase(
            label="下午",
            hint="现在是下午，正常的聊天时间。",
        ),
    ),
    (
        18,
        Phase(
            label="傍晚",
            hint="现在是傍晚，一天里比较放松的时候，可以自然地和用户聊。",
        ),
    ),
    (
        22,
        Phase(
            label="深夜",
            hint=(
                "现在是深夜，你该睡了，有点困。"
                "回复短一些、柔和一些，不要表现得很精神。"
            ),
            late_night=True,
        ),
    ),
]

#: 小时数不合法时的兜底（不崩，也不乱说话）
_FALLBACK = Phase(label="未知时段", hint="")


def current_phase(hour: Any) -> Phase:
    """按小时（0-23）返回时段。非法输入返回空提示的兜底（**不抛**）。"""
    if isinstance(hour, bool) or not isinstance(hour, int):
        return _FALLBACK
    if hour < 0 or hour > 23:
        return _FALLBACK

    chosen = _phases()[0]
    for start, phase in _phases():
        if hour >= start:
            chosen = phase
        else:
            break
    return chosen


def _phases():
    """建一次就够（模块级缓存，避免每次调用重建）。"""
    global _PHASE_CACHE
    if _PHASE_CACHE is None:
        _PHASE_CACHE = [(start, phase) for start, phase in _PHASES]
    return _PHASE_CACHE


_PHASE_CACHE = None


def build_time_context(now: Optional[datetime] = None) -> Dict[str, Any]:
    """生成给 prompt 用的时间上下文。

    `now` 可注入（测试固定时间，避免 flaky）。返回：
    `{"phase": label, "hour": h, "hint": str, "late_night": bool}`

    ⚠️ `hint` 可能为空串 —— 调用方据此决定**不注入**（平淡时段省 token）。
    """
    now = now or datetime.now()
    hour = now.hour
    phase = current_phase(hour)
    return {
        "phase": phase.label,
        "hour": hour,
        "hint": phase.hint,
        "late_night": phase.late_night,
    }
