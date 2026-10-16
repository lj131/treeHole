"""世界日报 —— 把散落各处的世界/记忆数据聚合成一条时间线。

## 为什么需要它

`world_tick_scheduler` 每 30 分钟演化世界、NPC 关系在变、剧情在推进、梦境在生成，
但用户只看到**零散几条主动消息**，根本不知道世界一直在动。
D2（梦境）/ D3（挂件）/ D4（群聊旁观）是三个"点"，日报是把它们串成"面"的那个东西。

## 设计原则

- **纯聚合，零 LLM 调用** —— 数据全都在，只是散着。不拖慢任何东西，不产生新成本。
- **无 IO、无 FastAPI 依赖**（本模块只做数据变换，读盘在调用方）→ 方便单测。
- **一条坏数据不能毁掉整份日报** —— 解析失败就跳过，记 debug 日志。

## ⚠️ 三种时间格式混杂（这是本模块最容易出错的地方）

| 来源 | 格式 | 例子 |
|---|---|---|
| NPC 互动 / 八卦 / 世界影响 / 记忆事件 | 空格分隔 | `"2026-06-05 17:13"` |
| 世界事件 / 剧情 / 梦境 / 里程碑 | 纯日期 | `"2026-06-17"` |
| 主动消息 | ISO 带微秒 | `"2026-10-15T19:43:55.611966"` |

统一走 `parse_digest_time()`，**新增数据源时先确认格式**。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence

logger = logging.getLogger(__name__)

#: 支持的 kind（前端按这个映射图标/配色）
KIND_WORLD_EVENT = "world_event"
KIND_NPC_INTERACTION = "npc_interaction"
KIND_GOSSIP = "gossip"
KIND_WORLD_IMPACT = "world_impact"
KIND_STORY = "story"
KIND_DREAM = "dream"
KIND_PROACTIVE = "proactive"
KIND_MILESTONE = "milestone"
KIND_MEMORY_EVENT = "memory_event"

#: 日报窗口上限（防止有人传 days=99999 把整个历史拉出来）
MAX_DAYS = 30
#: 默认窗口。**取 7 天而不是 3 天** —— 陪伴类用户可能几天才来一次，
#: 3 天窗口经常只有 1-2 条，一进来就看到"世界很安静"是很差的体验。
DEFAULT_DAYS = 7


def parse_digest_time(raw: Any) -> Optional[datetime]:
    """把三种格式统一解析成 `datetime`；解析不了返回 `None`。

    能吃下：
    - `"2026-06-05 17:13"`（空格分隔）
    - `"2026-06-17"`（纯日期 → 补 00:00:00）
    - `"2026-10-15T19:43:55.611966"`（ISO 带微秒）

    **绝不抛异常** —— 一条坏数据不该让整个日报 500。
    """
    if not raw or not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None

    # 空格分隔 → ISO 的 T 分隔（fromisoformat 在 3.11 前不认空格）
    candidate = text.replace(" ", "T", 1)

    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        pass

    # 兜底：逐格式试（覆盖更老的 Python 或非标准写法）
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M",
                "%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue

    logger.debug("[digest] 无法解析时间：%r（已跳过该条）", raw)
    return None


def normalize_days(days: Any) -> int:
    """把 `days` 归一化到 `[1, MAX_DAYS]`；`None`/非法值 → `DEFAULT_DAYS`。

    ⚠️ **不能写 `days or DEFAULT_DAYS`** —— `0` 是有效整数但 falsy，
    会被当成"没传"而变成默认 3，于是"传 0 想只看今天"的用户拿到三天数据。
    用户明确传了值就该 clamp，而不是替换成默认值。
    """
    if days is None:
        return DEFAULT_DAYS
    try:
        value = int(days)
    except (TypeError, ValueError):
        return DEFAULT_DAYS
    return max(1, min(value, MAX_DAYS))


def _entry(
    at: Optional[datetime],
    kind: str,
    title: str,
    detail: str = "",
    actors: Optional[Sequence[str]] = None,
    character_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """构造一条时间线条目。`at` 为 None 时返回 None（调用方过滤掉）。

    `date` 字段由后端算好，前端直接拿来分组 —— 免得前端再解析一遍时间
    （那会让"分组错位"这种 bug 出现在两个地方）。
    """
    if at is None:
        return None
    item: Dict[str, Any] = {
        "at": at.isoformat(timespec="minutes"),
        "date": at.date().isoformat(),
        "kind": kind,
        "title": title,
        "detail": detail or "",
        "actors": list(actors or []),
    }
    if character_id:
        item["character_id"] = character_id
    return item


def _world_entries(world_state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """世界侧：事件 / NPC 互动 / 八卦 / 世界影响。"""
    out: List[Dict[str, Any]] = []
    ws = world_state.get("world_state") if "world_state" in world_state else world_state
    if not isinstance(ws, dict):
        return out

    # 世界事件（当前 + 已结束）。只取 created_at —— finished_at 是同一件事的另一个时点，
    # 放两条会让时间线看起来重复。
    for key, status_label in (("current_events", "进行中"), ("history_events", "已结束")):
        for ev in ws.get(key) or []:
            if not isinstance(ev, dict):
                continue
            name = ev.get("name") or ev.get("title") or ev.get("description") or "世界事件"
            item = _entry(
                parse_digest_time(ev.get("created_at")),
                KIND_WORLD_EVENT,
                f"{name}（{status_label}）",
                str(ev.get("description") or "")[:200],
            )
            if item:
                out.append(item)

    registry = ws.get("npc_registry") or {}
    if not isinstance(registry, dict):
        return out

    for it in registry.get("recent_interactions") or []:
        if not isinstance(it, dict):
            continue
        item = _entry(
            parse_digest_time(it.get("time")),
            KIND_NPC_INTERACTION,
            "NPC 之间发生了一场互动",
            str(it.get("summary") or "")[:200],
        )
        if item:
            out.append(item)

    for g in registry.get("gossip") or []:
        if not isinstance(g, dict):
            continue
        src, tgt = g.get("source") or "", g.get("target") or ""
        item = _entry(
            parse_digest_time(g.get("time")),
            KIND_GOSSIP,
            f"八卦传播：{src} → {tgt}".strip(" →"),
            str(g.get("content") or "")[:200],
            actors=[a for a in (src, tgt) if a],
        )
        if item:
            out.append(item)

    for imp in registry.get("world_impacts") or []:
        if not isinstance(imp, dict):
            continue
        item = _entry(
            parse_digest_time(imp.get("time")),
            KIND_WORLD_IMPACT,
            "世界受到影响",
            str(imp.get("impact") or "")[:200],
        )
        if item:
            out.append(item)

    return out


def _memory_entries(
    memories: Dict[str, Dict[str, Any]],
    rag_data: Optional[Dict[str, Dict[str, Any]]] = None,
    names: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """记忆侧：梦境 / 剧情 / 主动消息 / 里程碑 / 记忆事件。按角色遍历。

    `names` 是 `{character_id: 显示名}`（调用方从 `mc.get_all_characters()` 取）。
    **没有它时间线里会显示 `linwan` 而不是「林婉」** —— 记忆文件里不存角色名
    （`character_state` 只有 mood/energy/current_event）。
    """
    out: List[Dict[str, Any]] = []
    rag_data = rag_data or {}
    names = names or {}

    for char_id, mem in (memories or {}).items():
        if not isinstance(mem, dict):
            continue
        # 三级兜底：调用方给的名字 → 记忆里的（老数据可能有）→ id
        label = names.get(char_id) or ""
        if not label:
            state = mem.get("character_state")
            if isinstance(state, dict):
                label = str(state.get("name") or "")
        label = label or char_id

        # 梦境（历史 + 待投递）
        dreams = list(mem.get("dreams") or [])
        pending = mem.get("dream")
        if isinstance(pending, dict) and pending:
            dreams = dreams + [pending]
        for d in dreams:
            if not isinstance(d, dict):
                continue
            item = _entry(
                parse_digest_time(d.get("date")),
                KIND_DREAM,
                f"{label} 做了一场梦",
                str(d.get("text") or "")[:300],
                character_id=char_id,
            )
            if item:
                out.append(item)

        # 剧情（进行中 + 已归档）
        for st in list(mem.get("stories") or []) + list(mem.get("story_history") or []):
            if not isinstance(st, dict):
                continue
            title = str(st.get("title") or "剧情")
            stage = st.get("stage")
            max_stage = st.get("max_stage")
            progress = f"（第 {stage}/{max_stage} 阶段）" if stage is not None else ""
            # 推进时间优先用 last_advance_date（更近），否则 started_at
            at = parse_digest_time(st.get("last_advance_date")) or parse_digest_time(
                st.get("started_at")
            )
            item = _entry(
                at,
                KIND_STORY,
                f"{label} 的剧情推进：{title}{progress}",
                str(st.get("description") or "")[:200],
                character_id=char_id,
            )
            if item:
                out.append(item)

        # 主动消息（只取最近一次 —— 历史没存）
        pro = mem.get("proactive")
        if isinstance(pro, dict) and pro.get("last_message"):
            item = _entry(
                parse_digest_time(pro.get("last_time")),
                KIND_PROACTIVE,
                f"{label} 主动找你说话",
                str(pro.get("last_message"))[:300],
                character_id=char_id,
            )
            if item:
                out.append(item)

        # 关系里程碑
        sa = mem.get("self_awareness")
        if isinstance(sa, dict):
            for ms in sa.get("milestones") or []:
                if not isinstance(ms, dict):
                    continue
                item = _entry(
                    parse_digest_time(ms.get("date")),
                    KIND_MILESTONE,
                    f"你和{label}的关系：{ms.get('from', '?')} → {ms.get('to', '?')}",
                    "",
                    character_id=char_id,
                )
                if item:
                    out.append(item)

        # 记忆事件（在 .rag.json 里）
        rag = rag_data.get(char_id)
        if isinstance(rag, dict):
            for ev in rag.get("events") or []:
                if not isinstance(ev, dict):
                    continue
                item = _entry(
                    parse_digest_time(ev.get("time")),
                    KIND_MEMORY_EVENT,
                    f"{label} 记下了一件事",
                    str(ev.get("event") or "")[:200],
                    character_id=char_id,
                )
                if item:
                    out.append(item)

    return out


def build_entries(
    *,
    world_state: Optional[Dict[str, Any]] = None,
    memories: Optional[Dict[str, Dict[str, Any]]] = None,
    rag_data: Optional[Dict[str, Dict[str, Any]]] = None,
    names: Optional[Dict[str, str]] = None,
    now: Optional[datetime] = None,
    days: int = DEFAULT_DAYS,
) -> List[Dict[str, Any]]:
    """聚合成一条时间线，**最新的在前**。

    `now` 不传则用当前时间（测试里传固定值，避免时间依赖导致 flaky）。
    `days` 会被 clamp 到 `[1, MAX_DAYS]`。

    **窗口按"天"算，不按秒**：`days=3` = 今天 + 前两天（共 3 个自然日）。
    为什么不能按秒比：数据里有**纯日期粒度**的字段（世界事件 / 梦境 / 里程碑存的是
    `"2026-10-13"`，解析出来是当天 00:00）。若 cutoff 精确到 `now - 3天 = 10-13 12:00`，
    那么"10-13 那天发生的事"会因为早 12 小时被误杀 —— 用户视角里 10-13 明明在
    "最近三天"内。
    """
    now = now or datetime.now()
    days = normalize_days(days)
    # 含今天在内往前数 days 天 → 最早那天
    cutoff_date = (now - timedelta(days=days - 1)).date()

    entries: List[Dict[str, Any]] = []
    entries.extend(_world_entries(world_state or {}))
    entries.extend(_memory_entries(memories or {}, rag_data, names))

    kept: List[Dict[str, Any]] = []
    for e in entries:
        raw_date = e.get("date")
        day = parse_digest_time(raw_date)
        # 过滤只按日期；解析不出日期的不该走到这里（_entry 已保证），
        # 但真出现了也保留 —— 宁可多显示一条，不要静默吞掉。
        if day is not None and day.date() < cutoff_date:
            continue
        kept.append(e)

    # 倒序：最新的在前。同日同分钟的条目保持稳定顺序（Python sort 是稳定的）
    kept.sort(key=lambda e: e.get("at") or "", reverse=True)
    return kept


#: 一句话概览的措辞。只统计"值得说"的类别，避免概览变成流水账。
_SUMMARY_LABELS = {
    KIND_WORLD_EVENT: "世界事件",
    KIND_NPC_INTERACTION: "NPC 互动",
    KIND_DREAM: "梦境",
    KIND_STORY: "剧情推进",
    KIND_PROACTIVE: "主动消息",
    KIND_MILESTONE: "关系里程碑",
}


def summarize(entries: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """给前端做"一句话概览"用的计数。"""
    counts: Dict[str, int] = {}
    for e in entries:
        kind = str(e.get("kind") or "")
        counts[kind] = counts.get(kind, 0) + 1

    parts = [
        f"{label} {counts[kind]} 条"
        for kind, label in _SUMMARY_LABELS.items()
        if counts.get(kind)
    ]
    return {
        "counts": counts,
        "total": sum(counts.values()),
        # 例："世界事件 1 条 · NPC 互动 2 条 · 梦境 1 条"
        "text": " · ".join(parts) if parts else "这段时间世界很安静",
    }
