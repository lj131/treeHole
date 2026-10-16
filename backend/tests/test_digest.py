"""世界日报聚合（纯函数）。重点测时间解析 —— 那是本模块最容易回归的地方。"""
from datetime import datetime

import pytest

from funcation import digest


# ── 时间解析：三种格式都必须吃下 ──────────────────────────────

@pytest.mark.parametrize(
    "raw,expected",
    [
        # 空格分隔（NPC 互动 / 八卦 / 世界影响 / 记忆事件）
        ("2026-06-05 17:13", datetime(2026, 6, 5, 17, 13)),
        ("2026-10-12 14:03", datetime(2026, 10, 12, 14, 3)),
        # 纯日期（世界事件 / 剧情 / 梦境 / 里程碑）
        ("2026-06-17", datetime(2026, 6, 17, 0, 0)),
        ("2026-10-14", datetime(2026, 10, 14, 0, 0)),
        # ISO 带微秒（主动消息）
        ("2026-10-15T19:43:55.611966", datetime(2026, 10, 15, 19, 43, 55, 611966)),
        # ISO 不带微秒
        ("2026-10-15T19:43:55", datetime(2026, 10, 15, 19, 43, 55)),
    ],
)
def test_parse_all_three_formats(raw, expected):
    assert digest.parse_digest_time(raw) == expected


@pytest.mark.parametrize("bad", [None, "", "   ", "not a date", "2026-13-45", 123, [], {}])
def test_parse_bad_input_returns_none_without_raising(bad):
    """**一条坏数据不能毁掉整份日报** —— 必须返回 None，绝不抛"""
    assert digest.parse_digest_time(bad) is None


def test_parse_trims_whitespace():
    assert digest.parse_digest_time("  2026-06-17  ") == datetime(2026, 6, 17)


# ── 条目构建 ────────────────────────────────────────────────

NOW = datetime(2026, 10, 16, 12, 0)


def _world():
    return {
        "world_state": {
            "current_events": [
                {"name": "春季运动会", "description": "筹备中", "created_at": "2026-10-15"},
            ],
            "history_events": [
                {"name": "旧事件", "created_at": "2026-10-01", "status": "finished"},
            ],
            "npc_registry": {
                "recent_interactions": [
                    {"time": "2026-10-16 09:30", "summary": "两人在图书馆吵了一架"},
                ],
                "gossip": [
                    {"time": "2026-10-15 21:00", "source": "小羽", "target": "林婉", "content": "她把标准问出来了"},
                ],
                "world_impacts": [
                    {"time": "2026-10-15 22:00", "impact": "图书馆人流增加"},
                ],
            },
        }
    }


def _memories():
    return {
        "linwan": {
            "character_state": {"name": "林婉"},
            "dreams": [{"date": "2026-10-15", "text": "梦见考试迟到"}],
            "stories": [
                {"title": "校园祭", "stage": 2, "max_stage": 5, "last_advance_date": "2026-10-16"},
            ],
            "proactive": {"last_time": "2026-10-16T08:00:00", "last_message": "早"},
            "self_awareness": {"milestones": [{"date": "2026-10-14", "from": "普通", "to": "朋友"}]},
        }
    }


def _rag():
    return {"linwan": {"events": [{"time": "2026-10-14 14:03", "event": "关系从普通变成朋友"}]}}


def test_build_entries_collects_all_kinds():
    entries = digest.build_entries(
        world_state=_world(), memories=_memories(), rag_data=_rag(), now=NOW, days=3
    )
    kinds = {e["kind"] for e in entries}
    assert digest.KIND_WORLD_EVENT in kinds
    assert digest.KIND_NPC_INTERACTION in kinds
    assert digest.KIND_GOSSIP in kinds
    assert digest.KIND_WORLD_IMPACT in kinds
    assert digest.KIND_DREAM in kinds
    assert digest.KIND_STORY in kinds
    assert digest.KIND_PROACTIVE in kinds
    assert digest.KIND_MILESTONE in kinds
    assert digest.KIND_MEMORY_EVENT in kinds


def test_entries_sorted_newest_first():
    entries = digest.build_entries(world_state=_world(), memories=_memories(), now=NOW, days=3)
    times = [e["at"] for e in entries]
    assert times == sorted(times, reverse=True)


def test_time_window_filters_old_entries():
    """10-01 的旧事件在 3 天窗口外，必须被过滤"""
    entries = digest.build_entries(world_state=_world(), now=NOW, days=3)
    assert not any("旧事件" in e["title"] for e in entries)


def test_window_is_day_based_not_second_based():
    """**窗口按天算**：days=3 → 今天 + 前两天 = 10-14 / 10-15 / 10-16

    纯日期粒度的数据（世界事件存 "2026-10-13"，解析成 00:00）不该因为
    "比 now - 3天 的 12:00 早"就被误杀 —— 用户视角里 10-14 就是"最近三天"。
    """
    def _ev(name, date):
        return {"world_state": {"current_events": [{"name": name, "created_at": date}]}}

    assert len(digest.build_entries(world_state=_ev("首日", "2026-10-14"), now=NOW, days=3)) == 1
    assert len(digest.build_entries(world_state=_ev("越界", "2026-10-13"), now=NOW, days=3)) == 0


def test_days_1_means_today_only():
    def _ev(name, date):
        return {"world_state": {"current_events": [{"name": name, "created_at": date}]}}

    assert len(digest.build_entries(world_state=_ev("今天", "2026-10-16"), now=NOW, days=1)) == 1
    assert len(digest.build_entries(world_state=_ev("昨天", "2026-10-15"), now=NOW, days=1)) == 0


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, 7),        # 没传 → 默认（7 天，见 DEFAULT_DAYS 注释）
        (0, 1),           # **0 是有效值，要 clamp 到 1，不能当"没传"**
        (-5, 1),
        (1, 1),
        (7, 7),
        (30, 30),
        (99999, 30),      # 超上限
        ("5", 5),         # 字符串数字
        ("abc", 7),       # 非法 → 默认
    ],
)
def test_normalize_days(raw, expected):
    """`days or DEFAULT` 的坑：0 是 falsy 但合法，必须 clamp 而不是替换成默认"""
    assert digest.normalize_days(raw) == expected


def test_days_clamped():
    """days 超上限被 clamp，不该把整个历史拉出来"""
    ws = {"world_state": {"current_events": [{"name": "很旧", "created_at": "2020-01-01"}]}}
    assert digest.build_entries(world_state=ws, now=NOW, days=99999) == []
    assert digest.build_entries(world_state=ws, now=NOW, days=0) == []  # clamp 到 1 天


def test_entry_has_date_field_for_frontend_grouping():
    entries = digest.build_entries(world_state=_world(), now=NOW, days=3)
    assert all(e["date"] and len(e["date"]) == 10 for e in entries)


def test_empty_inputs_return_empty_list():
    assert digest.build_entries(now=NOW) == []
    assert digest.build_entries(world_state={}, memories={}, now=NOW) == []


def test_bad_records_are_skipped_not_fatal():
    """坏数据（缺时间 / 类型不对）跳过，好的照常出来"""
    ws = {
        "world_state": {
            "current_events": [
                {"name": "好的", "created_at": "2026-10-15"},
                {"name": "缺时间"},                       # 无 created_at
                "我不是 dict",                            # 类型错
                {"name": "时间非法", "created_at": "???"},
            ],
            "npc_registry": {"recent_interactions": [None, {"time": "2026-10-16 10:00", "summary": "ok"}]},
        }
    }
    entries = digest.build_entries(world_state=ws, now=NOW, days=3)
    assert len(entries) == 2
    assert any("好的" in e["title"] for e in entries)


def test_names_mapping_takes_priority():
    """**给了名字映射就用它** —— 记忆文件里不存角色名，不给会显示 "linwan" 而不是「林婉」"""
    mem = {"linwan": {"dreams": [{"date": "2026-10-15", "text": "梦"}]}}
    entries = digest.build_entries(memories=mem, names={"linwan": "林婉"}, now=NOW, days=3)
    assert "林婉" in entries[0]["title"]
    assert "linwan" not in entries[0]["title"]


def test_name_falls_back_to_character_state_then_id():
    """三级兜底：names 映射 → 记忆里的 name → id"""
    mem = {
        "a": {"character_state": {"name": "记忆里的名字"}, "dreams": [{"date": "2026-10-15", "text": "x"}]},
        "b": {"dreams": [{"date": "2026-10-15", "text": "y"}]},
    }
    entries = digest.build_entries(memories=mem, names={"a": "映射名字"}, now=NOW, days=3)
    titles = {e["character_id"]: e["title"] for e in entries}
    assert "映射名字" in titles["a"]          # 映射优先于记忆里的
    assert "b" in titles["b"]                # 都没有 → id


def test_names_mapping_takes_priority():
    """**给了名字映射就用它** —— 记忆文件里不存角色名，不给会显示 "linwan" 而不是「林婉」"""
    mem = {"linwan": {"dreams": [{"date": "2026-10-15", "text": "梦"}]}}
    entries = digest.build_entries(memories=mem, names={"linwan": "林婉"}, now=NOW, days=3)
    assert "林婉" in entries[0]["title"]
    assert "linwan" not in entries[0]["title"]


def test_name_falls_back_to_character_state_then_id():
    """三级兜底：names 映射 → 记忆里的 name → id"""
    mem = {
        "a": {"character_state": {"name": "记忆里的名字"}, "dreams": [{"date": "2026-10-15", "text": "x"}]},
        "b": {"dreams": [{"date": "2026-10-15", "text": "y"}]},
    }
    entries = digest.build_entries(memories=mem, names={"a": "映射名字"}, now=NOW, days=3)
    titles = {e["character_id"]: e["title"] for e in entries}
    assert "映射名字" in titles["a"]          # 映射优先于记忆里的
    assert "b" in titles["b"]                # 都没有 → id


def test_memories_without_character_state_use_id_as_label():
    mem = {"maid": {"dreams": [{"date": "2026-10-15", "text": "梦"}]}}
    entries = digest.build_entries(memories=mem, now=NOW, days=3)
    assert entries and "maid" in entries[0]["title"]


def test_pending_dream_included():
    """待投递的梦（memory.dream）也要进时间线"""
    mem = {"linwan": {"dream": {"date": "2026-10-16", "text": "今晚的梦", "delivered": False}}}
    entries = digest.build_entries(memories=mem, now=NOW, days=3)
    assert len(entries) == 1
    assert "今晚的梦" in entries[0]["detail"]


# ── 概览 ────────────────────────────────────────────────────

def test_summarize_counts_and_text():
    entries = digest.build_entries(world_state=_world(), memories=_memories(), now=NOW, days=3)
    s = digest.summarize(entries)
    assert s["total"] == len(entries)
    assert s["counts"][digest.KIND_NPC_INTERACTION] == 1
    assert "NPC 互动 1 条" in s["text"]


def test_summarize_empty_says_quiet():
    s = digest.summarize([])
    assert s["total"] == 0
    assert "安静" in s["text"]
