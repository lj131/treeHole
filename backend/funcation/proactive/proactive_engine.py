from datetime import datetime

from funcation.proactive import proactive_trigger

from funcation.proactive import proactive_decision

from funcation.proactive import proactive_cooldown

from funcation.proactive import proactive_message_agent


def run(
        mc,
        user_id,
        character,
        world
):
    memory_data = mc.load_memory(
        user_id,
        character["id"]
    )

    trigger = (
        proactive_trigger.detect_trigger(
            memory_data
        )
    )

    if not trigger:

        return None

    if not proactive_decision.should_send(
            memory_data
    ):
        return None

    if not proactive_cooldown.check(
            memory_data
    ):
        return None

    message = (
        proactive_message_agent.generate_message(
            trigger,
            character,
            world,
            memory_data
        )
    )

    # 梦境是**投递成功才标记**：recognize 前的决策/冷却都可能拦下它，
    # 在 detect_trigger 里就地清 flag 会让梦凭空消失（用户永远看不到）。
    if trigger.get("trigger") == "dream":
        from funcation import dream_agent

        dream_agent.mark_delivered(
            mc,
            user_id,
            character["id"],
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

    proactive[
        "today_count"
    ] = proactive.get(
        "today_count",
        0
    ) + 1

    mc.save_memory(
        user_id,
        character["id"],
        memory_data
    )

    return message