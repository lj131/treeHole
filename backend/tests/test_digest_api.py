"""世界日报接口：聚合 + 权限 + 空态。"""
import pytest


def test_requires_auth(client, tmp_data_dir):
    """未登录不能看（数据是 per-user 的）"""
    r = client.get("/world/digest")
    assert r.status_code == 401


def test_empty_world_returns_200_and_empty_entries(client, tmp_data_dir, admin_headers):
    """**空数据要 200 + 空数组**（前端渲染空态，不是错误）"""
    r = client.get("/world/digest", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["entries"] == []
    assert body["total"] == 0
    assert "安静" in body["summary"]
    assert body["range"]["days"] == 7


def test_days_param_respected_and_clamped(client, tmp_data_dir, admin_headers):
    h = admin_headers
    assert client.get("/world/digest?days=7", headers=h).json()["range"]["days"] == 7
    # clamp 到 [1, MAX_DAYS]
    assert client.get("/world/digest?days=99999", headers=h).json()["range"]["days"] == 30
    assert client.get("/world/digest?days=0", headers=h).json()["range"]["days"] == 1


def test_response_shape(client, tmp_data_dir, admin_headers):
    body = client.get("/world/digest", headers=admin_headers).json()
    for key in ("generated_at", "range", "entries", "counts", "summary", "total"):
        assert key in body, f"缺字段 {key}"
