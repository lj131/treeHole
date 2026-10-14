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
from datetime import datetime

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


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


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
    last_chat = memory_data.get("last_chat_time") or ""
    last_dream_date = dream.get("date") or ""
    if not last_chat:
        return ""
    if last_chat[:10] <= last_dream_date:
        return ""

    return "有新素材"


def _build_prompt(character: dict, profile: dict, story: dict, summaries: list) -> str:
    lines = "\n".join(f"- {s}" for s in summaries[-SUMMARY_MATERIAL:])
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


def generate_dream(mc, user_id, character_id, character) -> str:
    """生成一场梦的文本。**不落盘**（落盘由 `ensure_dream_pending` 负责）。"""
    memory_data = mc.load_memory(user_id, character_id)
    summaries = mc.get_chat_summary(user_id, character_id) or []

    prompt = _build_prompt(
        character=character or {},
        profile=memory_data.get("profile", {}),
        story=memory_data.get("story", {}),
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
    """
    try:
        memory_data = mc.load_memory(user_id, character_id)
        if not _dream_due(memory_data):
            return None

        summaries = mc.get_chat_summary(user_id, character_id) or []
        if not summaries:
            return None

        text = generate_dream(mc, user_id, character_id, character)
        if not text:
            logger.warning("[dream] user=%s char=%s LLM 返回空，跳过", user_id, character_id)
            return None

        _record_dream(mc, user_id, character_id, memory_data, text)
        logger.info("[dream] user=%s char=%s 已生成梦境（%d 字）",
                    user_id, character_id, len(text))
        return memory_data.get("dream")
    except (Exception, SystemExit) as e:  # noqa: BLE001 - 后台任务绝不能抛
        logger.warning("[dream] user=%s char=%s 生成失败（跳过）：%s", user_id, character_id, e)
        return None


def _record_dream(mc, user_id, character_id, memory_data: dict, text: str) -> None:
    """把新生成的梦写进 memory：追加历史 + 设 pending。"""
    today = _today()
    history = list(memory_data.get("dreams") or [])
    history.append({"date": today, "text": text})
    history = history[-MAX_DREAM_HISTORY:]

    memory_data["dreams"] = history
    memory_data["dream"] = {"text": text, "date": today, "delivered": False}
    mc.save_memory(user_id, character_id, memory_data)


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
