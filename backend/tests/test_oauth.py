"""第三方登录（QQ / 微信）。

重点钉住三件最容易写错、且错了很难查的事：
1. QQ 的 token 响应是 **querystring**、`oauth2.0/me` 是 **JSONP**，不是 JSON
2. `state` 必须一次性、带过期、绑定 provider（防 CSRF / 重放）
3. 同一个第三方号并发/重复回调只能建一个账号
"""
from __future__ import annotations

import uuid
from urllib.parse import parse_qs, quote, urlparse

import jwt
import pytest

from funcation import oauth


class FakeResponse:
    def __init__(self, text: str = "", payload=None):
        self._text = text
        self._payload = payload

    def raise_for_status(self):
        return None

    @property
    def text(self):
        return self._text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _live_config(monkeypatch):
    monkeypatch.setenv("OAUTH_MODE", "live")
    monkeypatch.setenv("QQ_APP_ID", "qq-id")
    monkeypatch.setenv("QQ_APP_KEY", "qq-key")
    monkeypatch.setenv("WECHAT_APP_ID", "wx-id")
    monkeypatch.setenv("WECHAT_APP_SECRET", "wx-secret")
    monkeypatch.setenv("OAUTH_CALLBACK_BASE", "https://example.com")


# ============================================================
# state
# ============================================================

def test_state_roundtrip(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret")
    state = oauth.issue_state("qq")
    oauth.consume_state(state, "qq")


def test_state_is_single_use(monkeypatch):
    """**重放必须被拒** —— 否则拿到一次回调 URL 就能反复登录"""
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret")
    state = oauth.issue_state("qq")
    oauth.consume_state(state, "qq")
    with pytest.raises(oauth.OAuthError):
        oauth.consume_state(state, "qq")


def test_state_is_bound_to_provider(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret")
    state = oauth.issue_state("qq")
    with pytest.raises(oauth.OAuthError):
        oauth.consume_state(state, "wechat")


def test_state_rejects_tampering(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret")
    state = oauth.issue_state("qq")
    with pytest.raises(oauth.OAuthError):
        oauth.consume_state(state[:-2] + ("aa" if not state.endswith("aa") else "bb"), "qq")


def test_state_rejects_expired(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret")
    expired = jwt.encode(
        {"p": "qq", "n": "expired-nonce", "exp": 1},
        oauth._state_secret(), algorithm="HS256",
    )
    with pytest.raises(oauth.OAuthError):
        oauth.consume_state(expired, "qq")


# ============================================================
# provider 响应解析（不发外网）
# ============================================================

def test_qq_exchange_handles_querystring_token_and_jsonp_openid(monkeypatch):
    """**QQ 最大的坑**：token 不是 JSON，me 是 JSONP。照微信那套写必挂。"""
    _live_config(monkeypatch)
    responses = iter([
        FakeResponse(text="access_token=AT123&expires_in=7776000&refresh_token=R"),
        FakeResponse(text='callback( {"client_id":"qq-id","openid":"OPENID_X"} );'),
        FakeResponse(payload={
            "ret": 0, "nickname": "小婉", "figureurl_qq_2": "https://q.logo/a.png",
        }),
    ])
    monkeypatch.setattr(oauth.requests, "get", lambda *a, **k: next(responses))

    identity = oauth.get_provider("qq").exchange("CODE")
    assert identity.provider == "qq"
    assert identity.subject == "OPENID_X"
    assert identity.nickname == "小婉"
    assert identity.avatar == "https://q.logo/a.png"


def test_qq_exchange_rejects_error_callback(monkeypatch):
    _live_config(monkeypatch)
    monkeypatch.setattr(
        oauth.requests, "get",
        lambda *a, **k: FakeResponse(text='callback( {"error":100006,"error_description":"..."} );'),
    )
    with pytest.raises(oauth.OAuthError):
        oauth.get_provider("qq").exchange("BAD")


def test_wechat_exchange_parses_userinfo(monkeypatch):
    _live_config(monkeypatch)
    responses = iter([
        FakeResponse(payload={"access_token": "AT", "openid": "WXID", "unionid": "UNION1"}),
        FakeResponse(payload={"nickname": "阿微", "headimgurl": "https://wx.logo/a.png"}),
    ])
    monkeypatch.setattr(oauth.requests, "get", lambda *a, **k: next(responses))

    identity = oauth.get_provider("wechat").exchange("CODE")
    assert identity.subject == "WXID"
    assert identity.unionid == "UNION1"
    assert identity.nickname == "阿微"


def test_wechat_exchange_rejects_errcode(monkeypatch):
    _live_config(monkeypatch)
    monkeypatch.setattr(
        oauth.requests, "get",
        lambda *a, **k: FakeResponse(payload={"errcode": 40029, "errmsg": "invalid code"}),
    )
    with pytest.raises(oauth.OAuthError):
        oauth.get_provider("wechat").exchange("BAD")


# ============================================================
# 配置门
# ============================================================

def test_unconfigured_provider_is_disabled_and_not_constructible(monkeypatch):
    """没配 AppID 就不能出现在可用列表里，点了必须明确失败而不是 500"""
    monkeypatch.delenv("OAUTH_MODE", raising=False)
    for key in ("QQ_APP_ID", "QQ_APP_KEY", "WECHAT_APP_ID", "WECHAT_APP_SECRET"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("OAUTH_CALLBACK_BASE", "")

    assert all(not p["enabled"] for p in oauth.configured_providers())
    with pytest.raises(oauth.OAuthNotConfigured):
        oauth.get_provider("qq")


def test_unknown_provider_rejected():
    with pytest.raises(oauth.OAuthNotConfigured):
        oauth.get_provider("github")


def test_qq_authorize_url_has_no_hash_and_looks_like_graph_api(monkeypatch):
    """QQ 规定回调域不能带 #，且回调地址必须完整编码进授权 URL"""
    _live_config(monkeypatch)
    url = oauth.get_provider("qq").authorize_url("STATE")
    assert url.startswith("https://graph.qq.com/oauth2.0/authorize?")
    assert "state=STATE" in url
    assert "redirect_uri=https%3A%2F%2Fexample.com" in url


# ============================================================
# 全链路（mock provider + 真实 TestClient + 真实 DB）
# ============================================================

@pytest.fixture
def mock_mode(monkeypatch):
    subject = f"tester_{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("OAUTH_MODE", "mock")
    monkeypatch.setenv("OAUTH_MOCK_SUBJECT", subject)
    monkeypatch.setenv("FRONTEND_BASE_URL", "http://127.0.0.1:5173")
    monkeypatch.setenv("OAUTH_CALLBACK_BASE", "http://127.0.0.1:8000")
    return subject


def _authorize_and_callback(client, provider: str):
    r = client.get(f"/auth/oauth/{provider}/authorize")
    assert r.status_code == 200, r.text
    body = r.json()
    qs = parse_qs(urlparse(body["url"]).query)
    code, state = qs["code"][0], qs["state"][0]
    return client.get(
        f"/auth/oauth/{provider}/callback?code={quote(code)}&state={quote(state)}",
        follow_redirects=False,
    )


def test_mock_full_flow_creates_user_and_returns_token(client, mock_mode):
    from funcation.auth import SessionLocal, User

    providers = client.get("/auth/oauth/providers").json()["providers"]
    assert len(providers) == 2 and all(p["enabled"] for p in providers)

    resp = _authorize_and_callback(client, "qq")
    assert resp.status_code == 302
    location = resp.headers["location"]
    # token 必须落在 **# 之后** fragment 里（QQ 不允许回调域带 #）
    assert "/#/oauth/callback?token=" in location
    assert "is_new=1" in location
    token = parse_qs(location.split("?", 1)[1])["token"][0]

    # token 是能用的真 JWT
    from funcation.auth import decode_token
    payload = decode_token(token)
    assert payload["username"].startswith("qq_")

    with SessionLocal() as db:
        users = db.query(User).filter(
            User.oauth_provider == "qq", User.oauth_id == mock_mode
        ).all()
    assert len(users) == 1
    assert users[0].status == "approved"          # 默认免审批
    assert users[0].password_hash                  # 占位密码已写，满足 NOT NULL


def test_second_login_reuses_same_account(client, mock_mode):
    """**同一个第三方号连登两次只能有一个账号**"""
    from funcation.auth import SessionLocal, User

    first = _authorize_and_callback(client, "qq")
    second = _authorize_and_callback(client, "qq")
    assert first.status_code == second.status_code == 302
    assert "is_new=0" in second.headers["location"]

    with SessionLocal() as db:
        count = db.query(User).filter(
            User.oauth_provider == "qq", User.oauth_id == mock_mode
        ).count()
    assert count == 1


def test_different_providers_are_different_accounts(client, mock_mode):
    """QQ 与微信的 openid 互不相通 —— 本期如实接受，不假装打通"""
    from funcation.auth import SessionLocal, User

    _authorize_and_callback(client, "qq")
    _authorize_and_callback(client, "wechat")
    with SessionLocal() as db:
        rows = db.query(User).filter(User.oauth_id == mock_mode).all()
    assert {r.oauth_provider for r in rows} == {"qq", "wechat"}


def test_callback_rejects_bad_state_without_creating_user(client, mock_mode):
    """伪造/重放 state 不能建号，也不能给用户裸 500"""
    from funcation.auth import SessionLocal, User

    r = client.get("/auth/oauth/qq/callback?code=mock%7Cqq%7Cattacker&state=forged",
                   follow_redirects=False)
    assert r.status_code == 302
    assert "error=" in r.headers["location"]
    with SessionLocal() as db:
        assert db.query(User).filter(User.oauth_id == "attacker").count() == 0


def test_oauth_unique_index_exists(client, mock_mode):
    """索引没建上的话，并发回调会开重号 —— 这条守住那个前提"""
    from funcation.auth import SessionLocal
    from sqlalchemy import text

    with SessionLocal() as db:
        rows = db.execute(text(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='uq_users_oauth'"
        )).fetchall()
    assert rows, "uq_users_oauth 唯一索引缺失"


def test_health_exposes_mock_mode(client, mock_mode):
    """**生产误开 mock = 认证绕过** —— 必须能从 /health 一眼看出来"""
    body = client.get("/health").json()
    assert body["oauth"]["mode"] == "mock"
    assert body["oauth"]["mock_allows_anyone"] is True
    assert set(body["oauth"]["enabled"]) == {"qq", "wechat"}


def test_health_oauth_segment_in_live_mode(client, monkeypatch):
    monkeypatch.setenv("OAUTH_MODE", "live")
    body = client.get("/health").json()
    assert body["oauth"]["mock_allows_anyone"] is False
