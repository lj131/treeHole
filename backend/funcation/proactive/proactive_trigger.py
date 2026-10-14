def detect_trigger(memory_data):

    # 梦境：待投递的一场梦。
    # ⚠️ **不在这里清 flag** —— 后面还有决策/冷却两道关卡，拦下了梦不能丢。
    # 现有分支就地清 `changed` 是历史写法（清了就找不回来）；梦沿用它会
    # "被冷却拦下后凭空消失"。所以这里只读，由 `proactive_engine`
    # 在消息生成成功后调用 `dream_agent.mark_delivered()`。
    dream = memory_data.get("dream") or {}
    if dream.get("text") and not dream.get("delivered"):
        return {
            "trigger": "dream",
            "reason": "想分享昨晚的梦",
            "dream": dream,
        }

    world_notice = memory_data.get(
        "world_event_notice",
        {}
    )

    if world_notice.get("changed"):

        world_notice["changed"] = False

        type_labels = {
            "created": "世界事件开始",
            "advanced": "世界事件推进",
            "finished": "世界事件结束",
        }

        return {
            "trigger": "world_event",
            "reason": type_labels.get(
                world_notice.get("type", ""),
                "世界发生变化",
            ),
            "world_event": world_notice,
        }

    story = memory_data.get(
        "story",
        {}
    )

    if story.get("changed"):

        story["changed"] = False

        return {
            "trigger": "story",
            "reason": "剧情推进"
        }

    relationship = memory_data.get(
        "relationship",
        {}
    )

    if relationship.get(
            "level_changed"
    ):

        relationship[
            "level_changed"
        ] = False

        return {
            "trigger": "relation",
            "reason": "关系变化"
        }

    state = memory_data.get(
        "character_state",
        {}
    )

    if state.get(
            "mood_changed"
    ):

        state[
            "mood_changed"
        ] = False

        return {
            "trigger": "state",
            "reason": "心情变化"
        }

    return None