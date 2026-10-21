"""长期记忆的**编辑/删除**必须落在真源（`.rag.json`）上。

背景（2026-10-21 修）：`DELETE /long-memory` 原本改主 JSON 的 `long_memory`，
而真源在 `.rag.json`（`get_long_memories` 也从那里读）。真实数据里主 JSON
该字段已是 `None`，于是**用户点删除永远收到"未找到该记忆"**。

这里钉住三件事：
1. 删除改的是**真源**
2. 删完必须**重建向量索引**（否则检索还命中已删内容）
3. 找不到 → **404**（调用方能区分"删成功"和"没这条"）
"""
from unittest.mock import patch

import pytest

from funcation.memory_center import MemoryCenter


@pytest.fixture
def mc(tmp_path, monkeypatch):
    """隔离的 MemoryCenter（索引重建被 patch 掉，避免动真实 chroma）"""
    monkeypatch.setattr(MemoryCenter, "__init__", lambda self, *a, **k: None)
    obj = MemoryCenter()

    rag_store = {"long_memory": ["我喜欢吃辣", "我在准备考试", "我喜欢吃辣"]}

    def fake_load_rag(user_id, character_id):
        return dict(rag_store)

    def fake_save_rag(user_id, character_id, rag):
        rag_store.clear()
        rag_store.update(rag)

    monkeypatch.setattr(obj, "_load_rag", fake_load_rag)
    monkeypatch.setattr(obj, "_save_rag", fake_save_rag)
    monkeypatch.setattr(obj, "_index_to_rag", lambda *a, **k: None)
    return obj, rag_store


def test_delete_removes_from_real_source(mc):
    """**删除改的是真源**（不是主 JSON）"""
    obj, store = mc
    ok = obj.delete_long_memory(1, "linwan", "我在准备考试")
    assert ok is True
    assert store["long_memory"] == ["我喜欢吃辣", "我喜欢吃辣"]


def test_delete_returns_false_when_absent(mc):
    """真源里没有 → False（不是抛异常）"""
    obj, store = mc
    assert obj.delete_long_memory(1, "linwan", "不存在的记忆") is False
    assert len(store["long_memory"]) == 3  # 一条都没动


def test_delete_removes_all_duplicates(mc):
    """文本完全相同的多条一起删（和 update 语义一致）"""
    obj, store = mc
    assert obj.delete_long_memory(1, "linwan", "我喜欢吃辣") is True
    assert store["long_memory"] == ["我在准备考试"]


def test_delete_rebuilds_rag_index(mc):
    """**删完必须重建向量索引** —— 不重建的话检索还命中已删内容"""
    obj, _ = mc
    with patch.object(obj, "_index_to_rag") as rebuild:
        obj.delete_long_memory(1, "linwan", "我在准备考试")
    rebuild.assert_called_once_with(1, "linwan", "long_memory")


def test_delete_does_not_rebuild_when_nothing_removed(mc):
    """没删掉东西就不该重建（省一次全量重索引）"""
    obj, _ = mc
    with patch.object(obj, "_index_to_rag") as rebuild:
        obj.delete_long_memory(1, "linwan", "不存在")
    rebuild.assert_not_called()


# ── 端点契约（不走真实 DB，用 TestClient + 假 mc）────────────────

def test_delete_endpoint_returns_404_when_absent():
    from fastapi.testclient import TestClient

    from api import api as api_mod
    from funcation.auth import require_approved

    class FakeUser:
        id = 1
        role = "user"
        status = "approved"

    class FakeMC:
        def get_user_current_character_id(self, uid):
            return "linwan"

        def delete_long_memory(self, uid, cid, text):
            return False        # 模拟"真源里没有"

        def get_long_memories(self, uid, cid):
            return ["a"]

    orig_mc = api_mod.mc
    api_mod.mc = FakeMC()
    # 绕过认证，直接测端点自己的逻辑（404 vs 200）
    api_mod.app.dependency_overrides[require_approved] = lambda: FakeUser()
    try:
        client = TestClient(api_mod.app)
        # 这个版本的 TestClient.delete() 连 content= 都不支持，用通用 request()
        resp = client.request(
            "DELETE",
            "/long-memory",
            content='{"memory": "不存在"}',
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 404
        assert "未找到" in resp.json()["detail"]
    finally:
        api_mod.mc = orig_mc
        api_mod.app.dependency_overrides.pop(require_approved, None)
