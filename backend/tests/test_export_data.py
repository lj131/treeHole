"""数据导出（E11）。重点：**敏感字段绝不外泄**、**区块齐全**、**不越权**。"""
import json
from datetime import datetime

from funcation import export_data


NOW = datetime(2026, 10, 22, 15, 0)


class FakeMC:
    """记录调用参数，用于验证"不越权"。"""

    def __init__(self, mem=None, long_memory=None, summaries=None, events=None, messages=None):
        self.mem = mem or {}
        self.long_memory = long_memory if long_memory is not None else []
        self.summaries = summaries if summaries is not None else []
        self.events = events if events is not None else []
        self.messages = messages if messages is not None else []
        self.calls = []

    def load_memory(self, user_id, character_id):
        self.calls.append(("load_memory", user_id, character_id))
        return dict(self.mem)

    def get_long_memories(self, user_id, character_id):
        self.calls.append(("get_long_memories", user_id, character_id))
        return list(self.long_memory)

    def get_chat_summary(self, user_id, character_id):
        self.calls.append(("get_chat_summary", user_id, character_id))
        return list(self.summaries)

    def get_events(self, user_id, character_id):
        self.calls.append(("get_events", user_id, character_id))
        return list(self.events)


def base_mc():
    return FakeMC(
        mem={
            "favorability": 63,
            "relationship": {"level": "亲近"},
            "character_state": {"mood": "平静"},
            "profile": {"name": "小明", "city": "北京"},
            "story": {"chapter": "第3章"},
            "diaries": [{"date": "2026-10-21", "text": "今天很累。"}],
            "dreams": [{"date": "2026-10-20", "text": "梦到下雨。"}],
        },
        long_memory=["我不吃香菜"],
        summaries=["我们聊了考试"],
        events=[{"time": "2026-10-21", "event": "一起去看了电影"}],
    )


def character():
    return {
        "id": "linwan",
        "name": "林婉",
        "description": "高冷的学生会成员",
        "personality": "外冷内热",
        "avatar": "linwan.png",
        "created_at": "2026-01-01",
    }


# ── 区块齐全 ────────────────────────────────────────────────

def test_collect_covers_all_sections():
    d = export_data.collect_export_data(
        base_mc(), 1, "linwan", character(),
        messages=[{"role": "user", "content": "你好"}, {"role": "assistant", "content": "嗯"}],
        now=NOW,
    )
    for key in (
        "meta", "character", "relationship", "profile", "story",
        "long_memory", "chat_summary", "events", "diaries", "dreams", "messages",
    ):
        assert key in d, f"缺区块: {key}"


def test_collect_with_empty_data_still_has_keys():
    """**空数据也不能缺键** —— 否则渲染时 KeyError，且用户以为导出坏了"""
    d = export_data.collect_export_data(FakeMC(), 1, "linwan", None, messages=[], now=NOW)
    # 列表类区块空时就是 []
    for key in ("long_memory", "chat_summary", "events", "diaries", "dreams", "messages"):
        assert key in d
        assert d[key] == [], key
    # character/profile/story 是**白名单结构**：键总在、值为空（结构稳定）
    for key in ("character", "profile", "story"):
        assert key in d
        assert not any(d[key].values()), key
    # relationship 区块：**结构稳定**（键总在），空数据时所有值都是空
    rel = d["relationship"]
    assert set(rel.keys()) == {
        "favorability", "relationship", "character_state", "self_awareness"
    }
    assert rel["favorability"] is None
    # 嵌套的三个都是白名单结构：键在、值全空
    for k in ("relationship", "character_state", "self_awareness"):
        assert not any(rel[k].values()), f"{k} 里有非空值"


def test_collect_does_not_crash_on_bad_input():
    """坏输入不抛（导出失败顶多空骨架，不能 500）"""
    mc = FakeMC(mem={"profile": "bad", "relationship": None, "story": 42})
    d = export_data.collect_export_data(mc, 1, "linwan", "not-a-dict", messages="bad", now=NOW)
    assert isinstance(d, dict)
    assert d["messages"] == []


def test_messages_normalized_to_role_content_only():
    """聊天记录只留 role/content，坏条目丢掉"""
    d = export_data.collect_export_data(
        base_mc(), 1, "linwan", character(),
        messages=[
            {"role": "user", "content": "你好"},
            {"role": "system", "content": "ignore me"},
            {"role": "assistant"},                      # 没 content
            "not a dict",
            {"role": "assistant", "content": "在的"},
        ],
        now=NOW,
    )
    assert d["messages"] == [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "在的"},
    ]


# ── 🔒 安全：敏感字段绝不外泄 ──────────────────────────────

def test_sensitive_fields_never_leak():
    """**核心安全承诺**：源数据里塞了敏感字段，导出结果里一个都不出现"""
    mc = FakeMC(
        mem={
            "favorability": 60,
            "api_key": "sk-SECRET-111",
            "DEEPSEEK_API_KEY": "sk-SECRET-222",
            "password": "p@ss",
            "token": "tok-SECRET-333",
            "secret": "shh",
            "internal_path": "D:/secret/dir",
            "other_user_id": 999,
            # 塞在嵌套里也一样
            "profile": {
                "name": "小明",
                "api_key": "sk-NESTED-444",
                "token": "tok-NESTED-555",
            },
            "character_state": {"mood": "平静", "secret": "nested-secret"},
        },
    )
    char = dict(character())
    char["api_key"] = "sk-CHAR-666"
    char["internal_note"] = "别导出我"

    d = export_data.collect_export_data(mc, 1, "linwan", char, messages=[], now=NOW)
    blob = json.dumps(d, ensure_ascii=False) + export_data.render_markdown(d)

    for secret in (
        "sk-SECRET-111", "sk-SECRET-222", "sk-NESTED-444", "sk-CHAR-666",
        "p@ss", "tok-SECRET-333", "tok-NESTED-555", "shh",
        "D:/secret/dir", "nested-secret", "别导出我",
    ):
        assert secret not in blob, f"泄漏了敏感字段: {secret}"

    # 而该在的还在（白名单不是把整个 profile 丢掉）
    assert d["profile"]["name"] == "小明"
    assert d["character"]["name"] == "林婉"


def test_character_only_whitelisted_fields():
    char = dict(character())
    char["api_key"] = "x"
    char["internal_note"] = "y"
    d = export_data.collect_export_data(FakeMC(), 1, "linwan", char, messages=[], now=NOW)
    assert set(d["character"].keys()) == set(export_data.CHARACTER_FIELDS)


def test_profile_only_whitelisted_fields():
    mc = FakeMC(mem={"profile": {"name": "小明", "api_key": "leak", "token": "leak"}})
    d = export_data.collect_export_data(mc, 1, "linwan", None, messages=[], now=NOW)
    assert set(d["profile"].keys()) == set(export_data.PROFILE_FIELDS)


# ── 不越权 ──────────────────────────────────────────────────

def test_only_reads_passed_user_and_character():
    """只读传入的 user_id/character_id（不读别人的）"""
    mc = base_mc()
    export_data.collect_export_data(mc, 7, "other_char", character(), messages=[], now=NOW)
    for call in mc.calls:
        assert call[1] == 7, call
        assert call[2] == "other_char", call


# ── 渲染 ────────────────────────────────────────────────────

def test_markdown_has_all_sections():
    d = export_data.collect_export_data(
        base_mc(), 1, "linwan", character(),
        messages=[{"role": "user", "content": "你好"}, {"role": "assistant", "content": "嗯"}],
        now=NOW,
    )
    md = export_data.render_markdown(d)
    for heading in (
        "# 你和林婉的纪念册", "## 她是谁", "## 你们的关系",
        "## 她眼中的你", "## 一起经历的剧情", "## 她记住的事",
        "## 聊天摘要", "## 她的日记", "## 她的梦",
        "## 发生过得事", "## 聊天记录",
    ):
        assert heading in md, f"Markdown 缺标题: {heading}"
    # 内容也在
    assert "我不吃香菜" in md
    assert "你好" in md
    assert "63" in md


def test_markdown_empty_data_has_placeholder():
    md = export_data.render_markdown({"meta": {"exported_at": "x"}})
    assert "纪念册" in md
    assert "还没有什么可导出" in md


def test_markdown_handles_bad_nested_types():
    d = {
        "meta": {},
        "character": {"name": "林婉"},
        "relationship": {"favorability": 60, "relationship": "bad", "character_state": "bad"},
        "messages": ["bad", {"role": "user", "content": "在吗"}],
        "diaries": ["bad", {"date": "d", "text": "t"}],
    }
    md = export_data.render_markdown(d)
    assert "在吗" in md


def test_markdown_never_prints_none():
    """纪念册里不该出现字面 "None"（实测发现 stage/reason 空值时很难看）"""
    d = export_data.collect_export_data(
        FakeMC(mem={
            "favorability": 60,
            "relationship": {"level": "亲近", "stage": None, "reason": ""},
            "profile": {"name": "小明", "city": None, "recent_topics": []},
            "story": {"chapter": "第3章", "summary": None},
        }),
        1, "linwan", character(), messages=[], now=NOW,
    )
    md = export_data.render_markdown(d)
    assert "None" not in md
    assert "亲近" in md and "第3章" in md and "小明" in md


def test_markdown_formats_lists_readably():
    """列表渲染成顿号分隔，别带 Python 的方括号和引号"""
    d = export_data.collect_export_data(
        FakeMC(mem={"profile": {"recent_topics": ["考试", "周末"]}}),
        1, "linwan", character(), messages=[], now=NOW,
    )
    md = export_data.render_markdown(d)
    assert "考试、周末" in md
    assert "['" not in md


def test_render_json_parseable_and_complete():
    d = export_data.collect_export_data(base_mc(), 1, "linwan", character(), messages=[], now=NOW)
    raw = export_data.render_json(d)
    parsed = json.loads(raw)          # 必须可解析
    assert parsed["character"]["name"] == "林婉"
    assert parsed["meta"]["user_id"] == 1
    assert "你好" not in raw           # 没传 messages → 不该有聊天内容


# ── 验证"测试能失败"的锚点：把 collect 改成"整个 dict 倒出去" → 下面 3 条会红 ──
# test_sensitive_fields_never_leak
# test_character_only_whitelisted_fields
# test_profile_only_whitelisted_fields
