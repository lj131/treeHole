from datetime import datetime


def should_send(memory_data):
    """要不要发这条主动消息。

    ⚠️ `today_count` 是**当天**的计数，不是终身累计。
    历史 bug：这个字段只增不清（`create_default_memory` 置 0 后就只 +1），
    于是 `today_count >= 5` 变成"这个角色一辈子最多主动发 5 条"，
    第 6 条起主动消息**永久静默**，且不报任何错（2026-10-14 修）。
    修法：计数旁边必须带 `count_date`，跨天先视为 0。
    """
    proactive = memory_data.get(
        "proactive",
        {}
    )

    # 跨天先清零。没有 count_date 的历史数据也按"今天之前"处理 → 视为 0。
    if proactive.get("count_date") != datetime.now().strftime("%Y-%m-%d"):
        today_count = 0
    else:
        today_count = proactive.get(
            "today_count",
            0
        )

    if today_count >= 5:

        return False

    state = memory_data.get(
        "character_state",
        {}
    )

    energy = state.get(
        "energy",
        100
    )

    if energy <= 10:

        return False

    return True
