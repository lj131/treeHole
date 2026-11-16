"""群聊发言权调度：信号从数据层收集 → 加权选人（2026-11-16 批次 2）。

`_pick_interjection_speaker` 是 api 层的信号适配器（纯读），这里用假 mc +
真 world_state 字典验证四类信号真的进到了调度里，而不只是单测纯函数。

⚠️ session 级 `disable_rag` mock 不影响这里：本函数**只读** world_state / 角色列表，
   不碰向量库。
"""
import pytest

from api import api as api_module
from funcation import circadian, group_chat


class _FakeMC:
    def __init__(self, characters=None):
        self._characters = characters or []

    def get_all_characters(self):
        return self._characters


def _world(rels=None, recent=None):
    return {"world_state": {"npc_registry": {
        "relationships": rels or {},
        "recent_hecklers": recent or [],
    }}}


def _characters():
    return [
        {"id": "linwan", "name": "林婉", "personality": "高冷"},
        {"id": "maid", "name": "小羽", "personality": "活泼开朗"},
        {"id": "xiaomei", "name": "小梅", "personality": "文静"},
    ]


@pytest.fixture(autouse=True)
def _always_heckle(monkeypatch):
    """把 25% 概率门钉成恒真，让测试只检验"选谁"。"""
    monkeypatch.setattr(group_chat, "should_heckle", lambda *a, **k: True)


def test_late_night_excludes_everyone(monkeypatch):
    """深夜硬门：全员排除 → 不插嘴（和 incoming_call 一致）"""
    monkeypatch.setattr(
        circadian, "current_phase", lambda h: type("P", (), {"late_night": True})()
    )
    rels = {"linwan": {"maid": {"favorability": 90}, "xiaomei": {"favorability": 80}}}
    picked = api_module._pick_interjection_speaker(
        _FakeMC(_characters()), _world(rels),
        user_input="小梅你说的那个", main_reply="嗯", primary_id="linwan", seed="s",
    )
    assert picked is None


def test_mentioned_character_wins():
    """内容相关：提到小梅 vs 提到小羽 —— 被提到的那个命中数要明显上升。

    用**对比**而非绝对比例：小羽关系满值、小梅关系很低，单看关系必然是
    小羽赢；"提到谁"这个信号要能把天平扳回来。对比写法对样本噪声更鲁棒。
    """
    rels = {
        "linwan": {
            "maid": {"favorability": 100},   # 小羽关系满值
            "xiaomei": {"favorability": 20}, # 小梅关系低
        }
    }

    def _wins(msg):
        return sum(
            api_module._pick_interjection_speaker(
                _FakeMC(_characters()), _world(rels),
                user_input=msg, main_reply="嗯",
                primary_id="linwan", seed=f"s{i}",
            ) == "xiaomei"
            for i in range(60)
        )

    assert _wins("小梅你觉得呢") > _wins("今天天气不错") + 10


def test_recent_heckler_is_demoted():
    """防连庄：刚插过嘴的小羽，下一次明显更少被选"""
    rels = {"linwan": {"maid": {"favorability": 60}, "xiaomei": {"favorability": 60}}}
    without = sum(
        api_module._pick_interjection_speaker(
            _FakeMC(_characters()), _world(rels),
            user_input="今天天气不错", main_reply="是啊",
            primary_id="linwan", seed=f"s{i}",
        ) == "maid"
        for i in range(40)
    )
    with_recent = sum(
        api_module._pick_interjection_speaker(
            _FakeMC(_characters()), _world(rels, recent=["maid"]),
            user_input="今天天气不错", main_reply="是啊",
            primary_id="linwan", seed=f"s{i}",
        ) == "maid"
        for i in range(40)
    )
    assert with_recent < without, (with_recent, without)


def test_extrovert_gets_bonus():
    """外向加权：同关系、都不被提及，让小羽"外向" vs 去掉外向词，命中数要上升。

    同样用对比写法 —— 外向只是 +0.5 的弱信号，绝对比例会被样本噪声淹没。
    """
    rels = {"linwan": {"maid": {"favorability": 50}, "xiaomei": {"favorability": 50}}}
    extro_chars = _characters()               # 小羽 = 活泼开朗
    intro_chars = [dict(c) for c in _characters()]
    intro_chars[1]["personality"] = ""        # 小羽性格清空

    def _wins(chars):
        return sum(
            api_module._pick_interjection_speaker(
                _FakeMC(chars), _world(rels),
                user_input="今天天气不错", main_reply="是啊",
                primary_id="linwan", seed=f"s{i}",
            ) == "maid"
            for i in range(80)
        )

    assert _wins(extro_chars) > _wins(intro_chars)


def test_no_relationships_returns_none():
    """没有任何 NPC 关系 → 没有候选 → 不插嘴"""
    picked = api_module._pick_interjection_speaker(
        _FakeMC(_characters()), _world({}),
        user_input="你好", main_reply="你好", primary_id="linwan", seed="s",
    )
    assert picked is None


def test_primary_never_picked():
    """主角永不被选（即使关系矩阵里主角也与自己有关系）"""
    rels = {"linwan": {"linwan": {"favorability": 100}, "maid": {"favorability": 10}}}
    for i in range(20):
        picked = api_module._pick_interjection_speaker(
            _FakeMC(_characters()), _world(rels),
            user_input="林婉林婉林婉", main_reply="嗯",
            primary_id="linwan", seed=f"s{i}",
        )
        assert picked != "linwan"


def test_remember_heckler_keeps_recent_three():
    """写回 recent：去重 + 保留最近 3 个，新的排最前。用真 save 验证落盘。"""
    class _MemMC:
        def __init__(self):
            self.saved = None
            self.data = _world({}, recent=["old1", "old2", "old3"])

        def get_user_world_mode(self, user_id):
            return "public"

        def load_world_state(self, world_id, user_id, mode):
            return self.data

        def save_world_state(self, world_id, data, user_id, mode):
            self.saved = data

    mc = _MemMC()
    api_module._remember_heckler(mc, "campus", 1, "maid")
    recent = mc.saved["world_state"]["npc_registry"]["recent_hecklers"]
    assert recent[0] == "maid"          # 刚插嘴的排最前
    assert len(recent) == 3
    assert "old3" not in recent         # 列表末尾是最老的，被挤掉
    assert "old1" in recent             # 较新的还在


def test_remember_heckler_never_raises():
    """坏 mc → 不抛（挂主链路，绝不能崩）"""
    class _BadMC:
        def get_user_world_mode(self, user_id):
            raise RuntimeError("boom")

    api_module._remember_heckler(_BadMC(), "campus", 1, "maid")  # 不抛即通过
