"""长期记忆的时间轴（2026-11-09）。

## 这条要解决的问题

10-31 的 E2E 里，用户说「今天有点累」，她回「明天三点半，撑得住就来」——
而"明天三点半"来自 **9 天前**的一条长期记忆。原因是 `long_memory` 没有时间信息，
模型看到「我们约好明天下午三点集合」无从判断是哪天的"明天"。

## 本文件钉住四件事

1. 写入侧加日期前缀，且**已有前缀不叠加**
2. `update` / `delete` **前缀无关**匹配（否则 LLM 返回的 old_memory 命中不了，静默失败）
3. 更新**沿用原日期**（改内容不等于改时间）
4. prompt 里必须有解释前缀的话，否则加了前缀模型也不会用
"""
from datetime import datetime

import pytest

from funcation import memory_timeline as mt
from funcation import prompt
from funcation.memory_center import MemoryCenter

DAY1 = datetime(2026, 10, 30, 15, 0)
DAY2 = datetime(2026, 11, 9, 15, 0)


class _FrozenDatetime(datetime):
    current = DAY2

    @classmethod
    def now(cls, tz=None):
        return cls.current


@pytest.fixture(autouse=True)
def _freeze_today(monkeypatch):
    monkeypatch.setattr(mt, "datetime", _FrozenDatetime)


@pytest.fixture
def mc(monkeypatch):
    """隔离的 MemoryCenter：真源在内存，索引重建不碰网络/真实 chroma"""
    monkeypatch.setattr(MemoryCenter, "__init__", lambda self, *a, **k: None)
    obj = MemoryCenter()
    store = {"long_memory": []}

    monkeypatch.setattr(obj, "_load_rag", lambda u, c: dict(store))
    monkeypatch.setattr(obj, "_save_rag", lambda u, c, rag: (store.clear(), store.update(rag)))
    monkeypatch.setattr(obj, "_index_to_rag", lambda *a, **k: None)
    return obj, store


# ============================================================
# 纯函数
# ============================================================

def test_stamp_adds_iso_date():
    assert mt.stamp("我们约好明天三点集合") == "（2026-11-09）我们约好明天三点集合"


def test_stamp_is_idempotent():
    once = mt.stamp("一件事")
    assert mt.stamp(once) == once, "重复提取不该叠两层日期"


def test_stamp_handles_empty_and_non_string():
    assert mt.stamp("") == ""
    assert mt.stamp(None) == ""
    assert mt.stamp("  ") == ""
    assert mt.strip_stamp(123) == "123"


def test_strip_and_date():
    text = "（2026-10-30）我们约好明天三点集合"
    assert mt.strip_stamp(text) == "我们约好明天三点集合"
    assert mt.date_of(text) == "2026-10-30"
    assert mt.prefix_of(text) == "（2026-10-30）"
    assert mt.date_of("老数据没日期") == ""
    assert mt.prefix_of("老数据没日期") == ""


def test_only_leading_prefix_is_stripped():
    """正文里出现同样的字串不能被误删"""
    text = "（2026-10-30）他说（2026-01-01）那天不算"
    assert mt.strip_stamp(text) == "他说（2026-01-01）那天不算"


def test_same_memory_ignores_date():
    assert mt.same_memory("（2026-10-30）同一件事", "同一件事")
    assert mt.same_memory("（2026-10-30）同一件事", "（2026-11-09）同一件事")
    assert not mt.same_memory("同一件事", "另一件事")


def test_with_same_date_keeps_old_date():
    assert mt.with_same_date("新说法", "（2026-10-30）旧说法") == "（2026-10-30）新说法"


def test_with_same_date_on_legacy_stays_undated():
    """老数据更新后不能凭空变成"今天发生的" """
    assert mt.with_same_date("新说法", "旧说法（无日期）") == "新说法"


def test_defuse_relative_time():
    """**实测两轮都失败后的确定性手段**：不跟模型讲道理，直接改它看到的文本"""
    assert mt.defuse_relative_time("明天三点半后勤门口见") == "当时的『明天』三点半后勤门口见"
    assert mt.defuse_relative_time("下周再谈") == "当时的『下周』再谈"
    # 不含相对时间的句子一个字都不动
    assert mt.defuse_relative_time("体育馆漏水，她帮我搬了设备") == "体育馆漏水，她帮我搬了设备"


def test_defuse_does_not_touch_real_data_contract():
    """去活化只在渲染层，纯函数本身不产生日期前缀（真源格式不受影响）"""
    text = mt.stamp("明天三点半见")
    assert mt.date_of(text)                        # 真源仍带日期
    assert mt.strip_stamp(text) == "明天三点半见"   # 真源正文原样
    assert "当时的『明天』" not in text


# ============================================================
# MemoryCenter 接入
# ============================================================

def test_add_writes_dated_memory(mc):
    obj, store = mc
    obj.add_long_memory(1, "linwan", "我们约好明天三点集合")
    assert store["long_memory"] == ["（2026-11-09）我们约好明天三点集合"]


def test_add_dedupes_by_body_even_on_another_day(mc, monkeypatch):
    """**同一句话隔天再被提取一次，不该因为日期不同变成两条**"""
    obj, store = mc
    obj.add_long_memory(1, "linwan", "同一件事")
    # 用 monkeypatch 改「今天」，测试结束自动还原（直接改类属性会污染后续用例）
    monkeypatch.setattr(_FrozenDatetime, "current", DAY2.replace(day=10))
    obj.add_long_memory(1, "linwan", "同一件事")
    assert len(store["long_memory"]) == 1
    assert mt.date_of(store["long_memory"][0]) == "2026-11-09"


def test_update_finds_memory_without_prefix(mc):
    """**关键**：LLM 返回的 old_memory 不带日期，用 `==` 会静默失败"""
    obj, store = mc
    obj.add_long_memory(1, "linwan", "旧说法")
    obj.update_long_memory(1, "linwan", "旧说法", "新说法")
    assert store["long_memory"] == ["（2026-11-09）新说法"]


def test_update_finds_memory_with_prefix(mc):
    obj, store = mc
    obj.add_long_memory(1, "linwan", "旧说法")
    full = store["long_memory"][0]
    obj.update_long_memory(1, "linwan", full, "新说法")
    assert store["long_memory"] == ["（2026-11-09）新说法"]


def test_update_keeps_original_date(mc):
    obj, store = mc
    store["long_memory"] = ["（2026-10-30）旧说法"]
    obj.update_long_memory(1, "linwan", "旧说法", "新说法")
    assert store["long_memory"] == ["（2026-10-30）新说法"]


def test_update_missing_is_noop(mc):
    obj, store = mc
    store["long_memory"] = ["（2026-10-30）旧说法"]
    obj.update_long_memory(1, "linwan", "不存在的", "新说法")
    assert store["long_memory"] == ["（2026-10-30）旧说法"]


def test_delete_works_with_or_without_prefix(mc):
    obj, store = mc
    store["long_memory"] = ["（2026-10-30）要删的", "留下的"]
    assert obj.delete_long_memory(1, "linwan", "要删的") is True
    assert mt.strip_stamp(store["long_memory"][0]) == "留下的"

    store["long_memory"] = ["（2026-10-30）要删的", "留下的"]
    assert obj.delete_long_memory(1, "linwan", "（2026-10-30）要删的") is True
    assert len(store["long_memory"]) == 1


def test_legacy_undated_memory_still_editable(mc):
    """老数据（无前缀）的更新/删除必须照常可用"""
    obj, store = mc
    store["long_memory"] = ["老记忆"]
    obj.update_long_memory(1, "linwan", "老记忆", "改过的老记忆")
    assert store["long_memory"] == ["改过的老记忆"]
    assert obj.delete_long_memory(1, "linwan", "改过的老记忆") is True


# ============================================================
# prompt 解释（加了前缀但模型不懂 = 白加）
# ============================================================

def _long_section(text: str) -> str:
    """只取【长期记忆】段 —— 规则说明里也会出现「（日期不明）」这个字面量，
    直接对整个 prompt 做 count 会把它算进去。"""
    return text.split("【长期记忆】\n", 1)[1].split("\n\n【关键事件】", 1)[0]


def test_prompt_explains_date_prefix():
    text = prompt.build_memory_summary(
        short_messages=[], long_memories=["（2026-10-30）我们约好明天三点集合"],
        events=[], chat_summary=[], retrieved_memories=[],
    )
    assert "【记忆的时间" in text
    assert "❌ 错误示范" in text
    assert "日期不明" not in _long_section(text)   # 这条有日期，不该被标成旧事


def test_every_undated_memory_gets_explicit_label():
    """**实测教训**：只在开头写一句"没前缀的时间不明"压不住老记忆。
    必须让模型在每条材料旁边都看到标签。"""
    text = prompt.build_memory_summary(
        short_messages=[],
        long_memories=["明天三点半后勤门口见", "（2026-10-30）约好明天三点"],
        events=[], chat_summary=[], retrieved_memories=[],
    )
    section = _long_section(text)
    assert "（日期不明·旧事）当时的『明天』三点半后勤门口见" in section
    assert "（2026-10-30）当时的『明天』约好" not in section  # 带日期的保留日期
    assert "（2026-10-30）约好当时的『明天』三点" in section
    assert section.count("（日期不明·旧事）") == 1


def test_rag_hits_are_also_labeled():
    text = prompt.build_memory_summary(
        short_messages=[], long_memories=[], events=[], chat_summary=[],
        retrieved_memories=[{"collection": "long_memory", "text": "明天下午三点集合"}],
    )
    assert "【记忆的时间" in text
    assert "（日期不明·旧事）当时的『明天』下午三点集合" in text


def test_prompt_explains_prefix_when_only_rag_hits():
    """RAG 检索回来的文本也会进规则范围，说明不能只在有 long_memories 时加"""
    text = prompt.build_memory_summary(
        short_messages=[], long_memories=[], events=[], chat_summary=[],
        retrieved_memories=[{"collection": "long_memory", "text": "（2026-10-30）约好明天三点"}],
    )
    assert "【记忆的时间" in text


def test_prompt_omits_note_when_no_memories():
    """没记忆就别白烧 token"""
    text = prompt.build_memory_summary(
        short_messages=[], long_memories=[], events=[], chat_summary=[],
        retrieved_memories=[],
    )
    assert "【记忆的时间" not in text


def test_render_flags_stale_arrangements_per_memory():
    """含相对时间的旧安排要**逐条**带硬提示；普通记忆不要被误标"""
    text = prompt.build_memory_summary(
        short_messages=[],
        long_memories=["明天三点半后勤门口见", "她喜欢雨天"],
        events=[], chat_summary=[], retrieved_memories=[],
    )
    section = _long_section(text)
    assert "〔旧安排·已失效，禁止据此约时间〕" in section
    assert section.count("〔旧安排·已失效，禁止据此约时间〕") == 1
    assert "（日期不明·旧事）她喜欢雨天" in section


def test_memory_agent_prompt_forbids_relative_time(monkeypatch):
    """**治本**：新写入的记忆不许再用「明天/下周」这类相对时间。
    只改渲染层挡不住强诱导，源头必须干净。"""
    from funcation import memory_agent

    captured = {}

    class _FakeCompletions:
        def create(self, **kwargs):
            captured["prompt"] = kwargs["messages"][1]["content"]
            class _Resp:
                choices = [type("C", (), {"message": type("M", (), {
                    "content": '{"action":"ignore"}'
                })()})()]
            return _Resp()

    class _FakeChat:
        completions = _FakeCompletions()

    monkeypatch.setattr(memory_agent.client, "chat", _FakeChat())
    memory_agent.extract_memory("明天三点见", [])
    p = captured["prompt"]
    assert "绝对日期" in p
    assert "禁止出现" in p and "明天" in p
