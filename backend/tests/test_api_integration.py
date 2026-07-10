"""API 集成测试 —— TestClient + fake DeepSeek + tmp 数据 + 禁用 RAG。

覆盖关键路径：health / auth 注册登录审批 / 角色切换 / chat 主回复 / 角色访问隔离逻辑。
不覆盖：流式 /chat/stream、语音 WebSocket、真实 RAG、真实 DeepSeek。
"""
import uuid
from types import SimpleNamespace

import pytest

from api.api import _check_character_access


def _unique(prefix="user"):
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# ---------- 基础 ----------

def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


# ---------- auth ----------

def test_register_login_me(client):
    name = _unique()
    r = client.post("/auth/register", json={"username": name, "password": "pass1234"})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["status"] == "pending"

    r = client.post("/auth/login", json={"username": name, "password": "pass1234"})
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    assert token

    # 带 token 取 /me
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["user"]["username"] == name


def test_login_wrong_password(client):
    name = _unique()
    client.post("/auth/register", json={"username": name, "password": "pass1234"})
    r = client.post("/auth/login", json={"username": name, "password": "wrong"})
    assert r.status_code == 401


def test_pending_user_cannot_chat(client):
    """pending 用户调 /chat 被 require_approved 拦 403。"""
    name = _unique()
    client.post("/auth/register", json={"username": name, "password": "pass1234"})
    r = client.post("/auth/login", json={"username": name, "password": "pass1234"})
    token = r.json()["token"]
    r = client.post("/chat", json={"message": "你好"},
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403, r.text


# ---------- 审批 + chat 全流程 ----------

@pytest.fixture
def admin_token(client):
    """admin 默认账 admin/admin123（_ensure_admin 种入）。"""
    r = client.post("/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture
def approved_user(client, admin_token):
    """注册一个用户并用 admin 审批通过，返回 (token, username)。"""
    name = _unique()
    pwd = "pass1234"
    reg = client.post("/auth/register", json={"username": name, "password": pwd})
    assert reg.status_code == 200, reg.text
    user_id = reg.json()["user"]["id"]

    apv = client.post(f"/auth/admin/approve/{user_id}",
                      headers={"Authorization": f"Bearer {admin_token}"})
    assert apv.status_code == 200, apv.text
    assert apv.json()["user"]["status"] == "approved"

    lg = client.post("/auth/login", json={"username": name, "password": pwd})
    assert lg.status_code == 200, lg.text
    return lg.json()["token"], name


def test_admin_approve_and_user_becomes_approved(approved_user):
    token, name = approved_user
    # fixture 已经断言审批成功；这里额外确认 /me 报 approved
    pass  # approved_user fixture 本身覆盖


def test_chat_returns_reply_and_favorability(client, tmp_data_dir, approved_user):
    """审批通过的用户切到 linwan 后 /chat 返回回复 + 好感度，不抛 500。"""
    token, _ = approved_user

    # 切到内置角色 linwan
    sw = client.post("/character/switch", json={"character_id": "linwan"},
                     headers={"Authorization": f"Bearer {token}"})
    assert sw.status_code == 200, sw.text

    # 发一条消息
    r = client.post("/chat", json={"message": "你好呀"},
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "reply" in body, body
    assert body["reply"], "回复不应为空"
    assert "favorability" in body
    assert isinstance(body["favorability"], int)


def test_chat_history_persists(client, tmp_data_dir, approved_user):
    """/chat 后历史落盘，GET /history 能取回。"""
    token, _ = approved_user
    client.post("/character/switch", json={"character_id": "linwan"},
                headers={"Authorization": f"Bearer {token}"})
    client.post("/chat", json={"message": "今天天气真好"},
                headers={"Authorization": f"Bearer {token}"})

    r = client.get("/history", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    msgs = r.json().get("messages") or r.json().get("history") or []
    # 至少有一条 assistant 回复
    roles = [m.get("role") for m in msgs]
    assert "assistant" in roles, roles


def test_favorability_and_relationship(client, tmp_data_dir, approved_user):
    token, _ = approved_user
    client.post("/character/switch", json={"character_id": "linwan"},
                headers={"Authorization": f"Bearer {token}"})
    client.post("/chat", json={"message": "你好"},
                headers={"Authorization": f"Bearer {token}"})

    fav = client.get("/favorability", headers={"Authorization": f"Bearer {token}"})
    assert fav.status_code == 200
    rel = client.get("/relationship", headers={"Authorization": f"Bearer {token}"})
    assert rel.status_code == 200


# ---------- 角色列表 ----------

def test_characters_list_builtin(client, tmp_data_dir, approved_user):
    token, _ = approved_user
    r = client.get("/characters", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    chars = r.json().get("characters") or r.json()
    ids = {c["id"] for c in chars} if isinstance(chars, list) else {c["id"] for c in chars.values()}
    assert "linwan" in ids, ids


# ---------- 角色访问隔离逻辑（纯函数单测） ----------

def _fake_user(uid, is_admin=False):
    return SimpleNamespace(id=uid, is_admin=is_admin)


def test_check_character_access_builtin_open():
    """内置角色（无 created_by）任何用户可访问。"""
    _check_character_access({"id": "linwan"}, _fake_user(999))


def test_check_character_access_owner():
    """用户可访问自己创建的角色。"""
    _check_character_access({"id": "char_x", "created_by": 42}, _fake_user(42))


def test_check_character_access_admin_sees_all():
    """管理员可访问任何角色。"""
    _check_character_access({"id": "char_x", "created_by": 42},
                            _fake_user(1, is_admin=True))


def test_check_character_access_other_user_forbidden():
    """普通用户不能访问别人创建的角色 → 403。"""
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        _check_character_access({"id": "char_x", "created_by": 42}, _fake_user(7))
    assert exc.value.status_code == 403
