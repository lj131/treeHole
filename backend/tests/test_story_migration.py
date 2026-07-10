"""story 格式迁移单测 —— 旧单 story dict → 新 stories 数组，幂等。"""
from funcation.memory_center import MemoryCenter, create_default_memory


def _old_story(stage=1, max_stage=5):
    return {
        "story_id": "s-1",
        "title": "初次相遇",
        "description": "命运的邂逅",
        "stage": stage,
        "max_stage": max_stage,
        "stages": ["相遇", "交谈", "告别", "重逢", "约定"],
        "last_update_date": "2026-06-01",
    }


def test_migrate_old_story_to_stories(mc):
    data = {"favorability": 50, "story": _old_story()}
    mc._migrate_story_format(data)
    assert "stories" in data and len(data["stories"]) == 1
    s = data["stories"][0]
    assert s["id"] == "s-1"
    assert s["title"] == "初次相遇"
    assert s["type"] == "main"
    assert s["status"] == "active"      # stage(1) < max_stage(5)
    assert s["stage"] == 1
    assert s["stages"] == ["相遇", "交谈", "告别", "重逢", "约定"]
    assert s["branch_points"] == []
    # 旧 story 字段被清空，避免下次 save 重复写回 JSON
    assert data["story"] == {}


def test_migrate_completed_old_story(mc):
    data = {"favorability": 50, "story": _old_story(stage=5, max_stage=5)}
    mc._migrate_story_format(data)
    assert data["stories"][0]["status"] == "completed"


def test_migrate_idempotent_when_already_new(mc):
    """已有非空 stories 时直接返回，不动数据。"""
    data = {"favorability": 50, "stories": [{"id": "x", "title": "已存在"}]}
    mc._migrate_story_format(data)
    assert data["stories"] == [{"id": "x", "title": "已存在"}]


def test_migrate_empty_story_creates_empty_list(mc):
    """旧 story 缺关键字段 → 建空 stories 数组。"""
    data = {"favorability": 50, "story": {}}
    mc._migrate_story_format(data)
    assert data["stories"] == []


def test_migrate_no_story_key(mc):
    """完全没有 story 键的旧数据 → 建 stories=[]。"""
    data = {"favorability": 50}
    mc._migrate_story_format(data)
    assert data["stories"] == []


def test_default_memory_passes_migration_cleanly(mc):
    """create_default_memory 产出已是新格式，迁移不应改动它。"""
    data = create_default_memory()
    mc._migrate_story_format(data)
    assert data["stories"] == []
