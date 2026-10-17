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
