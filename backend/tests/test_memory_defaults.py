"""默认记忆结构 & 字段懒补单测。"""
from funcation.memory_center import (
    MemoryCenter,
    create_default_memory,
    create_default_world_state,
)


def test_default_memory_has_all_fields():
    m = create_default_memory()
    for key in ("profile", "favorability", "relationship", "character_state",
                "proactive", "story", "stories", "story_history", "self_awareness",
                "seen_world_event_ids", "last_chat_time"):
        assert key in m, f"缺字段 {key}"


def test_default_memory_initial_values():
    m = create_default_memory()
    assert m["favorability"] == 50
    assert m["relationship"] == {"level": "普通", "last_reason": ""}
    assert m["stories"] == []
    assert m["story_history"] == []
    assert m["seen_world_event_ids"] == []
    assert m["last_chat_time"] is None
    # self_awareness 初值用当前好感（50）作峰谷
    assert m["self_awareness"]["peak_favorability"] == 50
    assert m["self_awareness"]["min_favorability"] == 50
    assert m["self_awareness"]["milestones"] == []


def test_default_world_state_structure():
    ws = create_default_world_state("campus")
    assert ws["world_id"] == "campus"
    assert "world_state" in ws
    assert ws["current_events"] == []
    assert ws["history_events"] == []
    assert "meta" in ws and "created_at" in ws["meta"]


def test_ensure_self_awareness_fills_missing(mc):
    """旧记忆文件无 self_awareness 字段时懒补，用当前好感作峰谷初值。"""
    data = {"favorability": 73}
    mc._ensure_self_awareness(data)
    sa = data["self_awareness"]
    assert sa["peak_favorability"] == 73
    assert sa["min_favorability"] == 73
    assert sa["milestones"] == []
    assert sa["fav_trail"] == []


def test_ensure_self_awareness_idempotent(mc):
    """已有合法 self_awareness 时不覆盖。"""
    data = {
        "favorability": 50,
        "self_awareness": {"milestones": [{"date": "2026-01-01", "from": "普通", "to": "朋友"}],
                           "peak_favorability": 99, "min_favorability": 10,
                           "fav_trail": [], "peak_fav_date": "", "min_fav_date": "",
                           "first_chat_date": ""},
    }
    mc._ensure_self_awareness(data)
    assert data["self_awareness"]["peak_favorability"] == 99   # 没被覆盖
    assert len(data["self_awareness"]["milestones"]) == 1
