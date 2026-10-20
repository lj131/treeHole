"""AI 主动发起活动 —— 决定"现在要不要约你出去"。

## 为什么需要它

proactive 只是一句问候，E7 来电打完就完。**活动邀请是一个闭环**：
她约你 → 你接受/拒绝 → **她记得这个约定**（下次聊天会提起）。
没有最后一步，用户接受后发现她再也不提，比不约更糟。

## 五条约束（都可测）

1. **不重复** —— 已有 pending 邀请时不再约（用户还没答呢）
2. **拒绝冷却 3 天** —— 被拒绝是明确信号
3. **好感度门槛 30** —— 不熟就约太突兀
4. **时段** —— 复用 `circadian`，深夜不约人
5. **概率 25%** —— seed 用**内容 hash**（同 E8 教训：分钟粒度会让
   同一分钟内连发的消息共享判定，要么全约要么全不约）
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

#: 低于此好感度不约（不熟就约太突兀）
MIN_FAVORABILITY = 30

#: 被拒绝后多少天内不再约
DECLINE_COOLDOWN_DAYS = 3

#: 默认邀请概率（百分比）
DEFAULT_CHANCE = 25

#: 邀请生成的最长字数（活动名）+ 一句话的长度上限
MAX_ACTIVITY_LEN = 30
MAX_MESSAGE_LEN = 60


@dataclass(frozen=True)
class InviteDecision:
    invite: bool
    reason: str = ""


def should_invite(
    memory_data: Optional[Dict[str, Any]],
    *,
    now: Optional[datetime] = None,
    seed: str = "",
    min_favorability: int = MIN_FAVORABILITY,
    cooldown_days: int = DECLINE_COOLDOWN_DAYS,
    chance: int = DEFAULT_CHANCE,
) -> InviteDecision:
    """决定现在要不要约用户出去。`seed` 用于确定性伪随机。"""
    now = now or datetime.now()

    # 1) 不重复：已有 pending 邀请
    record = _record_of(memory_data)
    if record.get("status") == "pending":
        return InviteDecision(invite=False, reason="已经有一个邀请在等你回复")

    # 2) 拒绝冷却
    declined_at = _parse(record.get("declined_at"))
    if declined_at is not None:
        days = (now - declined_at).total_seconds() / 86400
        if days < cooldown_days:
            return InviteDecision(
                invite=False, reason=f"被拒绝后 {days:.1f} 天，冷却中（{cooldown_days} 天）"
            )

    # 3) 好感度门槛
    favorability = _favorability_of(memory_data)
    if favorability < min_favorability:
        return InviteDecision(
            invite=False, reason=f"好感度 {favorability} 还不够（< {min_favorability}）"
        )

    # 4) 时段：深夜不约人
    if _is_late_night(now):
        return InviteDecision(invite=False, reason="深夜，不该约人")

    # 5) 概率
    if not _roll(seed or _default_seed(now), chance):
        return InviteDecision(invite=False, reason="这次不约")

    return InviteDecision(invite=True, reason="想约你出去走走")


def build_answer_record(action: str, now: Optional[datetime] = None) -> Dict[str, Any]:
    """接（接受/拒绝）后要写回记忆的字段。只回本次字段，调用方 merge。"""
    now = now or datetime.now()
    action = str(action or "")
    if action not in ("accepted", "declined"):
        return {}

    ts = now.isoformat()
    record: Dict[str, Any] = {"status": action, "answered_at": ts}
    if action == "declined":
        record["declined_at"] = ts
    return record


def pending_activity_prompt(memory_data: Optional[Dict[str, Any]]) -> str:
    """**闭环第 4 步**：给 prompt 的"已接受的约定"。

    返回空串 = 没有约定要提。只有 `status == "accepted"` 才注入 ——
    pending（用户还没答）时不能说"你们约好了"。
    """
    record = _record_of(memory_data)
    if record.get("status") != "accepted":
        return ""
    activity = str(record.get("activity") or "").strip()
    if not activity:
        return ""
    return f"你们已经约好了要一起去：{activity}。聊天时可以自然地提起这件事。"


# ── 内部 ────────────────────────────────────────────────────

def _record_of(memory_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not memory_data or not isinstance(memory_data, dict):
        return {}
    record = memory_data.get("activity_invitation")
    return record if isinstance(record, dict) else {}


def _favorability_of(memory_data: Optional[Dict[str, Any]]) -> int:
    """读好感度。非数字/缺失 → 0（保守：不熟就不约）。"""
    if not memory_data or not isinstance(memory_data, dict):
        return 0
    raw = memory_data.get("favorability", 0)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return 0
    return int(raw)


def _is_late_night(now: datetime) -> bool:
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


def _roll(seed: str, chance: int = DEFAULT_CHANCE) -> bool:
    """FNV-1a 确定性伪随机（同 E6/E7/E8）。"""
    try:
        pct = int(chance)
    except (TypeError, ValueError):
        pct = DEFAULT_CHANCE
    if pct <= 0:
        return False
    if pct >= 100:
        return True
    h = 2166136261
    for ch in seed:
        h ^= ord(ch)
        h = (h * 16777619) & 0xFFFFFFFF
    return (h % 100) < pct


def clean_invitation_payload(raw: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """清洗 LLM 产出的邀请内容。不合格返回 None（不抛）。

    只保留 `activity` / `message` 两个字段，其余一律丢弃 ——
    LLM 可能返回一堆额外字段，不该原样存进用户数据。
    """
    if not isinstance(raw, dict):
        return None
    activity = str(raw.get("activity") or "").strip()
    message = str(raw.get("message") or "").strip()
    if not activity or not message:
        return None
    if len(activity) > MAX_ACTIVITY_LEN or len(message) > MAX_MESSAGE_LEN:
        return None
    return {"activity": activity, "message": message}
