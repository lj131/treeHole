"""关系张力与冲突 —— **纯函数模块**（无 IO、无 LLM、无随机模块）。

## 为什么需要它

现在系统只会往好的方向走：prompt 里**有**负向 delta 示例（争吵 -10 / 背叛 -20），
但**没有任何指令鼓励生成冲突**，LLM 默认倾向"和谐"。
实测 NPC 关系只涨（50 → 51 → 55），互动记录全是友好交流。

**没有冲突就没有故事。** 所有陪伴类产品都"永远温柔" ——
有争吵、有关系危机、有角色跑来找你倾诉，才是"活着"和"哄你开心"的区别。

## 为什么要"代码决定张力"而不是让 LLM 自由发挥

频率不可控：要么天天吵（用户烦、关系崩），要么永远不吵（回到现状）。
所以**代码决定"这次要不要有张力"**（本模块），prompt 只负责"怎么吵得自然"。

## 确定性

`decide_tension` 用**自己算的伪随机**（不用 `random` 模块）：
- 可单测（同输入同输出）
- 不受全局随机状态影响（测试之间不互相污染）
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

#: 张力等级
TENSION_CALM = 0      # 平和：允许小分歧，整体友好
TENSION_FRICTION = 1  # 摩擦：应有一次意见不合 / 小误会
TENSION_CONFLICT = 2  # 冲突：应有一次明显争吵 / 对立

#: 冲突冷却天数。这段时间内一律不出张力 —— 否则用户会被连续吵架淹没。
CONFLICT_COOLDOWN_DAYS = 7

#: 判定"明显负向"的阈值。低于这个绝对值的变化才算冲突。
#: 注意 `-5` 是个**包含**边界（`<= -5` 算，`-4` 不算）。
CONFLICT_DELTA_THRESHOLD = -5

#: 信任低于此值的关系容易出张力
LOW_TRUST = 40

#: 好感明显低于初始值（50）= 已有裂痕
FRICTION_FAVORABILITY = 45

#: 各等级的基准概率（百分比）。乘以状态修正系数后使用。
_BASE_CHANCE = {TENSION_FRICTION: 35, TENSION_CONFLICT: 15}


def _hash_seed(seed: str) -> int:
    """把字符串变成稳定的整数（不用内置 `hash` —— 它受 PYTHONHASHSEED 影响）。"""
    h = 2166136261
    for ch in seed:
        h ^= ord(ch)
        h = (h * 16777619) & 0xFFFFFFFF
    return h


def _roll(seed: str, salt: str, percent: int) -> bool:
    """确定性伪随机：同样 (seed, salt) 永远同样结果。`percent` 为命中概率。"""
    if percent <= 0:
        return False
    if percent >= 100:
        return True
    value = _hash_seed(f"{seed}|{salt}") % 100
    return value < percent


def _days_since(raw: Any, today: str) -> Optional[int]:
    """距某天过了多少天。解析不了返回 None（= 不知道，按"很久以前"处理）。"""
    if not raw or not isinstance(raw, str):
        return None
    try:
        then = datetime.fromisoformat(raw.strip().replace(" ", "T", 1)).date()
    except ValueError:
        return None
    try:
        now = datetime.fromisoformat(today.strip()).date()
    except ValueError:
        return None
    return (now - then).days


def decide_tension(
    relationships: Dict[str, Dict[str, Dict[str, Any]]],
    *,
    seed: str,
    today: str,
    last_conflict_date: str = "",
) -> int:
    """决定本轮 NPC 互动该带多少张力。

    `relationships` 是 world_state 里的 `npc_registry.relationships`
    （有向、可能不对称 —— 本函数只读不写，不做归一化）。

    返回 `TENSION_CALM` / `TENSION_FRICTION` / `TENSION_CONFLICT`。

    **冷却优先**：距上次冲突不足 `CONFLICT_COOLDOWN_DAYS` 天 → 一律平和。
    """
    # 冷却：刚吵过就别再吵
    # 冷却：刚吵过就别再吵
    since = _days_since(last_conflict_date, today)
    if since is not None and since < CONFLICT_COOLDOWN_DAYS:
        return TENSION_CALM

    stats = _collect_stats(relationships)
    if stats is None:
        # 没有任何关系数据 → 平和（没什么可吵的）
        return TENSION_CALM

    min_trust, min_fav, avg_fav, pairs = stats

    # 状态修正系数：信任越低、裂痕越深，越容易出张力
    modifier = 1.0
    if min_trust < LOW_TRUST:
        modifier += 0.8
    if min_fav < FRICTION_FAVORABILITY:
        modifier += 0.6
    # 关系越少，世界越"平静"（没什么互动可吵）
    if pairs < 2:
        modifier *= 0.6

    for level in (TENSION_CONFLICT, TENSION_FRICTION):
        chance = int(_BASE_CHANCE[level] * modifier)
        if _roll(seed, f"tension{level}", chance):
            return level

    return TENSION_CALM


def _collect_stats(
    relationships: Dict[str, Dict[str, Dict[str, Any]]],
) -> Optional[tuple]:
    """返回 (最低信任, 最低好感, 平均好感, 关系对数量)；没有数据返回 None。"""
    if not isinstance(relationships, dict) or not relationships:
        return None

    trusts: List[float] = []
    favs: List[float] = []
    seen = set()
    for from_id, targets in relationships.items():
        if not isinstance(targets, dict):
            continue
        for to_id, stats in targets.items():
            if not isinstance(stats, dict) or not to_id:
                continue
            # 无向去重（同一对只算一次），和 E2 的画图逻辑保持一致
            key = tuple(sorted((str(from_id), str(to_id))))
            if key in seen:
                continue
            seen.add(key)
            t = stats.get("trust")
            f = stats.get("favorability")
            if isinstance(t, (int, float)):
                trusts.append(float(t))
            if isinstance(f, (int, float)):
                favs.append(float(f))

    if not favs and not trusts:
        return None
    pairs = max(len(seen), 1)
    return (
        min(trusts) if trusts else 50.0,
        min(favs) if favs else 50.0,
        (sum(favs) / len(favs)) if favs else 50.0,
        pairs,
    )


def detect_conflict(result: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """从 LLM 输出里挑出**明显的负向关系变化**。

    只看 `favorability_delta` / `trust_delta`（`intimacy` 下降不算冲突 ——
    亲密度的降低更可能是"疏远"，不是"吵架"）。

    返回 `[{from, to, severity, reason, favorability_delta, trust_delta}]`，
    按严重度降序。`severity`：1 = 小摩擦，2 = 明显冲突。
    """
    if not result or not isinstance(result, dict):
        return []

    found: List[Dict[str, Any]] = []
    for change in result.get("relationship_changes") or []:
        if not isinstance(change, dict):
            continue
        fav_d = _num(change.get("favorability_delta"))
        trust_d = _num(change.get("trust_delta"))
        worst = min(fav_d, trust_d)
        if worst > CONFLICT_DELTA_THRESHOLD:
            continue

        from_name = str(change.get("from") or "").strip()
        to_name = str(change.get("to") or "").strip()
        if not from_name or not to_name:
            continue

        found.append(
            {
                "from": from_name,
                "to": to_name,
                # 明显冲突（≤ -10）vs 小摩擦
                "severity": 2 if worst <= -10 else 1,
                "reason": str(change.get("reason") or "").strip(),
                "favorability_delta": fav_d,
                "trust_delta": trust_d,
            }
        )

    found.sort(key=lambda c: min(c["favorability_delta"], c["trust_delta"]))
    return found


def conflict_notice_payload(
    conflict: Dict[str, Any],
    *,
    today: str,
) -> Dict[str, Any]:
    """生成写进角色记忆的通知结构（`memory["conflict_notice"]`）。

    只写**一方**（`from`）—— 两边都来倾诉会很吵，而且用户会觉得莫名其妙。
    """
    return {
        "changed": True,
        "with": conflict.get("to", ""),
        "summary": conflict.get("reason") or f"和{conflict.get('to', '对方')}闹得不太愉快",
        "severity": int(conflict.get("severity") or 1),
        "time": today,
    }


def should_notify_conflict(
    conflict: Dict[str, Any],
    *,
    severity_threshold: int = 2,
) -> bool:
    """值不值得专门来找用户说一次。

    **默认只通知"明显冲突"（severity 2）** —— 小摩擦天天有，
    每次都来倾诉会让用户觉得这个角色很烦。
    """
    return int(conflict.get("severity") or 0) >= severity_threshold


def cooldown_ok(last_conflict_date: str, today: str) -> bool:
    """距上次冲突够久了吗（可以和 `decide_tension` 共用同一套天数逻辑）。"""
    since = _days_since(last_conflict_date, today)
    if since is None:
        return True
    return since >= CONFLICT_COOLDOWN_DAYS


def _num(v: Any) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    return 0.0
