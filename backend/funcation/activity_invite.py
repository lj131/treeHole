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

## 状态机（2026-10-31 补"过程"）

```
pending ──接受──→ accepted ──到点(settle)──→ done
   │                 │                        │
   └─48h 没人回─→ 过期   └─拒绝──→ declined ──3 天冷却──→ 可再约
```

**为什么要有 `done`**：原来 `accepted` 是终态 —— 约定永远"还没去"，
prompt 每次都说"你们约好了要一起去"，说了几个月。而且 `accepted`
不挡新邀请，下一次邀请会**直接把那条约定覆盖掉**（静默丢约定）。
现在到点后 `settle_due()` 把它转成 `done` 并落一条长期记忆。

**`pending` 过期是必须的**：用户很可能直接关掉页面不回复，
原来那个 pending 会**永久**挡住所有后续邀请。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
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

#: pending 邀请挂多久算过期（用户可能直接关页面不回复）
PENDING_TTL_HOURS = 48

#: 接受后默认多久算"活动已经发生"（LLM 没给 when_hours 时用）
DEFAULT_DELAY_HOURS = 20

#: `when_hours` 的合法区间（超出视为无效，回退默认值）
MAX_DELAY_HOURS = 72

#: 活动刚结束多久内不再约（刚一起出去玩过，别马上又约）
RECENT_ACTIVITY_COOLDOWN_DAYS = 1

STATUS_PENDING = "pending"
STATUS_ACCEPTED = "accepted"
STATUS_DONE = "done"
STATUS_DECLINED = "declined"


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

    record = _record_of(memory_data)
    status = record.get("status")

    # 1) 不重复：已有 pending 邀请且没过期
    if status == STATUS_PENDING and not _pending_expired(record, now):
        return InviteDecision(invite=False, reason="已经有一个邀请在等你回复")

    # 1b) 已经约好了还没到日子 —— 别又约一次（会覆盖掉那条约定）
    #     到点后放行：此时 settle_due() 已在同一轮对话开头把它转成 done，
    #     如果没转成（结算失败），下次聊天还会再试，不会永久卡住。
    if status == STATUS_ACCEPTED:
        scheduled = _scheduled_at(record)
        if scheduled is None or now < scheduled:
            return InviteDecision(invite=False, reason="你们还有个约定没去")

    # 1c) 刚一起出去玩过，缓一天
    if status == STATUS_DONE:
        done_at = _parse(record.get("done_at"))
        if done_at is not None:
            days = (now - done_at).total_seconds() / 86400
            if days < RECENT_ACTIVITY_COOLDOWN_DAYS:
                return InviteDecision(
                    invite=False,
                    reason=f"刚一起出去过 {days:.1f} 天，别马上又约",
                )

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


def build_answer_record(
    action: str,
    now: Optional[datetime] = None,
    when_hours: Any = None,
) -> Dict[str, Any]:
    """接（接受/拒绝）后要写回记忆的字段。只回本次字段，调用方 merge。

    `when_hours` 是生成邀请时 LLM 给的"多久之后"（小时）。接受时把它换算成
    **绝对时间 `scheduled_at`** 落库 —— 之后判断"到点没有"只依赖这一个字段，
    不再需要 LLM 或自然语言解析。
    """
    now = now or datetime.now()
    action = str(action or "")
    if action not in ("accepted", "declined"):
        return {}

    ts = now.isoformat()
    record: Dict[str, Any] = {"status": action, "answered_at": ts}
    if action == "declined":
        record["declined_at"] = ts
    else:
        hours = _clamp_hours(when_hours)
        record["delay_hours"] = hours
        record["scheduled_at"] = (now + timedelta(hours=hours)).isoformat()
    return record


def settle_due(
    memory_data: Optional[Dict[str, Any]],
    now: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """**闭环最后一步**：约定到点了 → 返回要写回的东西。纯函数，不写盘。

    返回 `{"record": {...}, "memory_text": "..."}`，调用方负责：
    1. merge 进 `activity_invitation` 并 `save_memory`
    2. 把 `memory_text` 落进长期记忆（`add_long_memory`）

    没到点 / 不是 accepted / 没有活动名 → 返回 None（**绝大多数情况**）。
    """
    now = now or datetime.now()
    record = _record_of(memory_data)
    if record.get("status") != STATUS_ACCEPTED:
        return None

    scheduled = _scheduled_at(record)
    if scheduled is None or now < scheduled:
        return None

    activity = str(record.get("activity") or "").strip()
    if not activity:
        return None

    return {
        "record": {"status": STATUS_DONE, "done_at": now.isoformat()},
        "memory_text": f"我们约好一起去{activity}，后来真的去了。那天过得很舒服。",
    }


def activity_prompt(
    memory_data: Optional[Dict[str, Any]],
    now: Optional[datetime] = None,
) -> str:
    """给 prompt 的"约定/回忆"段。返回空串 = 没有可说的。

    - `pending`：**不注入**（用户还没答，不能说"你们约好了"）
    - `accepted` 未到点：按距离远近说"就在今天/明天/X月X日"
    - `accepted` 已过点（还没结算）：如实说"约定的时间已经过了"
    - `done`：变成回忆（"你们前几天一起去了X"）
    - `declined`：不注入（被拒绝的约定提起来只会尴尬）
    """
    now = now or datetime.now()
    record = _record_of(memory_data)
    status = record.get("status")
    activity = str(record.get("activity") or "").strip()

    if status == STATUS_DONE:
        if not activity:
            return ""
        return (
            f"你们前几天一起去了{activity}（已经去过了）。"
            "可以自然地提起那次，但别每句话都提。"
        )

    if status != STATUS_ACCEPTED or not activity:
        return ""

    scheduled = _scheduled_at(record)
    if scheduled is None:
        return f"你们已经约好了要一起去：{activity}。聊天时可以自然地提起这件事。"

    hours = (scheduled - now).total_seconds() / 3600
    if hours <= 0:
        return (
            f"你们约好了要去{activity}，约定的时间已经过了（应该已经去过了）。"
            "可以自然提起，别抱怨对方没提。"
        )
    if hours <= 6:
        return f"你们约好了{activity}，就在今天、很快就要去了。可以表现出一点期待。"
    if scheduled.date() == now.date():
        return f"你们约好了今天去{activity}。可以自然提起，表现出期待。"
    if (scheduled.date() - now.date()).days == 1:
        return f"你们约好了明天去{activity}。可以自然提起。"
    return (
        f"你们约好了要去{activity}（{scheduled.month}月{scheduled.day}日）。"
        "聊天时可以自然提起。"
    )


# ── 内部 ────────────────────────────────────────────────────

def _scheduled_at(record: Dict[str, Any]) -> Optional[datetime]:
    """约定的绝对时间。老数据没有 `scheduled_at` → 用 `answered_at + 默认延迟`。"""
    scheduled = _parse(record.get("scheduled_at"))
    if scheduled is not None:
        return scheduled
    answered = _parse(record.get("answered_at"))
    if answered is None:
        return None
    return answered + timedelta(hours=DEFAULT_DELAY_HOURS)


def _pending_expired(record: Dict[str, Any], now: datetime) -> bool:
    """pending 挂太久 → 当没约过（用户可能直接关了页面）。"""
    created = _parse(record.get("created_at"))
    if created is None:
        return False  # 不知道什么时候约的，保守：仍然挡住（不误判成过期）
    return (now - created).total_seconds() / 3600 >= PENDING_TTL_HOURS


def _clamp_hours(raw: Any) -> int:
    """把 LLM 给的 `when_hours` 收敛到合法区间。非法 → 默认值。"""
    if isinstance(raw, bool):
        return DEFAULT_DELAY_HOURS
    try:
        hours = int(float(raw))
    except (TypeError, ValueError):
        return DEFAULT_DELAY_HOURS
    if hours < 1 or hours > MAX_DELAY_HOURS:
        return DEFAULT_DELAY_HOURS
    return hours


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


def clean_invitation_payload(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """清洗 LLM 产出的邀请内容。不合格返回 None（不抛）。

    只保留 `activity` / `message` / `when_hours` 三个字段，其余一律丢弃 ——
    LLM 可能返回一堆额外字段，不该原样存进用户数据。

    `when_hours` 是"多久之后去"（小时），接受时换算成绝对时间；
    缺失或非法就不带这个键（`build_answer_record` 会回退默认延迟）。
    """
    if not isinstance(raw, dict):
        return None
    activity = str(raw.get("activity") or "").strip()
    message = str(raw.get("message") or "").strip()
    if not activity or not message:
        return None
    if len(activity) > MAX_ACTIVITY_LEN or len(message) > MAX_MESSAGE_LEN:
        return None
    payload: Dict[str, Any] = {"activity": activity, "message": message}
    raw_hours = raw.get("when_hours")
    if not isinstance(raw_hours, bool) and isinstance(raw_hours, (int, float, str)):
        try:
            hours = int(float(raw_hours))
        except (TypeError, ValueError):
            hours = 0
        if 1 <= hours <= MAX_DELAY_HOURS:
            payload["when_hours"] = hours
    return payload
