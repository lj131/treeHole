"""记忆回响：挑出该展示的召回结果（纯函数）。"""
import pytest

from funcation import memory_echo


def item(text, collection="long_memory", score=1.3):
    return {"text": text, "collection": collection, "score": score}


# ── 集合白名单 ──────────────────────────────────────────────

def test_only_echo_collections():
    """**story / relationship 是设定与状态，不是"记得"** —— 必须排除"""
    retrieved = [
        item("你喜欢喝美式", "long_memory", 1.3),
        item("【主线】林婉的暖流计划…", "story", 1.2),
        item("关系等级：朋友（好感度：50）", "relationship", 1.25),
        item("关系从普通变成朋友", "events", 1.4),
    ]
    echoes = memory_echo.pick_echoes(retrieved)
    assert [e["collection"] for e in echoes] == ["long_memory", "events"]


def test_keeps_profile_but_filters_noise():
    """profile 可以留，但「用户姓名：未知」这种占位是噪音"""
    retrieved = [
        item("用户姓名：未知", "profile", 1.1),
        item("用户喜欢在深夜写代码，讨厌开会", "profile", 1.3),
    ]
    echoes = memory_echo.pick_echoes(retrieved)
    assert len(echoes) == 1
    assert "深夜写代码" in echoes[0]["text"]


# ── 排序与截断 ──────────────────────────────────────────────

def test_sorted_by_score_ascending():
    """**score 是 distance：越小越相关**，前 N 条取最小的"""
    retrieved = [
        item("这条最不相关的内容", "long_memory", 1.9),
        item("这条最相关的内容", "long_memory", 1.1),
        item("这条居中相关的内容", "long_memory", 1.5),
    ]
    echoes = memory_echo.pick_echoes(retrieved, limit=2)
    assert echoes[0]["text"] == "这条最相关的内容"
    assert echoes[1]["text"] == "这条居中相关的内容"


def test_limit_applied():
    retrieved = [item(f"记忆{i}内容够长了", "long_memory", 1.0 + i * 0.1) for i in range(10)]
    assert len(memory_echo.pick_echoes(retrieved, limit=3)) == 3


def test_limit_default_is_three():
    retrieved = [item(f"记忆{i}内容够长了", "long_memory", 1.0 + i * 0.1) for i in range(10)]
    assert len(memory_echo.pick_echoes(retrieved)) == 3


def test_bad_limit_falls_back():
    retrieved = [item("内容够长的记忆", "long_memory", 1.2)]
    assert len(memory_echo.pick_echoes(retrieved, limit=0)) == 1
    assert len(memory_echo.pick_echoes(retrieved, limit="abc")) == 1


# ── 噪音剔除 ────────────────────────────────────────────────

def test_too_short_skipped():
    retrieved = [item("好的", "long_memory", 1.1), item("这条够长了可以展示", "long_memory", 1.3)]
    echoes = memory_echo.pick_echoes(retrieved)
    assert len(echoes) == 1
    assert "够长了" in echoes[0]["text"]


def test_placeholder_in_long_text_is_kept():
    """占位词只**短文本**才算噪音 —— 长句里的"未知"可能是有意义的叙述"""
    long_text = "用户说他最近状态不太好，对未来有点未知的焦虑，想找个时间聊聊这件事"
    echoes = memory_echo.pick_echoes([item(long_text, "long_memory", 1.2)])
    assert len(echoes) == 1


def test_duplicate_text_deduped():
    """同一条记忆可能出现在多个集合里，只展示一次"""
    same = "用户喜欢在周末爬山，最近在计划去黄山"
    retrieved = [item(same, "long_memory", 1.2), item(same, "profile", 1.3)]
    assert len(memory_echo.pick_echoes(retrieved)) == 1


# ── 输出形状 ────────────────────────────────────────────────

def test_output_has_no_score():
    """**不带 score** —— 前端不需要，显示 distance 只会让用户困惑"""
    echoes = memory_echo.pick_echoes([item("一条够长的记忆内容", "long_memory", 1.23)])
    assert set(echoes[0].keys()) == {"text", "collection"}


# ── 坏数据 ──────────────────────────────────────────────────

def test_empty_input():
    assert memory_echo.pick_echoes(None) == []
    assert memory_echo.pick_echoes([]) == []


def test_bad_items_skipped():
    retrieved = [None, "not a dict", 123, {"collection": "long_memory"}, item("有效内容够长了", "long_memory", 1.2)]
    echoes = memory_echo.pick_echoes(retrieved)
    assert len(echoes) == 1


def test_missing_score_still_included():
    """没有 score 的条目排最后，但不该被丢掉"""
    retrieved = [{"text": "没有分数的记忆内容", "collection": "long_memory"}]
    echoes = memory_echo.pick_echoes(retrieved)
    assert len(echoes) == 1


def test_non_numeric_score_sorts_last():
    retrieved = [
        {"text": "分数是字符串的记忆", "collection": "long_memory", "score": "bad"},
        item("有正常分数的记忆", "long_memory", 1.3),
    ]
    echoes = memory_echo.pick_echoes(retrieved)
    assert echoes[0]["text"] == "有正常分数的记忆"


# ── 摘要 ────────────────────────────────────────────────────

def test_echo_summary():
    assert memory_echo.echo_summary([]) == ""
    assert memory_echo.echo_summary(None) == ""
    assert memory_echo.echo_summary([{"text": "a", "collection": "long_memory"}]) == "参考了 1 条记忆"
    assert memory_echo.echo_summary([{}, {}, {}]) == "参考了 3 条记忆"
