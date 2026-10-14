import logging
import threading
from datetime import datetime

from funcation.proactive import proactive_trigger
from funcation.proactive import proactive_decision
from funcation.proactive import proactive_cooldown
from funcation.proactive import proactive_message_agent

logger = logging.getLogger(__name__)

#: 同一个 (user, character) 的主动投递不许并发 ——
#: 用户开两个标签页就会双倍调 LLM、`today_count` 各基于旧值 +1、
#: 最后两份旧快照互相覆盖。进程内锁够用（当前是单进程 asyncio）。
_LOCKS: dict[tuple, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(user_id, character_id) -> threading.Lock:
    key = (user_id, character_id)
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


def run(
        mc,
        user_id,
        character,
        world
):
    """跑一轮主动消息。返回消息文本，或 None（不该发）。

    **不抛**：LLM 超时/异常只记日志返回 None。否则 /proactive 端点直接 500，
    用户看到的是"页面坏了"而不是"今天没有主动消息"。
    """
    character_id = character["id"]
    with _lock_for(user_id, character_id):
        try:
            return _run_locked(mc, user_id, character, world)
        except Exception as exc:  # noqa: BLE001 - 绝不能让它冒到 HTTP 层
            logger.exception(
                "[proactive] user=%s char=%s 投递失败（返回 None）: %s",
                user_id, character_id, exc,
            )
            return None


def _run_locked(mc, user_id, character, world):
    character_id = character["id"]
    memory_data = mc.load_memory(
        user_id,
        character_id
    )

    trigger = proactive_trigger.detect_trigger(memory_data)

    if not trigger:
        return None

    if not proactive_decision.should_send(memory_data):
        logger.debug(
            "[proactive] user=%s char=%s 被 decision 拦下（trigger=%s）",
            user_id, character_id, trigger.get("trigger"),
        )
        return None

    if not proactive_cooldown.check(memory_data):
        logger.debug(
            "[proactive] user=%s char=%s 冷却期内，跳过（trigger=%s）",
            user_id, character_id, trigger.get("trigger"),
        )
        return None

    message = proactive_message_agent.generate_message(
        trigger,
        character,
        world,
        memory_data
    )

    # 梦境是**投递成功才标记**：recognize 前的决策/冷却都可能拦下它，
    # 在 detect_trigger 里就地清 flag 会让梦凭空消失（用户永远看不到）。
    if trigger.get("trigger") == "dream":
        from funcation import dream_agent

        dream_agent.mark_delivered(
            mc,
            user_id,
            character_id,
            memory_data,
        )

    proactive = memory_data.setdefault(
        "proactive",
        {}
    )

    proactive[
        "last_time"
    ] = datetime.now().isoformat()

    proactive[
        "last_message"
    ] = message

    proactive[
        "last_trigger"
    ] = trigger["trigger"]

    today = datetime.now().strftime("%Y-%m-%d")
    if proactive.get("count_date") != today:
        # 跨天重新开始计数（见 proactive_decision.should_send 的说明）
        proactive["count_date"] = today
        proactive["today_count"] = 0
    proactive[
        "today_count"
    ] = proactive.get(
        "today_count",
        0
    ) + 1

    mc.save_memory(
        user_id,
        character_id,
        memory_data
    )

    logger.info(
        "[proactive] user=%s char=%s 已投递 trigger=%s 今日第 %d 条",
        user_id, character_id, trigger["trigger"], proactive["today_count"],
    )

    return message
