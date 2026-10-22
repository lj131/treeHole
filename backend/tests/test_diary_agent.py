"""角色日记（E9）。重点：**懒生成必须幂等**、**无素材不写**、**只 merge 自己的字段**。"""
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from funcation import diary_agent


# ⚠️ 不能硬编码日期字符串（"2026-10-21" 这种）—— 跨天后测试就会红。
# 用"现在的今天"和"相对的昨天"，让测试永远和时间无关。
NOW = datetime.now().replace(microsecond=0)
TODAY = diary_agent.today_str()
YESTERDAY = (NOW - timedelta(days=1)).strftime("%Y-%m-%d")


class FakeMC:
    """最小 mc 假件：只实现日记用到的几个方法。"""

    def __init__(self, store=None, interactions=None, events=None, summaries=None):
        self.store = store if store is not None else {}
        self.interactions = interactions if interactions is not None else []
        self.events = events if events is not None else []
        self.saved = []

    # 日记会读的
    def load_memory(self, user_id, character_id):
        return dict(self.store)

    def load_user_current_world(self, user_id):
        return {"id": "campus"}

    def get_user_world_mode(self, user_id):
        return "auth"

    def load_world_state(self, world_id, user_id, mode):
        return {
            "world_state": {"npc_registry": {"interactions": self.interactions}},
            "current_events": self.events,
        }

    def get_chat_summary(self, user_id, character_id):
        return []

    # 写入
    def save_memory(self, user_id, character_id, data):
        self.saved.append(data)
        self.store = dict(data)


@pytest.fixture
def mc_with_material():
    return FakeMC(
        interactions=[{"characters": "小羽", "dialogue": "她今天一直在看窗外"}],
        events=[{"title": "校庆筹备委员会重组"}],
    )


# ── due 判定 ────────────────────────────────────────────────

def test_due_when_no_diary_today():
    assert diary_agent.diary_due({}, now=NOW) is True
    assert diary_agent.diary_due({"diary": {"date": YESTERDAY, "text": "x"}},
                                 now=NOW) is True


def test_not_due_when_diary_today_exists():
    """**今天已有 → 不该再写**（幂等的核心）"""
    assert diary_agent.diary_due({"diary": {"date": TODAY, "text": "x"}},
                                 now=NOW) is False


def test_due_on_bad_input():
    assert diary_agent.diary_due(None, now=NOW) is True
    assert diary_agent.diary_due({"diary": "bad"}, now=NOW) is True
    assert diary_agent.diary_due({"diary": {"date": None}}, now=NOW) is True


# ── 懒生成幂等 ──────────────────────────────────────────────

def test_ensure_diary_returns_existing_without_llm():
    """**今天已有 → 直接返回，不调 LLM**（否则用户每开一次面板烧一次钱）"""
    existing = {"date": TODAY, "text": "今天的日记"}
    mc = FakeMC(store={"diary": existing})
    with patch.object(diary_agent.client.chat.completions, "create") as create:
        out = diary_agent.ensure_diary(mc, 1, "linwan", {"name": "林婉"}, mc.load_memory(1, "linwan"))
    assert out == existing
    create.assert_not_called()


def test_ensure_diary_generates_once_then_reuses():
    """第一次写、第二次复用（真实的两连开面板场景）"""
    mc = FakeMC(
        store={},
        interactions=[{"characters": "小羽", "dialogue": "她今天一直在看窗外"}],
        events=[{"title": "校庆筹备委员会重组"}],
    )
    with patch.object(diary_agent.client.chat.completions, "create") as create:
        create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="今天有点烦。"))]
        )
        first = diary_agent.ensure_diary(mc, 1, "linwan", {"name": "林婉"}, {})
        assert first == {"date": TODAY, "text": "今天有点烦。"}
        assert create.call_count == 1

        # 第二次：memory 里已有今天的日记
        second = diary_agent.ensure_diary(
            mc, 1, "linwan", {"name": "林婉"}, mc.load_memory(1, "linwan")
        )
        assert second == first
        assert create.call_count == 1      # **没有第二次 LLM 调用** ✅


def test_no_material_returns_none_without_llm():
    """**素材全空 → 返回 None 且不调 LLM**（编一篇空的比没有更糟）"""
    mc = FakeMC()   # 空互动 + 空事件
    with patch.object(diary_agent.client.chat.completions, "create") as create:
        out = diary_agent.ensure_diary(mc, 1, "linwan", {"name": "林婉"}, {})
    assert out is None
    create.assert_not_called()


def test_llm_failure_returns_none_and_does_not_raise():
    """LLM 挂 → None，**不抛**（UI 不能因此 500）"""
    mc = FakeMC(
        interactions=[{"characters": "小羽", "dialogue": "x"}],
        events=[{"title": "y"}],
    )
    with patch.object(diary_agent.client.chat.completions, "create", side_effect=RuntimeError("boom")):
        out = diary_agent.ensure_diary(mc, 1, "linwan", {"name": "林婉"}, {})
    assert out is None


def test_overlong_diary_discarded():
    """超长日记被丢弃（通常是模型跑飞）"""
    mc = FakeMC(
        interactions=[{"dialogogue": "x", "characters": "小羽"}],
        events=[{"title": "y"}],
    )
    with patch.object(diary_agent.client.chat.completions, "create") as create:
        create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="长" * (diary_agent.MAX_DIARY_CHARS + 1)))]
        )
        out = diary_agent.ensure_diary(mc, 1, "linwan", {"name": "林婉"}, {})
    assert out is None
    assert mc.saved == []      # 没有落库


# ── 落库 ────────────────────────────────────────────────────

def test_record_diary_merges_own_fields_only():
    """**只 merge diary/diaries**，不动 favorability / dream 等别人的字段"""
    store = {"favorability": 77, "dream": {"text": "一场梦"}, "long_memory": ["x"]}
    mc = FakeMC(store=store)
    with patch.object(diary_agent.client.chat.completions, "create") as create:
        create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="今天的日记。"))]
        )
        diary_agent.ensure_diary(
            mc, 1, "linwan", {"name": "林婉"},
            {"interactions": [], "events": []},
        )
    # 上面素材空 → 不会生成，换有素材的 store 重来
    mc2 = FakeMC(
        store=store,
        interactions=[{"characters": "小羽", "dialogue": "她看了窗外"}],
        events=[{"title": "校庆"}],
    )
    diary_agent._record_diary(mc2, 1, "linwan", "今天的日记。")

    saved = mc2.store
    assert saved["diary"] == {"date": TODAY, "text": "今天的日记。"}
    assert saved["diaries"][-1]["text"] == "今天的日记。"
    # 别人的字段完好
    assert saved["favorability"] == 77
    assert saved["dream"] == {"text": "一场梦"}
    assert saved["long_memory"] == ["x"]


def test_diary_history_truncated():
    """历史超过上限被截断"""
    store = {"diaries": [{"date": f"2026-10-{i:02d}", "text": f"d{i}"} for i in range(1, 11)]}
    mc = FakeMC(store=store)
    diary_agent._record_diary(mc, 1, "linwan", "新的一篇")
    assert len(mc.store["diaries"]) == diary_agent.MAX_DIARY_HISTORY
    assert mc.store["diaries"][-1]["text"] == "新的一篇"


def test_get_diary_history_newest_first():
    mem = {"diaries": [
        {"date": "2026-10-19", "text": "前天"},
        {"date": YESTERDAY, "text": "昨天"},
        {"date": "2026-10-21", "text": "今天"},
    ]}
    hist = diary_agent.get_diary_history(mem)
    assert [h["text"] for h in hist] == ["今天", "昨天", "前天"]
    assert diary_agent.get_diary_history(None) == []
    assert diary_agent.get_diary_history({"diaries": "bad"}) == []


# ── prompt ──────────────────────────────────────────────────

def test_prompt_uses_npc_and_world_events():
    p = diary_agent.build_diary_prompt(
        {"name": "林婉", "description": "高冷"},
        ["小羽：她看了窗外"],
        ["校庆筹备委员会重组"],
    )
    assert "林婉" in p
    assert "她看了窗外" in p          # NPC 互动
    assert "校庆筹备委员会重组" in p    # 世界事件
    # 视角约束：不要写"用户"这个词
    assert "不要提到\"用户\"" in p or '不要提到"用户"' in p


def test_prompt_handles_empty_material():
    p = diary_agent.build_diary_prompt({"name": "林婉"}, [], [])
    assert "今天没什么特别的互动" in p
    assert "今天没什么大事发生" in p


# ── 验证"测试能失败"的锚点：去掉今天已有就跳过 → 下面 3 条会红 ──
# test_ensure_diary_returns_existing_without_llm
# test_ensure_diary_generates_once_then_reuses
# test_not_due_when_diary_today_exists
