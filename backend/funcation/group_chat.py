"""多人群聊 —— 选"谁来插嘴"。

## 为什么需要它

现在每轮只有一个角色说话（`mc.get_user_current_character_id` 定的那个）。
E8 要"一群角色"：主角答，其他人**偶尔**插一句。

## 核心设计：主链路不变，插嘴独立追加

改"让一个 LLM 同时输出多个人说话"要把输出解析整个换掉，风险大。所以：
主答完全走原链路（零回归风险），插嘴是**事后追加**的一次小调用。

## 三条约束（都可测）

1. 插嘴者**不能是主角**（自己接自己的话很怪）
2. **25% 概率** —— 插一句是点缀，插三句是噪音
3. 一轮最多 `max_hecklers` 个（默认 1）
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

#: 默认插嘴概率（百分比）。**25%**：别每轮都有人插嘴。
DEFAULT_HECKLE_CHANCE = 25

#: 一轮最多几个插嘴者。1 个就够 —— 群聊的灵动感来自"偶尔一句"。
DEFAULT_MAX_HECKLERS = 1


@dataclass(frozen=True)
class GroupPlan:
    primary: str
    hecklers: List[str] = field(default_factory=list)


def pick_heckler(
    candidates: Optional[Sequence[Any]],
    *,
    primary_id: str,
    seed: str,
) -> Optional[str]:
    """从候选里选一个插嘴者。**不能是主角**，空候选返回 None。"""
    pool = _clean_candidates(candidates, primary_id)
    if not pool:
        return None
    if len(pool) == 1:
        return pool[0]
    index = _hash_seed(f"{seed}|heckle") % len(pool)
    return pool[index]


def should_heckle(seed: str, *, chance: int = DEFAULT_HECKLE_CHANCE) -> bool:
    """这一轮要不要有人插嘴。确定性伪随机（同 seed 同结果）。"""
    try:
        pct = int(chance)
    except (TypeError, ValueError):
        pct = DEFAULT_HECKLE_CHANCE
    if pct <= 0:
        return False
    if pct >= 100:
        return True
    return (_hash_seed(f"{seed}|chance") % 100) < pct


def plan_group(
    candidates: Optional[Sequence[Any]],
    *,
    primary_id: str,
    seed: str,
    max_hecklers: int = DEFAULT_MAX_HECKLERS,
    chance: int = DEFAULT_HECKLE_CHANCE,
) -> GroupPlan:
    """规划这一轮群聊：主角 + 若干插嘴者。"""
    if not should_heckle(seed, chance=chance):
        return GroupPlan(primary=primary_id, hecklers=[])

    try:
        cap = max(0, int(max_hecklers))
    except (TypeError, ValueError):
        cap = DEFAULT_MAX_HECKLERS

    hecklers: List[str] = []
    pool = _clean_candidates(candidates, primary_id)
    while pool and len(hecklers) < cap:
        picked = pick_heckler(pool, primary_id=primary_id, seed=f"{seed}|{len(hecklers)}")
        if picked is None or picked in hecklers:
            break
        hecklers.append(picked)
        pool = [c for c in pool if c != picked]

    return GroupPlan(primary=primary_id, hecklers=hecklers)


# ============================================================
# 加权调度（批次 2，2026-11-16）
# ============================================================
#
# 旧的 `plan_group` 是均匀随机（hash % len），不看任何上下文。
# 这里新增一个**并存的纯函数**：给定同样的信号，选出"该说话的人"。
# 旧函数一行不动 —— 既有调用和测试零回归；新入口由 api 层显式接入。
#
# 权重信号（都来自已存在的数据，见 docs/.../2026-11-16-group-speaking-rights.md）：
#   affinity 关系强度 0~100（主角视角）→ 关系越好越爱接话
#   relevant 本轮 RAG 命中了谁的集合   → 聊到谁谁接话（最强信号）
#   extrovert 性格外向                 → 外向的人更爱插嘴
#   recent 最近插过嘴的人               → 大幅降权（**降权不禁止**，保留自然感）
#   sleeping 正在睡的                   → 硬门，直接排除

#: 各信号的权重。集中在这里，调参一眼可见、可测。
W_RELEVANT = 3.0        # 内容相关（最强：聊到谁谁接话）
W_AFFINITY_MAX = 2.0    # 关系强度满值（favorability=100）
W_EXTROVERT = 0.5       # 性格外向
F_RECENT = 0.15         # 最近插过 → 乘这个系数（不是 0：禁止会显得机械）

#: 确定性抽签的分母（2^32，和 FNV-1a 的 32 位对齐）
_DRAW_MOD = 0x100000000


def weights_for(
    candidates: Sequence[str],
    *,
    affinity: Optional[Dict[str, Any]] = None,
    relevant: Optional[Any] = None,
    extrovert: Optional[Any] = None,
    recent: Optional[Sequence[str]] = None,
    sleeping: Optional[Sequence[str]] = None,
) -> Dict[str, float]:
    """给每个候选算权重。纯函数，无 IO，结果可复现。

    `sleeping` 里的候选权重直接是 0（硬门）。`relevant` / `extrovert` 支持
    dict 或任何 `x in container` 的容器（set/list/dict 都行）。
    """
    aff = affinity or {}
    rel = relevant if relevant is not None else ()
    ext = extrovert if extrovert is not None else ()
    slept = set(sleeping or ())
    recent_set = set(recent or ())

    out: Dict[str, float] = {}
    for cid in candidates:
        if cid in slept:
            out[cid] = 0.0
            continue
        w = 1.0
        if cid in rel:
            w += W_RELEVANT
        try:
            fav = float(aff.get(cid, 0) or 0)
        except (TypeError, ValueError):
            fav = 0.0
        w += max(0.0, min(100.0, fav)) / 100.0 * W_AFFINITY_MAX
        if cid in ext:
            w += W_EXTROVERT
        if cid in recent_set:
            w *= F_RECENT
        out[cid] = w
    return out


def _weighted_pick(weights: Dict[str, float], seed: str) -> Optional[str]:
    """加权轮盘：确定性伪随机落在权重累积区间里。全 0 权重 → None。"""
    total = sum(max(0.0, w) for w in weights.values())
    if total <= 0:
        return None
    draw = (_hash_seed(f"{seed}|draw") % _DRAW_MOD) / _DRAW_MOD * total
    acc = 0.0
    # 排序保证遍历顺序稳定（dict 插入顺序依赖调用方，不能让它影响结果）
    for cid in sorted(weights):
        acc += max(0.0, weights[cid])
        if draw < acc:
            return cid
    return sorted(weights)[-1]  # 浮点边界兜底


def plan_group_with_signals(
    candidates: Optional[Sequence[Any]],
    *,
    primary_id: str,
    seed: str,
    max_hecklers: int = DEFAULT_MAX_HECKLERS,
    chance: int = DEFAULT_HECKLE_CHANCE,
    affinity: Optional[Dict[str, Any]] = None,
    relevant: Optional[Any] = None,
    extrovert: Optional[Any] = None,
    recent: Optional[Sequence[str]] = None,
    sleeping: Optional[Sequence[str]] = None,
) -> GroupPlan:
    """加权版群聊规划。**仍是纯函数**（零 IO、同输入同输出）。

    和旧 `plan_group` 的区别只在"选谁"：旧的均匀随机，这里按信号加权。
    概率门、主角排除、上限、同轮不重复 —— 全部沿用同样的语义。
    """
    if not should_heckle(seed, chance=chance):
        return GroupPlan(primary=primary_id, hecklers=[])

    try:
        cap = max(0, int(max_hecklers))
    except (TypeError, ValueError):
        cap = DEFAULT_MAX_HECKLERS

    pool = _clean_candidates(candidates, primary_id)
    if not pool or cap == 0:
        return GroupPlan(primary=primary_id, hecklers=[])

    weights = weights_for(
        pool, affinity=affinity, relevant=relevant, extrovert=extrovert,
        recent=recent, sleeping=sleeping,
    )
    # sleeping 全排除 → 总权重 0 → 不插嘴
    if sum(weights.values()) <= 0:
        return GroupPlan(primary=primary_id, hecklers=[])

    hecklers: List[str] = []
    for i in range(cap):
        # 每选一个就把它从候选里移除（同轮不重复）
        live = {cid: w for cid, w in weights.items() if cid not in hecklers}
        if not live or sum(live.values()) <= 0:
            break
        picked = _weighted_pick(live, seed=f"{seed}|{i}")
        if picked is None or picked in hecklers:
            break
        hecklers.append(picked)

    return GroupPlan(primary=primary_id, hecklers=hecklers)


# ── 内部 ────────────────────────────────────────────────────

def _clean_candidates(candidates: Optional[Sequence[Any]], primary_id: str) -> List[str]:
    """去重、去空、**去掉主角**。非字符串条目会被丢掉（不抛）。"""
    if not candidates:
        return []
    out: List[str] = []
    for c in candidates:
        if not isinstance(c, str):
            continue
        cid = c.strip()
        if not cid or cid == primary_id or cid in out:
            continue
        out.append(cid)
    return out


def _hash_seed(seed: str) -> int:
    """FNV-1a（和 E6 `tension.py` / E7 `incoming_call.py` 同一套）。

    不用内置 `hash`（受 `PYTHONHASHSEED` 影响）、不用 `random`
    （不可测且污染全局状态）。
    """
    h = 2166136261
    for ch in seed:
        h ^= ord(ch)
        h = (h * 16777619) & 0xFFFFFFFF
    return h
