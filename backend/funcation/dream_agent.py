"""梦境日记：用聊天摘要生成一场"梦"，次日由主动消息投递。

## 为什么复用 proactive 而不是新造通道

角色主动开口这件事，`funcation/proactive/` 已经有完整的
触发器 → 决策 → 冷却 → 生成 四段式。梦境只是**多了一种触发原因**，
再造一套投递机制只会多一条要维护的路径。

素材用 `mc.get_chat_summary()` —— 它的真源是 `data/memories/*.rag.json`
（P0 §1-7 之后），所以这里**不碰向量库**，向量库挂了这个功能照样能生成。

## 存储

    memory["dream"]  = {"text": str, "date": "2026-10-14", "delivered": False}
    memory["dreams"] = [{"date": ..., "text": ...}]     # 历史，最多 20 条

放**主 JSON**（和 `proactive` 并列）：它是"一条待投递的短消息"，不是检索对象。

## 三条闸门（别骚扰用户）

1. 已有 `delivered=False` 的梦 → **不叠加**。否则攒一堆排队，用户一次收到好几条。
2. 今天已经生成过 → 跳过。**一天一场**。
3. `last_chat_time` 不晚于上一场梦 → 没新素材，跳过。
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime

from dotenv import load_dotenv
from openai import OpenAI

logger = logging.getLogger(__name__)

load_dotenv()

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url=os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com"),
)

#: 历史最多留几条（再老的没意义，还会把 JSON 撑大）
MAX_DREAM_HISTORY = 20

#: 一次给 LLM 多少条聊天摘要当素材
SUMMARY_MATERIAL = 10

#: 生成的梦超过这个长度就丢弃。它是"一条待投递的短消息"，
#: 失控时会直接把主 JSON 撑大，而且 prompt 说 2-3 句就够了。
MAX_DREAM_CHARS = 600

#: 单条摘要进 prompt 时截断到这么长（一坨几百字的摘要会把 prompt 撑爆）
SUMMARY_ITEM_CHARS = 200


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _last_chat_date(memory_data: dict):
    """`last_chat_time` 的日期部分。解析不了返回 None。

    用 `datetime.fromisoformat` 而不是 `last_chat_time[:10]` 的**字符串切片** ——
    后者靠隐式格式契约，一旦换成 UTC / 带时区后缀 / 紧凑格式就静默失效
    （而且会被 `ensure_dream_pending` 的 except 吞成 warning，更难发现）。
    """
    raw = memory_data.get("last_chat_time") or ""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).date()
    except (ValueError, TypeError):
        logger.warning("[dream] last_chat_time 解析不了: %r", raw)
        return None


def _dream_date(raw: str):
    """把 YYYY-MM-DD 解析成 date；解析不了返回 None"""
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except (ValueError, TypeError):
        return None


def _dream_due(memory_data: dict) -> str:
    """判断现在该不该生成一场梦。返回原因；空串表示不该生成。

    刻意返回**原因**而不是布尔 —— 调用方（后台 tick）要能把它记进日志，
    否则"梦怎么没来"只能靠猜。
    """
    dream = memory_data.get("dream") or {}

    # 1) 上一场还没投递 → 不叠加
    if dream.get("text") and not dream.get("delivered"):
        return ""

    # 2) 今天已经生成过
    if dream.get("date") == _today():
        return ""

    # 3) 那之后没聊过天 → 没素材
    last_chat = _last_chat_date(memory_data)
    if last_chat is None:
        return ""
    last_dream = _dream_date(dream.get("date") or "")
    if last_dream is not None and last_chat <= last_dream:
        return ""

    return "有新素材"


def _build_prompt(character: dict, profile: dict, story: dict, summaries: list) -> str:
    # 单条摘要截断：一坨几百字的原文会把 prompt 撑爆，而且模型会照抄
    clipped = [str(s)[:SUMMARY_ITEM_CHARS] for s in summaries[-SUMMARY_MATERIAL:]]
    lines = "\n".join(f"- {s}" for s in clipped)
    return f"""
你正在为角色「{character.get("name", "")}」写**一场梦**。

角色设定：
{character.get("description", "")}

用户画像：
{profile}

当前剧情：
{story}

今天之前和用户聊过的内容：
{lines}

要求：

1 用第一人称写"我梦到了……"，2到3句话
2 必须从上面的聊天内容里取材，别写成通用鸡汤
3 梦可以荒诞、跳跃，但情绪要贴合角色
4 不要出现"梦"这个字以外的元叙述（不要写"这是一个关于……的梦"）
5 不要提到用户在现实里做了什么，只写梦里看到的画面和感觉

直接输出梦的内容
"""


def generate_dream(mc, user_id, character_id, character, memory_data: dict | None = None) -> str:
    """生成一场梦的文本。**不落盘**（落盘由 `ensure_dream_pending` 负责）。

    `memory_data` 是调用方已经加载的快照 —— 传进来就不必再 load 一次
    （否则门控用一个快照、prompt 用另一个快照，profile/story 中间可能已经变了）。
    """
    data = memory_data if memory_data is not None else mc.load_memory(user_id, character_id)
    summaries = mc.get_chat_summary(user_id, character_id) or []

    prompt = _build_prompt(
        character=character or {},
        profile=data.get("profile", {}),
        story=data.get("story", {}),
        summaries=summaries,
    )

    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        temperature=1.0,
    )
    text = (response.choices[0].message.content or "").strip()
    # 偶尔模型会给自己加引号，去掉
    return text.strip("「」\"'")


def ensure_dream_pending(mc, user_id, character_id, character) -> dict | None:
    """若条件满足就生成一场梦并标记为待投递。返回 `memory["dream"]`，否则 None。

    **绝不会抛** —— 它是后台任务，LLM 失败不该影响 tick，也不该影响主流程。

    ⚠️ 落盘前**重新 load 再只 merge 自己负责的字段**，不用开头那个旧快照整包回写 ——
    中间隔着一次数秒到数十秒的 LLM 调用，其间用户聊天链路的
    `update_last_chat_time` 等也在写同一个 JSON，整包回写会把它们覆盖掉
    （lost update）。
    """
    try:
        memory_data = mc.load_memory(user_id, character_id)
        if not _dream_due(memory_data):
            return None

        summaries = mc.get_chat_summary(user_id, character_id) or []
        if not summaries:
            return None

        text = generate_dream(mc, user_id, character_id, character, memory_data)
        if not text:
            logger.warning("[dream] user=%s char=%s LLM 返回空，跳过", user_id, character_id)
            return None
        if len(text) > MAX_DREAM_CHARS:
            logger.warning(
                "[dream] user=%s char=%s 梦太长（%d > %d），丢弃",
                user_id, character_id, len(text), MAX_DREAM_CHARS,
            )
            return None

        _record_dream(mc, user_id, character_id, memory_data, text)
        logger.info(
            "[dream] user=%s char=%s 已生成梦境（%d 字）", user_id, character_id, len(text)
        )
        return mc.load_memory(user_id, character_id).get("dream")
    except (Exception, SystemExit) as e:  # noqa: BLE001 - 后台任务绝不能抛
        logger.warning(
            "[dream] user=%s char=%s 生成失败（跳过）：%s", user_id, character_id, e
        )
        return None


def _record_dream(mc, user_id, character_id, memory_data: dict, text: str) -> dict:
    """把新生成的梦写进 memory：追加历史 + 设 pending。返回最新快照。

    **不整包回写** `memory_data`（那是早先加载的旧快照，会覆盖并发的修改）——
    重新读一份，只改 `dream` / `dreams` 两个字段再存。
    """
    today = _today()

    latest = mc.load_memory(user_id, character_id)
    history = list(latest.get("dreams") or [])
    history.append({"date": today, "text": text})
    history = history[-MAX_DREAM_HISTORY:]

    latest["dreams"] = history
    latest["dream"] = {"text": text, "date": today, "delivered": False}
    mc.save_memory(user_id, character_id, latest)
    return latest


def mark_delivered(mc, user_id, character_id, memory_data: dict | None = None) -> None:
    """把待投递的梦标记为已投递。

    由 `proactive_engine` 在**消息生成成功之后**调用 —— 中途失败不能标记，
    否则梦就被吃掉了（用户永远看不到）。
    """
    data = memory_data if memory_data is not None else mc.load_memory(user_id, character_id)
    dream = data.get("dream")
    if not dream or not dream.get("text"):
        return
    if dream.get("delivered"):
        return
    dream["delivered"] = True
    mc.save_memory(user_id, character_id, data)
