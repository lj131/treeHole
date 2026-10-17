"""`fair_top_k` —— 跨集合检索的公平性。

核心问题：原来是 `sort(...)[:top_k]`，文档多的集合垄断席位。
实测 `story` 有 10+ 条、distance 都更小时，会把 long_memory 整个挤出 top_k。
"""
import pytest

from funcation import memory_rag


def it(collection, score, text=None):
    return {"collection": collection, "score": score, "text": text or f"{collection}-{score}"}


def test_big_collection_does_not_monopolize():
    """**核心断言**：story 10 条全比 long_memory 近，long_memory 仍必须出现"""
    items = [it("story", 0.5 + i * 0.01) for i in range(10)]
    items += [it("long_memory", 1.9), it("long_memory", 1.95)]

    picked = memory_rag.fair_top_k(items, top_k=10, min_per_collection=2)

    assert len(picked) == 10
    by_coll = {}
    for p in picked:
        by_coll[p["collection"]] = by_coll.get(p["collection"], 0) + 1
    # long_memory 保底 2 条，没有被 story 挤掉
    assert by_coll.get("long_memory") == 2


def test_every_collection_gets_its_floor():
    """三个集合都必须有**保底**条数（不是恰好保底 —— 补齐阶段会继续加 story）"""
    items = (
        [it("story", 0.5 + i * 0.01) for i in range(8)]
        + [it("long_memory", 1.8)]
        + [it("events", 1.85)]
    )
    picked = memory_rag.fair_top_k(items, top_k=6, min_per_collection=2)
    by_coll = {}
    for p in picked:
        by_coll[p["collection"]] = by_coll.get(p["collection"], 0) + 1
    # 小集合拿到全部可用条数（保底 2，但它们各只有 1 条）
    assert by_coll["long_memory"] == 1
    assert by_coll["events"] == 1
    # 大集合：保底 2 + 补齐 2 = 4（补齐是按全局顺序的，story 分数最低自然占满剩余碗位）
    assert by_coll["story"] == 4


def test_result_sorted_by_score():
    """**返回仍是全局相关性顺序**（保底+补齐会打乱，最后必须重新排）"""
    items = [it("story", 0.5 + i * 0.01) for i in range(10)] + [
        it("long_memory", 1.9),
        it("long_memory", 1.95),
    ]
    picked = memory_rag.fair_top_k(items, top_k=10, min_per_collection=2)
    scores = [p["score"] for p in picked]
    assert scores == sorted(scores)


def test_respects_top_k():
    items = [it("story", 0.5 + i * 0.01) for i in range(10)] + [
        it("long_memory", 1.9),
        it("long_memory", 1.95),
    ]
    assert len(memory_rag.fair_top_k(items, top_k=3, min_per_collection=2)) == 3
    assert len(memory_rag.fair_top_k(items, top_k=100, min_per_collection=2)) == len(items)


def test_floor_shrinks_when_top_k_small():
    """top_k 太小时保底会收敛，不会全被保底占满"""
    items = (
        [it("story", 0.5 + i * 0.01) for i in range(5)]
        + [it("long_memory", 1.9)]
        + [it("events", 1.95)]
        + [it("profile", 1.99)]
    )
    # top_k=3, 4 个集合 → floor 收敛到 max(1, min(2, 3//4)) = 1
    picked = memory_rag.fair_top_k(items, top_k=3, min_per_collection=2)
    assert len(picked) == 3
    # floor=1 生效：每个集合各拿到 1 条（而不是 story 独占 3 席）
    by_coll = {}
    for p in picked:
        by_coll[p["collection"]] = by_coll.get(p["collection"], 0) + 1
    assert by_coll["story"] == 1
    assert by_coll["long_memory"] == 1
    assert by_coll["events"] == 1


def test_single_collection_behaves_like_plain_top_k():
    """只有一个集合时退化成普通 top_k（公平性无从谈起）"""
    items = [it("long_memory", 0.5 + i * 0.1) for i in range(10)]
    picked = memory_rag.fair_top_k(items, top_k=4, min_per_collection=2)
    assert len(picked) == 4
    assert [p["score"] for p in picked] == sorted(p["score"] for p in picked)


def test_empty_and_bad_input():
    assert memory_rag.fair_top_k([], top_k=10) == []
    assert memory_rag.fair_top_k(None, top_k=10) == []
    assert memory_rag.fair_top_k([it("story", 0.5)], top_k=0) == []


def test_missing_score_does_not_crash():
    """缺 score 的条目排最后，但不该让整体崩"""
    items = [
        {"collection": "story", "text": "no score"},
        it("long_memory", 0.5, "has score"),
    ]
    picked = memory_rag.fair_top_k(items, top_k=2, min_per_collection=1)
    assert len(picked) == 2
    assert picked[0]["text"] == "has score"


def test_no_duplicates():
    """保底 + 补齐不能选重"""
    items = [it("story", 0.5 + i * 0.01) for i in range(10)] + [
        it("long_memory", 1.9),
        it("events", 1.95),
    ]
    picked = memory_rag.fair_top_k(items, top_k=10, min_per_collection=2)
    ids = [id(p) for p in picked]
    assert len(ids) == len(set(ids))


def test_all_items_kept_when_top_k_large():
    """top_k 大于候选数 → 全部保留（不丢数据）"""
    items = [it("story", 0.5), it("long_memory", 0.6)]
    picked = memory_rag.fair_top_k(items, top_k=10, min_per_collection=2)
    assert len(picked) == 2


# ── 世界过滤：哪些集合能按 world_id 过滤 ──────────────────────

def test_only_world_scoped_collections_are_filtered():
    """**只有三个集合的文档带 world_id 元数据**，其余不该被 world_id 过滤"""
    assert memory_rag.applies_world_filter("profile") is True
    assert memory_rag.applies_world_filter("story") is True
    assert memory_rag.applies_world_filter("relationship") is True

    assert memory_rag.applies_world_filter("long_memory") is False
    assert memory_rag.applies_world_filter("events") is False
    assert memory_rag.applies_world_filter("chat_summary") is False


def test_unknown_collection_not_filtered():
    """未知集合默认不过滤（宁可多查，不可漏数据）"""
    assert memory_rag.applies_world_filter("brand_new") is False
    assert memory_rag.applies_world_filter("") is False
    assert memory_rag.applies_world_filter(None) is False
