"""E6 端到端：冲突 → 通知 → 触发 → 消息生成。

重点验证**不污染**（不写系统用户）和 **flag 语义**（只读不清，投递后才清）。
"""
import pytest

from funcation import interaction_agent, tension
from funcation.proactive import proactive_trigger


def _conflict_result(fav_delta=-15, reason="因为社团的事吵了起来"):
    return {
        "interaction_summary": "两人因为社团分工吵了起来",
        "dialogues": [{"speaker": "林婉", "content": "你根本没把这件事当回事。"}],
        "relationship_changes": [
            {
                "from": "林婉",
                "to": "小羽",
                "favorability_delta": fav_delta,
                "trust_delta": -5,
                "reason": reason,
            }
        ],
        "gossip_events": [],
        "world_impact": "",
    }


# ── 冲突检测（复用 tension，这里确认接线正确） ──────────────

def test_conflict_detected_from_llm_output():
    found = tension.detect_conflict(_conflict_result())
    assert len(found) == 1
    assert found[0]["severity"] == 2
    assert tension.should_notify_conflict(found[0]) is True


def test_mild_friction_not_notified():
    """小摩擦（-5）不专门来倾诉"""
    found = tension.detect_conflict(_conflict_result(fav_delta=-5))
    assert found[0]["severity"] == 1
    assert tension.should_notify_conflict(found[0]) is False


# ── 通知写入 ────────────────────────────────────────────────

def test_notify_conflicts_writes_to_user_memory(mc, tmp_data_dir):
    """**写进调用方传的 user_id**，不是 _SYSTEM_USER_ID"""
    user_id = 7
    # 造一份该用户的角色记忆
    mc.save_memory(user_id, "linwan", {"favorability": 50})
    registry = {}
    name_to_id = {"林婉": "linwan", "小羽": "maid"}
    valid_ids = {"linwan", "maid"}

    written = interaction_agent._notify_conflicts(
        mc,
        _conflict_result(),
        name_to_id,
        valid_ids,
        user_id,
        registry,
        "2026-10-16 14:00",
    )

    assert written == "linwan"
    mem = mc.load_memory(user_id, "linwan")
    notice = mem.get("conflict_notice")
    assert notice and notice["changed"] is True
    assert notice["with"] == "小羽"
    assert notice["severity"] == 2
    # 冷却日期落进 registry（会被 save_world_state 一起持久化）
    assert registry["last_conflict_date"] == "2026-10-16"


def test_notify_skipped_without_user_id(mc, tmp_data_dir):
    """世界级调用（无 user_id）不写通知 —— 没有倾诉对象"""
    registry = {}
    assert (
        interaction_agent._notify_conflicts(
            mc, _conflict_result(), {"林婉": "linwan"}, {"linwan"}, None, registry, "2026-10-16 14:00"
        )
        is None
    )
    assert "last_conflict_date" not in registry


def test_notify_respects_cooldown(mc, tmp_data_dir):
    """**冷却期内不重复写**（刚吵过就别再吵）"""
    user_id = 8
    mc.save_memory(user_id, "linwan", {"favorability": 50})
    registry = {"last_conflict_date": "2026-10-15"}  # 昨天刚吵过

    written = interaction_agent._notify_conflicts(
        mc,
        _conflict_result(),
        {"林婉": "linwan"},
        {"linwan"},
        user_id,
        registry,
        "2026-10-16 14:00",
    )

    assert written is None
    assert not mc.load_memory(user_id, "linwan").get("conflict_notice")


def test_notify_ignores_positive_interaction(mc, tmp_data_dir):
    """正常友好互动不写通知（不破坏现状）"""
    user_id = 9
    mc.save_memory(user_id, "linwan", {"favorability": 50})
    friendly = {
        "relationship_changes": [
            {"from": "林婉", "to": "小羽", "favorability_delta": 5, "reason": "一起吃饭"}
        ]
    }
    assert (
        interaction_agent._notify_conflicts(
            mc, friendly, {"林婉": "linwan"}, {"linwan"}, user_id, {}, "2026-10-16 14:00"
        )
        is None
    )


def test_unknown_character_skipped(mc, tmp_data_dir):
    """角色名解析不出来 → 跳过（不崩）"""
    assert (
        interaction_agent._notify_conflicts(
            mc, _conflict_result(), {}, set(), 10, {}, "2026-10-16 14:00"
        )
        is None
    )


# ── 触发器 ──────────────────────────────────────────────────

def test_trigger_returns_conflict():
    mem = {
        "conflict_notice": {
            "changed": True,
            "with": "小羽",
            "summary": "吵了一架",
            "severity": 2,
        }
    }
    trig = proactive_trigger.detect_trigger(mem)
    assert trig["trigger"] == "conflict"
    assert "小羽" in trig["reason"]
    assert trig["conflict"]["severity"] == 2


def test_trigger_reads_but_does_not_clear_flag():
    """**只读不清** —— 被冷却拦下时这件事不能凭空消失"""
    mem = {"conflict_notice": {"changed": True, "with": "小羽", "severity": 2}}
    first = proactive_trigger.detect_trigger(mem)
    second = proactive_trigger.detect_trigger(mem)
    assert first and second
    assert first["trigger"] == second["trigger"] == "conflict"
    # flag 还在（由 engine 在投递成功后清）
    assert mem["conflict_notice"]["changed"] is True


def test_conflict_takes_priority_over_world_event():
    """冲突优先于世界事件（强情绪该先说）"""
    mem = {
        "conflict_notice": {"changed": True, "with": "小羽", "severity": 2},
        "world_event_notice": {"changed": True, "type": "created"},
    }
    assert proactive_trigger.detect_trigger(mem)["trigger"] == "conflict"


def test_dream_still_takes_priority_over_conflict():
    """dream 的优先级不动（它有"昨晚"的时效性）"""
    mem = {
        "dream": {"text": "梦到考试迟到", "delivered": False},
        "conflict_notice": {"changed": True, "with": "小羽", "severity": 2},
    }
    assert proactive_trigger.detect_trigger(mem)["trigger"] == "dream"


def test_delivered_conflict_does_not_trigger():
    mem = {"conflict_notice": {"changed": False, "delivered": True, "with": "小羽"}}
    assert proactive_trigger.detect_trigger(mem) is None


def test_no_conflict_key_is_fine():
    """没有 conflict_notice 字段时行为与之前一致（不破坏现状）"""
    assert proactive_trigger.detect_trigger({}) is None
    assert proactive_trigger.detect_trigger({"conflict_notice": {}}) is None


# ── 完整接线：apply_interaction_result 真的会把通知写下去 ──────

def test_apply_interaction_result_writes_conflict_notice(mc, tmp_data_dir):
    """走**完整函数**（不只 `_notify_conflicts`）—— 验证接线没漏。"""
    user_id = 11
    mc.save_memory(user_id, "linwan", {"favorability": 50})

    ok = interaction_agent.apply_interaction_result(
        mc,
        "campus",
        _conflict_result(),
        {"林婉": "linwan", "小羽": "maid"},
        user_id,
        "private",
    )

    assert ok is True
    notice = mc.load_memory(user_id, "linwan").get("conflict_notice")
    assert notice is not None, "冲突通知没有落盘 —— 接线断了"
    assert notice["severity"] == 2
    assert notice["with"] == "小羽"
    # 冷却日期也落盘了（存在 world_state 里）
    world = mc.load_world_state("campus", user_id, "private")
    assert world["world_state"]["npc_registry"]["last_conflict_date"]


def test_apply_friendly_interaction_leaves_no_notice(mc, tmp_data_dir):
    """友好互动不产生通知（不破坏现状）"""
    user_id = 12
    mc.save_memory(user_id, "linwan", {"favorability": 50})
    friendly = {
        "interaction_summary": "一起吃了饭",
        "relationship_changes": [
            {"from": "林婉", "to": "小羽", "favorability_delta": 5, "reason": "一起吃饭"}
        ],
    }
    interaction_agent.apply_interaction_result(
        mc, "campus", friendly, {"林婉": "linwan", "小羽": "maid"}, user_id, "private"
    )
    assert not mc.load_memory(user_id, "linwan").get("conflict_notice")


# ── 完整接线：apply_interaction_result 真的会把通知写下去 ──────

def test_apply_interaction_result_writes_conflict_notice(mc, tmp_data_dir):
    """走**完整函数**（不只 `_notify_conflicts`）—— 验证接线没漏。"""
    user_id = 11
    mc.save_memory(user_id, "linwan", {"favorability": 50})

    ok = interaction_agent.apply_interaction_result(
        mc,
        "campus",
        _conflict_result(),
        {"林婉": "linwan", "小羽": "maid"},
        user_id,
        "private",
    )

    assert ok is True
    notice = mc.load_memory(user_id, "linwan").get("conflict_notice")
    assert notice is not None, "冲突通知没有落盘 —— 接线断了"
    assert notice["severity"] == 2
    assert notice["with"] == "小羽"
    # 冷却日期也落盘了（存在 world_state 里）
    world = mc.load_world_state("campus", user_id, "private")
    assert world["world_state"]["npc_registry"]["last_conflict_date"]


def test_apply_friendly_interaction_leaves_no_notice(mc, tmp_data_dir):
    """友好互动不产生通知（不破坏现状）"""
    user_id = 12
    mc.save_memory(user_id, "linwan", {"favorability": 50})
    friendly = {
        "interaction_summary": "一起吃了饭",
        "relationship_changes": [
            {"from": "林婉", "to": "小羽", "favorability_delta": 5, "reason": "一起吃饭"}
        ],
    }
    interaction_agent.apply_interaction_result(
        mc, "campus", friendly, {"林婉": "linwan", "小羽": "maid"}, user_id, "private"
    )
    assert not mc.load_memory(user_id, "linwan").get("conflict_notice")
