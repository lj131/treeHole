"""角色日记本（E9）—— 她用第一人称写日记，用户可以"偷看"。

## 为什么新写一个而不复用 `dream_agent`

复用引擎看似省事，但**四处都不同**，硬塞 mode 分支会把两个功能耦死：

| | 梦境（已有） | 日记（本模块） |
|---|---|---|
| 文体 | 荒诞、跳跃 | 平实、第一人称"今天……" |
| 素材 | 用户聊天摘要 `chat_summary` | **NPC 互动 + 世界事件** |
| 触发 | 一天一场 + 投递制（`delivered`） | 一天一篇 + **懒生成** |
| 存储 | `dream` / `dreams` | **`diary` / `diaries`（不混在一起）** |

推进计划原文要求"视角与梦境不同"，上面的差异表就是这个要求的落地。

## 为什么是懒生成

`world_tick_scheduler` 的后台 tick 在本地和 CI 都是**禁用的**
（`RUN_BACKGROUND_TICK=0`，启动日志会明确打出），真实数据里
`dreams: []`——梦从未生成过。所以把日记接进 tick 等于**永远看不到**。

改成：用户打开日记面板时，如果今天还没写，就当场写一篇。
更贴合"偷看"的体验，也不依赖调度器。
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

logger = logging.getLogger(__name__)

# 和 dream_agent 用同一套 client 构造（同一份 .env / 同一个网关）
client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url=os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com"),
)

#: 单篇日记最长字数（超长丢弃 —— 通常是模型跑飞了）
MAX_DIARY_CHARS = 400

#: 历史日记保留篇数（"偷看"最近的几篇就够）
MAX_DIARY_HISTORY = 7

#: prompt 里最多塞几条 NPC 互动
MAX_INTERACTION_ITEMS = 6

#: 单条素材截断（几百字的原文会把 prompt 撑爆，而且模型会照抄）
MAX_ITEM_CHARS = 120


def today_str(now: Optional[datetime] = None) -> str:
    return (now or datetime.now()).strftime("%Y-%m-%d")


def diary_due(memory_data: Optional[Dict[str, Any]], *, now: Optional[datetime] = None) -> bool:
    """今天还没写过日记 → True（该写一篇）。

    刻意比 `_dream_due` 简单：梦境要"投递制"是因为它会由主动消息带出来，
    日记没有投递环节，用户打开面板就是读。
    """
    if not memory_data or not isinstance(memory_data, dict):
        return True
    diary = memory_data.get("diary") or {}
    # diary 可能是坏数据（字符串/None/列表）—— 一律当"没有"处理，别抛
    if not isinstance(diary, dict):
        return True
    return diary.get("date") != today_str(now)


def build_diary_prompt(
    character: Dict[str, Any],
    npc_interactions: List[str],
    world_events: List[str],
) -> str:
    """构造日记 prompt：第一人称、平实、从 NPC 互动与世界事件取材。"""
    interactions = [str(s)[:MAX_ITEM_CHARS] for s in (npc_interactions or [])[-MAX_INTERACTION_ITEMS:]]
    events = [str(s)[:MAX_ITEM_CHARS] for s in (world_events or [])[-MAX_INTERACTION_ITEMS:]]
    rel_lines = "\n".join(f"- {s}" for s in interactions) or "- （今天没什么特别的互动）"
    evt_lines = "\n".join(f"- {s}" for s in events) or "- （今天没什么大事发生）"

    return f"""
你正在为角色「{character.get("name", "")}」写**今天的日记**。

角色设定：
{character.get("description", "")}

今天和其他人的互动：
{rel_lines}

世界上发生的事：
{evt_lines}

要求：

1 用第一人称写，2到4句话，像真人写在日记本上的字
2 从上面的互动和事件里取材，别写成通用鸡汤
3 可以写对某个人的看法、对某件事的态度，但要符合角色性格
4 **不要**写成梦境：不要荒诞跳跃，不要写"我梦到"
5 不要出现"这是一篇日记"这类元叙述，也绝对不要提到"用户"这个词
  （日记是写自己的，把对方当成"那个人"来写）
6 直接输出日记正文

直接输出
"""


def generate_diary(
    mc,
    user_id: int,
    character_id: str,
    character: Dict[str, Any],
    memory_data: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """生成一篇日记文本。**不落盘**（落盘由 `ensure_diary` 负责）。

    返回 None 表示这次没写成（没素材 / LLM 失败 / 超长）。
    """
    data = memory_data if memory_data is not None else mc.load_memory(user_id, character_id)
    interactions = _collect_npc_interactions(mc, user_id, character_id, data)
    events = _collect_world_events(mc, user_id, character_id, data)

    # 素材全空就不写 —— 编一篇空的比没有更糟（用户一看就是敷衍）
    if not interactions and not events:
        logger.info("[diary] user=%s char=%s 无素材，跳过", user_id, character_id)
        return None

    prompt = build_diary_prompt(character or {}, interactions, events)

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9,
        )
        text = (response.choices[0].message.content or "").strip()
        text = text.strip("「」\"'").strip()
    except Exception as e:  # noqa: BLE001 - UI 不能因为 LLM 挂就 500
        logger.warning("[diary] user=%s char=%s 生成失败: %s", user_id, character_id, e)
        return None

    if not text:
        return None
    if len(text) > MAX_DIARY_CHARS:
        logger.warning(
            "[diary] user=%s char=%s 日记太长（%d > %d），丢弃",
            user_id, character_id, len(text), MAX_DIARY_CHARS,
        )
        return None
    return text


def ensure_diary(
    mc,
    user_id: int,
    character_id: str,
    character: Dict[str, Any],
    memory_data: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """**懒生成**：今天已有日记就直接返回它，否则写一篇。绝不抛。

    ⚠️ 落盘前**重新 load 再只 merge 自己负责的字段**（不用传进来的旧快照整包回写）
    —— 中间隔着一次数秒的 LLM 调用，其间用户聊天链路也在写同一个 JSON，
    整包回写会把它们覆盖掉（lost update）。照抄 `dream_agent._record_dream` 的做法。
    """
    try:
        data = memory_data if memory_data is not None else mc.load_memory(user_id, character_id)
        if not diary_due(data):
            return data.get("diary") or None

        text = generate_diary(mc, user_id, character_id, character, data)
        if not text:
            return None

        return _record_diary(mc, user_id, character_id, text)
    except (Exception, SystemExit) as e:  # noqa: BLE001 - UI 绝不能因为它 500
        logger.warning("[diary] user=%s char=%s 失败（跳过）: %s", user_id, character_id, e)
        return None


def get_diary_history(memory_data: Optional[Dict[str, Any]], limit: int = MAX_DIARY_HISTORY) -> List[Dict[str, Any]]:
    """最近几篇日记（新→旧）。坏数据返回空列表。"""
    if not memory_data or not isinstance(memory_data, dict):
        return []
    history = memory_data.get("diaries")
    if not isinstance(history, list):
        return []
    return [h for h in history if isinstance(h, dict)][-max(0, int(limit)):][::-1]


# ── 内部 ────────────────────────────────────────────────────
def _record_diary(mc, user_id: int, character_id: str, text: str) -> Dict[str, Any]:
    """写 `diary`（今天）+ 追加 `diaries`（历史）。返回最新快照。"""
    today = today_str()
    latest = mc.load_memory(user_id, character_id)

    history = list(latest.get("diaries") or [])
    history.append({"date": today, "text": text})
    history = history[-MAX_DIARY_HISTORY:]

    latest["diary"] = {"date": today, "text": text}
    latest["diaries"] = history
    mc.save_memory(user_id, character_id, latest)
    return latest["diary"]


def _collect_npc_interactions(mc, user_id: int, character_id: str, memory_data: Dict[str, Any]) -> List[str]:
    """素材之一：NPC 互动（`build_social_prompt_for_character` 的参与者与互动）。"""
    out: List[str] = []
    try:
        world = mc.load_user_current_world(user_id)
        world_id = world.get("id") if isinstance(world, dict) else None
        if not world_id:
            return out
        world_state = mc.load_world_state(world_id, user_id, mc.get_user_world_mode(user_id))
        registry = (world_state.get("world_state") or {}).get("npc_registry") or {}
        interactions = registry.get("interactions") or []
        for it in interactions[-MAX_INTERACTION_ITEMS:]:
            if not isinstance(it, dict):
                continue
            dialog = str(it.get("dialogue") or it.get("summary") or "").strip()
            who = str(it.get("characters") or it.get("participants") or "").strip()
            if dialog:
                out.append(f"{who}：{dialog}" if who else dialog)
    except Exception as e:  # noqa: BLE001
        logger.info("[diary] 取 NPC 互动失败（用剩下的素材）: %s", e)
    return out


def _collect_world_events(mc, user_id: int, character_id: str, memory_data: Dict[str, Any]) -> List[str]:
    """素材之二：世界事件（今日世界日报里的条目）。"""
    out: List[str] = []
    try:
        world = mc.load_user_current_world(user_id)
        world_id = world.get("id") if isinstance(world, dict) else None
        if not world_id:
            return out
        world_state = mc.load_world_state(world_id, user_id, mc.get_user_world_mode(user_id))
        for ev in (world_state.get("current_events") or [])[-MAX_INTERACTION_ITEMS:]:
            if not isinstance(ev, dict):
                continue
            title = str(ev.get("title") or "").strip()
            if title:
                out.append(title)
    except Exception as e:  # noqa: BLE001
        logger.info("[diary] 取世界事件失败（用剩下的素材）: %s", e)
    return out
