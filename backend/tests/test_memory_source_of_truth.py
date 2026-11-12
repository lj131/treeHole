"""记忆真源统一（P0 §1-7 根治）。

## 要买的东西

在 2026-10-14 之前，`long_memory` / `events` / `chat_summary` **只存在于向量库**，
于是向量库被隔离一次就等于**静默丢数据**（真实发生过 6 次误隔离）。

现在它们和 `profile` / `story` / `relationship` 一样：**真源在 JSON，向量库只是索引**。
本文件把这条不变量钉住 —— 尤其是**挪走整个向量库后数据必须还在**。

## 测试手法

不 mock `memory_rag`：直接用真的 chromadb（指向 tmp 目录），
这样"索引"这件事是真的在跑。**必须 monkeypatch `PERSIST_DIR`** ——
它是绝对路径（`BASE_DIR/data/chroma`），不受 `tmp_data_dir` 的 chdir 隔离影响，
不 patch 就会写到开发库。
"""
import hashlib
import json

import pytest
from chromadb.api.types import EmbeddingFunction

from funcation import memory_rag
from funcation import memory_timeline as mt
from funcation.memory_center import MemoryCenter, create_default_rag

USER = 1


def _bodies(items):
    """剥掉日期前缀只比正文。2026-11-09 起 `add_long_memory` 会写入
    「（YYYY-MM-DD）」前缀，但这些测试关心的是**真源里有没有这条内容**，
    不是它的格式。格式由 `test_memory_timeline.py` 单独钉住。

    ⚠️ 别在这里直接断言完整文本相等 —— 那会把"有没有日期"和
    "数据有没有落到真源"两件事绑在一起。
    """
    return [mt.strip_stamp(x) for x in items]
CHAR = "linwan"

# ⚠️ 本文件要跑**真实**的 chromadb，但 `conftest.disable_rag` 是 **session 级**的：
# 只要本次会话里有别的测试用了 `client`，它就会把 `memory_rag` 的读写全 mock 成空，
# 于是本文件的测试会"单独跑过、全量跑挂"（踩过）。
#
# 修法：在**模块导入时**抓一份真函数 —— 那时 pytest 还在收集阶段，
# fixture 都没执行，`memory_rag` 还是原装的。fixture 里再把它们还原回去。
_REAL_RAG = {
    name: getattr(memory_rag, name)
    for name in (
        "list_all_memories",
        "add_memory",
        "upsert_memory",
        "update_memory",
        "delete_memory",
        "rebuild_collection_from_items",
        "purge_collection",
    )
}


@pytest.fixture
def mc(tmp_path, monkeypatch):
    """真实 chromadb（tmp 目录）+ 隔离的 data/memories"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "memories" / str(USER)).mkdir(parents=True)
    (tmp_path / "data" / "characters").mkdir(parents=True, exist_ok=True)

    # 还原可能被 disable_rag 换掉的实现（见上面的说明）
    for name, fn in _REAL_RAG.items():
        monkeypatch.setattr(memory_rag, name, fn)

    # ⚠️ 用**真 chromadb**，但 embedding 换成本地确定性向量。
    # 这些测试要验的是"真源在 JSON、向量库只是索引"，跟嵌入模型质量无关；
    # 而 FastEmbed 每次构造都会访问 huggingface.co 查元数据，网络一 502
    # 整个文件会卡到超时（2026-11-09 实测）。换成本地 hash 向量后：
    # 真 sqlite / 真 collection / 真增删查全保留，只是不再依赖外网。
    class _HashEmbedding(EmbeddingFunction):
        def __call__(self, input):
            out = []
            for text in input:
                digest = hashlib.sha256(str(text).encode("utf-8")).digest()
                out.append([b / 255.0 for b in digest[:32]])
            return out

    monkeypatch.setattr(
        memory_rag, "get_embedding_function",
        lambda *a, **k: _HashEmbedding(),
    )

    chroma_dir = tmp_path / "data" / "chroma"
    monkeypatch.setattr(memory_rag, "PERSIST_DIR", str(chroma_dir))
    monkeypatch.setattr(memory_rag, "_chroma_persist_dir", None)
    memory_rag.release_client()      # 丢掉可能指向别的目录的旧 client
    yield MemoryCenter()
    memory_rag.release_client()


def _quarantine_index(monkeypatch, tmp_path, tag="1"):
    """模拟"向量库被隔离"：把索引换到一个**全新的空目录**。

    语义上等价于"索引没了"（应用看到的就是空索引），
    而且不用跟 Windows 的文件锁搏斗 —— chromadb 持有 sqlite 句柄，
    直接 rename 旧目录会 `PermissionError: WinError 5`（`release_client()`
    也放不掉那个句柄）。真实场景里隔离正是"旧目录被 move 走、应用新建一个空的"。
    """
    memory_rag.release_client()
    empty = tmp_path / "data" / f"chroma_after_{tag}"
    monkeypatch.setattr(memory_rag, "PERSIST_DIR", str(empty))
    monkeypatch.setattr(memory_rag, "_chroma_persist_dir", None)
    return empty


# ============================================================
# 核心不变量：向量库没了，数据还在
# ============================================================

def test_data_survives_vector_db_loss(mc, tmp_path, monkeypatch):
    """**这是本次要买的东西。**

    写三条数据 → 把索引换成一个空目录（模拟被隔离）→ 重新加载 → 内容必须一字不差。
    """
    mc.add_long_memory(USER, CHAR, "用户喜欢雨天")
    mc.add_event(USER, CHAR, "一起去了图书馆")
    mc.add_chat_summary(USER, CHAR, "用户: 今天好累")
    mc.add_chat_summary(USER, CHAR, "AI: 那早点休息")

    before_long = mc.get_long_memories(USER, CHAR)
    before_events = mc.get_events(USER, CHAR)
    before_summary = mc.get_chat_summary(USER, CHAR)
    assert before_long and before_events and before_summary   # 先确认真的写进去了

    _quarantine_index(monkeypatch, tmp_path)

    # 关键断言：向量库没了，数据一条不少
    assert mc.get_long_memories(USER, CHAR) == before_long
    assert mc.get_events(USER, CHAR) == before_events
    assert mc.get_chat_summary(USER, CHAR) == before_summary

    mem = mc.load_memory(USER, CHAR)
    assert mem["long_memory"] == before_long
    assert mem["events"] == before_events
    assert mem["chat_summary"] == before_summary


def test_rag_json_is_written_at_all(mc, tmp_path):
    """真源文件确实落在 .rag.json 里（不是只写进了向量库）"""
    mc.add_long_memory(USER, CHAR, "记住这件事")
    path = tmp_path / "data" / "memories" / str(USER) / f"{CHAR}.rag.json"
    assert path.is_file()
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data["long_memory"]
    assert _bodies(items) == ["记住这件事"]
    # 日期前缀本身也要钉住，否则"加了前缀"这件事没人守
    assert mt.date_of(items[0]), "长期记忆应该带日期前缀"


# ============================================================
# 索引可重建
# ============================================================

def test_index_can_be_rebuilt_from_source(mc, tmp_path, monkeypatch):
    """向量库是索引 —— 删掉能按真源重建"""
    mc.add_long_memory(USER, CHAR, "记忆甲")
    mc.add_long_memory(USER, CHAR, "记忆乙")
    mc.add_event(USER, CHAR, "事件甲")

    _quarantine_index(monkeypatch, tmp_path)
    assert memory_rag.list_all_memories(USER, CHAR, "long_memory") == []   # 索引确实空了

    mc._index_to_rag(USER, CHAR, "long_memory")
    mc._index_to_rag(USER, CHAR, "events")

    texts = {it["text"] for it in memory_rag.list_all_memories(USER, CHAR, "long_memory")}
    assert set(_bodies(texts)) == {"记忆甲", "记忆乙"}
    assert len(memory_rag.list_all_memories(USER, CHAR, "events")) == 1


def test_rebuild_is_idempotent(mc):
    """重复重建不产生重复条目（先 purge 再全量写）"""
    mc.add_long_memory(USER, CHAR, "只此一条")
    mc._index_to_rag(USER, CHAR, "long_memory")
    mc._index_to_rag(USER, CHAR, "long_memory")
    items = memory_rag.list_all_memories(USER, CHAR, "long_memory")
    assert len(items) == 1


# ============================================================
# 反向迁移（把存量从向量库捞回真源）
# ============================================================

def test_migrate_from_chroma_pulls_legacy_data(mc, tmp_path):
    """模拟"历史状态"：数据只在向量库里，`.rag.json` 不存在 → 首次 load 应捞回来"""
    memory_rag.add_memory(USER, CHAR, "long_memory", "只存在向量库里的老记忆")
    memory_rag.add_memory(USER, CHAR, "events", "老事件", metadata={"time": "2026-01-01 10:00"})
    assert not (tmp_path / "data" / "memories" / str(USER) / f"{CHAR}.rag.json").exists()

    mem = mc.load_memory(USER, CHAR)

    assert "只存在向量库里的老记忆" in mem["long_memory"]
    assert any(e["event"] == "老事件" for e in mem["events"])
    path = tmp_path / "data" / "memories" / str(USER) / f"{CHAR}.rag.json"
    assert path.is_file(), "迁移后应写出真源文件"


def test_migrate_is_idempotent_and_wont_overwrite(mc, tmp_path):
    """迁移幂等；真源已存在时**不被向量库覆盖**（真源优先）"""
    mc.add_long_memory(USER, CHAR, "真源里的新内容")
    # 向量库里塞一条不同的（模拟索引过期）
    memory_rag.add_memory(USER, CHAR, "long_memory", "索引里的旧内容")

    mc.load_memory(USER, CHAR)
    assert _bodies(mc.get_long_memories(USER, CHAR)) == ["真源里的新内容"]

    # 再 load 一次也不变
    mc.load_memory(USER, CHAR)
    assert _bodies(mc.get_long_memories(USER, CHAR)) == ["真源里的新内容"]


def test_migrate_never_writes_empty_source_when_index_unreadable(mc, tmp_path, monkeypatch):
    """向量库读不到时**绝不能写出一个空真源** —— 那等于用一次读取失败抹掉数据"""
    def _boom(*a, **k):
        raise RuntimeError("向量库挂了")

    monkeypatch.setattr(memory_rag, "list_all_memories", _boom)
    path = tmp_path / "data" / "memories" / str(USER) / f"{CHAR}.rag.json"

    mc.load_memory(USER, CHAR)      # 不该抛

    assert not path.exists(), "读不到索引时不该凭空写出空真源"


# ============================================================
# 健壮性
# ============================================================

def test_index_failure_does_not_break_write(mc, monkeypatch):
    """索引写失败不影响数据落盘（真源已经写好了，索引坏了可以重建）"""
    def _boom(*a, **k):
        raise RuntimeError("索引炸了")

    monkeypatch.setattr(memory_rag, "rebuild_collection_from_items", _boom)
    mc.add_long_memory(USER, CHAR, "索引坏了也要存下来")   # 不该抛
    assert _bodies(mc.get_long_memories(USER, CHAR)) == ["索引坏了也要存下来"]


def test_load_rag_tolerates_corrupt_file(mc, tmp_path):
    """真源文件坏了 → 返回空结构，不抛（人工介入是另一回事）"""
    path = tmp_path / "data" / "memories" / str(USER) / f"{CHAR}.rag.json"
    path.write_text("{ 这不是合法 json", encoding="utf-8")
    rag = mc._load_rag(USER, CHAR)
    assert rag == create_default_rag()


def test_load_rag_tolerates_wrong_shape(mc, tmp_path):
    """内容不是 dict（比如被写成了数组）→ 也不抛"""
    path = tmp_path / "data" / "memories" / str(USER) / f"{CHAR}.rag.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    assert mc._load_rag(USER, CHAR) == create_default_rag()


# ============================================================
# 行为兼容（不能因为改真源就把原有语义改了）
# ============================================================

def test_long_memory_dedupes(mc):
    """长期记忆去重（原有行为）"""
    mc.add_long_memory(USER, CHAR, "同一件事")
    mc.add_long_memory(USER, CHAR, "同一件事")
    assert _bodies(mc.get_long_memories(USER, CHAR)) == ["同一件事"]


def test_chat_summary_keeps_last_10(mc):
    """聊天摘要只留最近 10 条（原有行为）"""
    for i in range(15):
        mc.add_chat_summary(USER, CHAR, f"第 {i} 条")
    kept = mc.get_chat_summary(USER, CHAR)
    assert len(kept) == 10
    assert kept[-1] == "第 14 条"
    assert kept[0] == "第 5 条"


def test_events_read_caps_at_50(mc):
    """事件读取最多 50 条（原有行为）"""
    for i in range(60):
        mc.add_event(USER, CHAR, f"事件 {i}")
    assert len(mc.get_events(USER, CHAR)) == 50


def test_update_long_memory(mc):
    mc.add_long_memory(USER, CHAR, "旧说法")
    mc.update_long_memory(USER, CHAR, "旧说法", "新说法")
    assert _bodies(mc.get_long_memories(USER, CHAR)) == ["新说法"]


def test_save_memory_still_excludes_rag_fields(mc, tmp_path):
    """主 JSON 里不该再出现这三个字段（它们的家在 .rag.json）"""
    data = mc.load_memory(USER, CHAR)
    data["long_memory"] = ["不该进主 JSON"]
    mc.save_memory(USER, CHAR, data)

    main = json.loads(
        (tmp_path / "data" / "memories" / str(USER) / f"{CHAR}.json").read_text(encoding="utf-8")
    )
    for field in ("long_memory", "events", "chat_summary"):
        assert field not in main
