"""数据导出（E11）—— 用户能把自己的数据带走。

## 为什么是白名单而不是"把 dict 倒出去"

导出的虽然是"用户自己的数据"，但 memory / character 字典里可能混着
不该出去的东西：API key、token、内部路径、对其他用户的引用。

所以这里**只取我们明确要的字段**，并且有一条测试专门钉住：
即使源数据里塞了 `api_key`/`token`/`password`，导出结果里也绝不出现。

## 只导当前用户的当前角色

和聊天页的上下文一致。全账号导出是另一个功能（要处理跨角色的合并/去重）。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

#: 明确允许从 character 字典里导出的字段（其余一律丢弃）
CHARACTER_FIELDS = ("id", "name", "description", "personality", "avatar", "created_at")

#: 明确允许从 profile 里导出的字段
PROFILE_FIELDS = ("name", "city", "job", "mood", "recent_topics")

#: 明确允许从 character_state / self_awareness 里导出的字段
#: ⚠️ 这两个 dict 曾经被"整个倒出去"—— 测试抓出那是泄漏面，现在也走白名单
STATE_FIELDS = ("mood", "energy", "focus", "last_topic", "note")

#: `GET /memory/full` 允许返回的字段。
#:
#: ⚠️ 2026-10-22：这个端点原本 `return {"memory": mem}` 把**整个 memory dict**
#: 原样吐给前端（`require_auth` 即可，零字段过滤）—— 和 E11 修的是同一类问题。
#: 现在用白名单收敛。列表与前端 `types/api.ts` 的 `FullMemory` 保持一致，
#: 但**故意不含** memory 里的内部字段（`conflict_notice`/`proactive`/
#: `seen_world_event_ids`/`world_event_notice`）。
#:
#: 注意：`long_memory`/`events`/`chat_summary` 的真源在 `.rag.json`（不在 memory
#: 主 JSON 里），前端本来就用专门端点取它们，所以这里允许缺失。
FULL_MEMORY_FIELDS = (
    "profile", "favorability", "long_memory", "events", "chat_summary",
    "relationship", "character_state", "story", "stories", "story_history",
    "last_chat_time", "dreams", "dream", "self_awareness",
)


def pick_fields(source: Any, fields) -> Dict[str, Any]:
    """**白名单取字段** —— 源字典里别的键一律不进结果。

    公开版（原来是 `_pick`）：`/memory/full` 也要用同一套，
    避免两处各写一份白名单然后漂移。
    """
    if not isinstance(source, dict):
        return {}
    return {k: source.get(k) for k in fields}


def collect_export_data(
    mc,
    user_id: int,
    character_id: str,
    character: Optional[Dict[str, Any]] = None,
    messages: Optional[List[Dict[str, Any]]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """组装导出数据。**绝不抛** —— 导出失败顶多给个空骨架，不能让接口 500。"""
    now = now or datetime.now()
    data: Dict[str, Any] = {
        "meta": {
            "exported_at": now.isoformat(),
            "user_id": user_id,
            "character_id": character_id,
            "app": "treeHole",
        },
    }

    try:
        data["character"] = pick_fields(character or {}, CHARACTER_FIELDS)

        mem = mc.load_memory(user_id, character_id) or {}

        data["relationship"] = {
            "favorability": mem.get("favorability"),
            "relationship": pick_fields(mem.get("relationship") or {}, ("level", "stage", "reason")),
            # ⚠️ character_state/self_awareness 也走白名单 ——
            # 曾经"整个 dict 倒出去"，测试抓出那会泄漏 api_key/secret
            "character_state": pick_fields(mem.get("character_state") or {}, STATE_FIELDS),
            "self_awareness": pick_fields(mem.get("self_awareness") or {}, STATE_FIELDS),
        }
        data["profile"] = pick_fields(mem.get("profile") or {}, PROFILE_FIELDS)
        data["story"] = pick_fields(mem.get("story") or {}, ("chapter", "summary", "current_arc", "title"))

        # 长期记忆/摘要的真源在 .rag.json，用封装好的读法
        data["long_memory"] = _safe_list(mc.get_long_memories(user_id, character_id))
        data["chat_summary"] = _safe_list(mc.get_chat_summary(user_id, character_id))
        data["events"] = _safe_list(mc.get_events(user_id, character_id))

        # 日记 / 梦境：她写的东西，导出来才有"纪念册"的意义
        data["diaries"] = _safe_list(mem.get("diaries"))
        data["dreams"] = _safe_list(mem.get("dreams"))

        data["messages"] = _normalize_messages(
            messages if messages is not None else _safe_list(_load_messages(mc, user_id, character_id))
        )
    except Exception as e:  # noqa: BLE001 - 导出绝不能 500
        logger.warning("[export] user=%s char=%s 收集数据失败: %s", user_id, character_id, e)
        data.setdefault("error", "部分数据收集失败")

    return data


def render_markdown(data: Dict[str, Any]) -> str:
    """渲染成"纪念册"：分节、可读、有标题层级。"""
    meta = data.get("meta") or {}
    character = data.get("character") or {}
    rel = data.get("relationship") or {}

    name = character.get("name") or character.get("id") or "她"
    lines: List[str] = []
    lines.append(f"# 你和{name}的纪念册")
    lines.append("")
    lines.append(f"> 导出于 {meta.get('exported_at', '')} · treeHole")
    lines.append("")

    # ── 角色设定 ──
    lines.append("## 她是谁")
    lines.append("")
    if character.get("description"):
        lines.append(str(character["description"]))
        lines.append("")
    if character.get("personality"):
        lines.append(f"**性格**：{character['personality']}")
        lines.append("")

    # ── 关系 ──
    lines.append("## 你们的关系")
    lines.append("")
    fav = rel.get("favorability")
    if fav is not None:
        lines.append(f"- 好感度：**{fav}**")
    relationship = _as_dict(rel.get("relationship"))
    for k, v in relationship.items():
        if _blank(v):
            continue
        lines.append(f"- {k}：{v}")
    state = _as_dict(rel.get("character_state"))
    if state.get("mood"):
        lines.append(f"- 她最近的心情：{state['mood']}")
    lines.append("")

    # ── 用户画像 ──
    profile = _as_dict(data.get("profile"))
    filled = [(k, v) for k, v in profile.items() if not _blank(v)]
    if filled:
        lines.append("## 她眼中的你")
        lines.append("")
        for k, v in filled:
            lines.append(f"- {k}：{_fmt(v)}")
        lines.append("")

    # ── 剧情 ──
    story = _as_dict(data.get("story"))
    filled = [(k, v) for k, v in story.items() if not _blank(v)]
    if filled:
        lines.append("## 一起经历的剧情")
        lines.append("")
        for k, v in filled:
            lines.append(f"- {k}：{_fmt(v)}")
        lines.append("")

    # ── 记忆 ──
    long_memory = data.get("long_memory") or []
    if long_memory:
        lines.append("## 她记住的事")
        lines.append("")
        for m in long_memory:
            lines.append(f"- {m}")
        lines.append("")

    summaries = data.get("chat_summary") or []
    if summaries:
        lines.append("## 聊天摘要")
        lines.append("")
        for s in summaries:
            lines.append(f"- {s}")
        lines.append("")

    # ── 日记 / 梦境 ──
    diaries = data.get("diaries") or []
    if diaries:
        lines.append("## 她的日记")
        lines.append("")
        for d in diaries:
            if isinstance(d, dict):
                lines.append(f"**{d.get('date', '')}**")
                lines.append("")
                lines.append(str(d.get("text", "")))
                lines.append("")

    dreams = data.get("dreams") or []
    if dreams:
        lines.append("## 她的梦")
        lines.append("")
        for d in dreams:
            if isinstance(d, dict):
                lines.append(f"**{d.get('date', '')}**")
                lines.append("")
                lines.append(str(d.get("text", "")))
                lines.append("")

    # ── 事件 ──
    events = data.get("events") or []
    if events:
        lines.append("## 发生过得事")
        lines.append("")
        for e in events:
            if isinstance(e, dict):
                when = e.get("time") or ""
                lines.append(f"- {when} {e.get('event', '')}".strip())
            else:
                lines.append(f"- {e}")
        lines.append("")

    # ── 聊天记录 ──
    messages = data.get("messages") or []
    if messages:
        lines.append("## 聊天记录")
        lines.append("")
        for m in messages:
            if not isinstance(m, dict):
                continue
            who = "你" if m.get("role") == "user" else name
            lines.append(f"**{who}**：{m.get('content', '')}")
            lines.append("")

    if not _has_substance(lines):
        lines.append("_（还没有什么可导出的内容）_")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _has_substance(lines: List[str]) -> bool:
    """除了标题和说明，有没有真内容（别被空行骗了）。"""
    for ln in lines:
        t = ln.strip()
        if not t or t.startswith("#") or t.startswith(">") or t.startswith("_"):
            continue
        if t.startswith(("她是谁", "你们的关系", "她眼中的你", "一起经历的剧情",
                         "她记住的事", "聊天摘要", "她的日记", "她的梦",
                         "发生过得事", "聊天记录")):
            continue
        return True
    return False


def _has_substance(lines: List[str]) -> bool:
    """除了标题和说明，有没有真内容（别被空行骗了）。"""
    for ln in lines:
        t = ln.strip()
        if not t or t.startswith("#") or t.startswith(">") or t.startswith("_"):
            continue
        if t.startswith(("她是谁", "你们的关系", "她眼中的你", "一起经历的剧情",
                         "她记住的事", "聊天摘要", "她的日记", "她的梦",
                         "发生过得事", "聊天记录")):
            continue
        return True
    return False


def render_json(data: Dict[str, Any]) -> str:
    """JSON 格式（备份/机器读）。"""
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


# ── 内部 ────────────────────────────────────────────────────

def _blank(value: Any) -> bool:
    """None / 空串 / 空列表 / 空 dict 都算空（别往纪念册里写 "None"）。"""
    if value is None:
        return True
    if isinstance(value, (str, list, dict, tuple)) and len(value) == 0:
        return True
    return False


def _fmt(value: Any) -> str:
    """列表渲染成顿号分隔（`recent_topics` 那种别带 Python 的方括号和引号）。"""
    if isinstance(value, (list, tuple)):
        return "、".join(str(x) for x in value)
    return str(value)


def _as_dict(value: Any) -> Dict[str, Any]:
    """坏类型一律当空 dict（渲染层不能因为 relationship 是字符串就崩）。"""
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    return []


def _load_messages(mc, user_id: int, character_id: str) -> List[Any]:
    """聊天历史在 `funcation/memory.py`（不是 memory_center）。"""
    try:
        from funcation import memory as memory_module

        return memory_module.load_memory(user_id, character_id) or []
    except Exception as e:  # noqa: BLE001
        logger.info("[export] 读聊天历史失败: %s", e)
        return []


def _normalize_messages(messages: List[Any]) -> List[Dict[str, Any]]:
    """只留 role/content，且按原顺序。坏条目丢掉（不抛）。"""
    out: List[Dict[str, Any]] = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        content = m.get("content")
        if role not in ("user", "assistant") or content is None:
            continue
        out.append({"role": role, "content": str(content)})
    return out
