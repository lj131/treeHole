"""主动来电 —— 决定"现在要不要打给你"。

## 为什么需要它

语音通话底层已经全通了（`WS /voice/call` + `voiceCallStore` + `VoiceCallModal`），
但**只有用户主动发起**这一条路。"她主动打过来"是陪伴感最强的一件事，
而它缺的只是"该不该打"的判定。

## 为什么决策是纯函数

频率必须可控，且可单测（不用等真时间、不依赖 LLM）。
和 E6 的 `tension.py` / E5 的 `circadian.py` 同一个模式：
**代码决定"要不要"，UI 负责"怎么响"**。

## 三条硬约束（都有理由）

1. **时段** —— 凌晨 3 点不能响（复用 `circadian` 的 `late_night`）
2. **拒绝冷却** —— 被拒绝后 2 小时内不能再打，否则是骚扰
3. **接听间隔** —— 刚接完又打会很烦
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

#: 被拒绝后多久不再打（分钟）。拒绝是明确信号，要尊重。
DECLINE_COOLDOWN_MINUTES = 120

#: 距上次接听多久才可能再打（分钟）。刚聊完别立刻又打。
ANSWERED_COOLDOWN_MINUTES = 30

#: 24 小时内最多主动打几次（硬上限，任何情况下不超过）。
MAX_CALLS_PER_DAY = 3


@dataclass(frozen=True)
class CallDecision:
    call: bool
    reason: str = ""
    greeting_hint: str = ""


def should_call(
    memory_data: Optional[Dict[str, Any]],
    *,
    now: Optional[datetime] = None,
    seed: str = "",
) -> CallDecision:
    """决定现在要不要给用户打电话。

    `memory_data` 是角色记忆（读 `incoming_call` 记录）。
    `now` 可注入（测试固定时间）。`seed` 用于确定性伪随机。

    返回 `CallDecision(call, reason, greeting_hint)`。
    """
    now = now or datetime.now()
    record = _record_of(memory_data)

    # 1) 时段：深夜不打
    if _is_late_night(now):
        return CallDecision(call=False, reason="深夜，不该打扰")

    # 2) 拒绝冷却
    declined_at = _parse(record.get("declined_at"))
    if declined_at is not None:
        minutes = (now - declined_at).total_seconds() / 60
        if minutes < DECLINE_COOLDOWN_MINUTES:
            return CallDecision(
                call=False,
                reason=f"被拒绝后 {int(minutes)} 分钟，冷却中（{DECLINE_COOLDOWN_MINUTES} 分钟）",
            )

    # 3) 接听间隔
    answered_at = _parse(record.get("answered_at"))
    if answered_at is not None:
        minutes = (now - answered_at).total_seconds() / 60
        if minutes < ANSWERED_COOLDOWN_MINUTES:
            return CallDecision(
                call=False,
                reason=f"刚接听完 {int(minutes)} 分钟，间隔太短",
            )

    # 4) 每日上限
    today = now.strftime("%Y-%m-%d")
    calls_today = record.get("calls_today_date") == today and record.get("calls_today") or 0
    if calls_today >= MAX_CALLS_PER_DAY:
        return CallDecision(call=False, reason=f"今天已经打过 {calls_today} 次了")

    # 5) 概率：不是每次都打（否则"主动"变成"骚扰"）
    if not _roll(seed or _default_seed(now)):
        return CallDecision(call=False, reason="这次不打")

    return CallDecision(
        call=True,
        reason="想听听你的声音",
        greeting_hint="你打给她，她接起来会先笑一下，然后问你怎么这个时候打来了。",
    )


def build_answer_record(action: str, now: Optional[datetime] = None) -> Dict[str, Any]:
    """生成接听/拒绝后要写回记忆的记录。

    只回**本次的字段**，由调用方 merge 进 `memory_data["incoming_call"]`，
    避免"用旧快照整体覆盖"把别的字段冲掉。
    """
    now = now or datetime.now()
    ts = now.isoformat()
    action = str(action or "")
    if action not in ("answered", "declined"):
        # 非法动作不写任何东西（也不抛）
        return {}

    record: Dict[str, Any] = {"last_action": action, "last_action_at": ts}
    if action == "answered":
        record["answered_at"] = ts
    else:
        record["declined_at"] = ts
    return record


def note_call_made(record: Optional[Dict[str, Any]], now: Optional[datetime] = None) -> Dict[str, Any]:
    """记一次"已拨出"（用于每日上限计数）。返回新字段，同样由调用方 merge。"""
    now = now or datetime.now()
    base = dict(record or {})
    today = now.strftime("%Y-%m-%d")
    count = base.get("calls_today") or 0 if base.get("calls_today_date") == today else 0
    return {"calls_today_date": today, "calls_today": count + 1, "last_call_at": now.isoformat()}


# ── 内部 ────────────────────────────────────────────────────

def _record_of(memory_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not memory_data or not isinstance(memory_data, dict):
        return {}
    record = memory_data.get("incoming_call")
    return record if isinstance(record, dict) else {}


def _is_late_night(now: datetime) -> bool:
    """复用 circadian（单一真源，不自己再判一次小时）。"""
    from funcation import circadian

    return circadian.current_phase(now.hour).late_night


def _parse(raw: Any) -> Optional[datetime]:
    if not raw or not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.strip().replace("Z", ""))
    except ValueError:
        return None


def _default_seed(now: datetime) -> str:
    return now.strftime("%Y-%m-%d-%H")


def _roll(seed: str) -> bool:
    """确定性伪随机：同 seed 同结果。

    命中率 **30%** —— "主动"才有意义，天天打就是骚扰。
    用和 E6 `tension.py` 同款的 FNV-1a（不用 `random` 模块）。
    """
    h = 2166136261
    for ch in seed:
        h ^= ord(ch)
        h = (h * 16777619) & 0xFFFFFFFF
    return (h % 100) < 30
