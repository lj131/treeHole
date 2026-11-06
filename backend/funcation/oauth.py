"""QQ / 微信网站应用第三方登录 —— provider 抽象 + state 防 CSRF。

## 为什么单独一层

OAuth 的业务逻辑（建号、签 JWT）不该关心"这家的 token 接口返回什么格式"。
而 QQ 和微信的格式**差别非常大**，还都不是标准 JSON：

| | 授权 | 换 token | 换身份 |
|---|---|---|---|
| QQ | `graph.qq.com/oauth2.0/authorize` | **querystring** `access_token=x&expires_in=...` | `oauth2.0/me` 返回 **JSONP** `callback( {...} );` |
| 微信 | `open.weixin.qq.com/connect/qrconnect` | JSON（有 `errcode`） | JSON（有 `errcode`） |

所以每种 provider 自己负责把响应解析成统一的 `OAuthIdentity`。

## 两种运行模式

- `OAUTH_MODE=live`（默认）：只有配齐了 AppID/Secret 的 provider 才可用
- `OAUTH_MODE=mock`：**不发任何外网请求**，用确定性的假身份走完整链路。
  本地没有备案域名、没拿 AppID 时靠它联调和跑测试（见 plans/2026-11-06-oauth-login.md）

## 安全约定

- 密钥只从 env 读，**不进 `system_config`**（项目约定：密钥类不进配置页面）
- `state` 用独立派生密钥签名，带 TTL + 一次性 nonce，防 CSRF 与重放
- 回调地址取**服务端配置**，绝不信客户端传的 `redirect_uri`（防开放重定向）
- 第三方原始响应只进服务端日志，抛给上层的错误一律泛化
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import jwt
import requests

logger = logging.getLogger(__name__)

SUPPORTED_PROVIDERS = ("qq", "wechat")

PROVIDER_LABELS = {"qq": "QQ 登录", "wechat": "微信登录"}

#: 外部接口的超时（秒）。挂在登录主链路上，不能让用户干等
HTTP_TIMEOUT = 8

#: state 有效期（秒）
STATE_TTL_SEC = 600


class OAuthError(RuntimeError):
    """可安全地展示给用户的错误（文案已泛化）。"""


class OAuthNotConfigured(OAuthError):
    """这个 provider 没配 AppID/Secret。"""


@dataclass(frozen=True)
class OAuthIdentity:
    """第三方返回的、与本系统无关的身份。"""

    provider: str
    subject: str                  # QQ 的 openid / 微信的 openid
    nickname: str = ""
    avatar: str = ""
    unionid: str = ""             # 微信有，QQ 没有


# ============================================================
# 配置（只从 env 读，密钥不进 system_config）
# ============================================================

def oauth_mode() -> str:
    return (os.getenv("OAUTH_MODE") or "live").strip().lower()


def frontend_base_url() -> str:
    """回调成功后 302 回前端的地址。

    ⚠️ 前端是 hash 路由，而 QQ 明确规定**回调域不能带 #** ——
    所以 QQ/微信的回调落在后端，再由这里跳回 `.../#/oauth/callback`。
    """
    return (os.getenv("FRONTEND_BASE_URL") or "http://127.0.0.1:5173").rstrip("/")


def redirect_uri_for(provider: str) -> str:
    """该 provider 注册在开放平台上的回调地址。

    优先级：provider 专属 env > `OAUTH_CALLBACK_BASE` 拼接。
    **必须与开放平台填的完全一致**（域名 + path），否则 QQ 返回 100010。
    """
    specific = os.getenv(f"{provider.upper()}_REDIRECT_URI")
    if specific:
        return specific
    # 兜底仅供 `OAUTH_MODE=mock` 本地联调。
    # ⚠️ 接真实接口时**必须**配 OAUTH_CALLBACK_BASE 或 provider 专属 REDIRECT_URI，
    # 否则会拿 localhost 去和开放平台注册的域名比对，QQ 直接返回 100010。
    base = (os.getenv("OAUTH_CALLBACK_BASE") or "http://127.0.0.1:8000").rstrip("/")
    return f"{base}/auth/oauth/{provider}/callback"


def _client_credentials(provider: str) -> tuple[str, str]:
    if provider == "qq":
        return os.getenv("QQ_APP_ID") or "", os.getenv("QQ_APP_KEY") or ""
    if provider == "wechat":
        return os.getenv("WECHAT_APP_ID") or "", os.getenv("WECHAT_APP_SECRET") or ""
    return "", ""


def is_configured(provider: str) -> bool:
    if provider not in SUPPORTED_PROVIDERS:
        return False
    if oauth_mode() == "mock":
        return True
    cid, secret = _client_credentials(provider)
    return bool(cid and secret and redirect_uri_for(provider))


def configured_providers() -> List[Dict[str, Any]]:
    """前端据此决定显示哪些按钮。**没配好就不显示**，别给用户一个点了必失败的按钮。"""
    return [
        {
            "provider": name,
            "label": PROVIDER_LABELS[name],
            "enabled": is_configured(name),
            "mode": oauth_mode(),
        }
        for name in SUPPORTED_PROVIDERS
    ]


# ============================================================
# state：签名 + 过期 + 一次性
# ============================================================

def _state_secret() -> str:
    """从 JWT_SECRET_KEY 派生，避免和登录 token 共用同一密钥。"""
    base = os.getenv("JWT_SECRET_KEY", "amy-dev-secret-change-in-production")
    return hashlib.sha256(f"{base}|oauth-state|v1".encode()).hexdigest()


_used_nonces: Dict[str, float] = {}
_nonce_lock = threading.Lock()


def _sweep_nonces(now: float) -> None:
    expired = [k for k, exp in _used_nonces.items() if exp < now]
    for k in expired:
        _used_nonces.pop(k, None)


def issue_state(provider: str) -> str:
    payload = {
        "p": provider,
        "n": secrets.token_urlsafe(16),
        "iat": int(time.time()),
        "exp": int(time.time()) + STATE_TTL_SEC,
    }
    return jwt.encode(payload, _state_secret(), algorithm="HS256")


def consume_state(state: str, provider: str) -> None:
    """校验并**立即作废** state。失败抛 OAuthError。

    一次性是必须的：否则攻击者拿到一次回调 URL 就能重放登录。
    """
    if not state:
        raise OAuthError("登录状态无效，请重新发起")
    try:
        payload = jwt.decode(state, _state_secret(), algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        logger.warning("[oauth] state 校验失败: %s", type(exc).__name__)
        raise OAuthError("登录状态已失效或无效，请重新发起") from None
    if payload.get("p") != provider:
        raise OAuthError("登录来源不匹配，请重新发起")
    nonce = str(payload.get("n") or "")
    if not nonce:
        raise OAuthError("登录状态无效，请重新发起")
    with _nonce_lock:
        _sweep_nonces(time.time())
        if nonce in _used_nonces:
            raise OAuthError("该登录链接已被使用，请重新发起")
        _used_nonces[nonce] = float(payload.get("exp") or (time.time() + STATE_TTL_SEC))


# ============================================================
# Provider 实现
# ============================================================

class BaseProvider:
    name = ""

    def __init__(self, name: str):
        self.name = name
        self.client_id, self.client_secret = _client_credentials(name)
        self.redirect_uri = redirect_uri_for(name)

    def authorize_url(self, state: str) -> str:
        raise NotImplementedError

    def exchange(self, code: str) -> OAuthIdentity:
        raise NotImplementedError

    def _get(self, url: str, params: Dict[str, Any]) -> requests.Response:
        try:
            resp = requests.get(url, params=params, timeout=HTTP_TIMEOUT)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            logger.warning("[oauth] %s 请求第三方失败: %s", self.name, type(exc).__name__)
            raise OAuthError("第三方登录服务暂时不可用，请稍后重试") from None

    @staticmethod
    def _jsonp(text: str) -> Dict[str, Any]:
        """QQ 的 `callback( {...} );` → dict。"""
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise OAuthError("第三方返回数据格式异常")
        try:
            data = json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            raise OAuthError("第三方返回数据格式异常") from None
        if not isinstance(data, dict):
            raise OAuthError("第三方返回数据格式异常")
        return data


class QQProvider(BaseProvider):
    def authorize_url(self, state: str) -> str:
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "state": state,
            "scope": "get_user_info",
        }
        return "https://graph.qq.com/oauth2.0/authorize?" + urlencode(params)

    def exchange(self, code: str) -> OAuthIdentity:
        # ① 换 token：响应**不是 JSON**，是 `access_token=xxx&expires_in=...`
        token_resp = self._get(
            "https://graph.qq.com/oauth2.0/token",
            {
                "grant_type": "authorization_code",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "code": code,
                "redirect_uri": self.redirect_uri,
            },
        )
        token_text = (token_resp.text or "").strip()
        if "callback(" in token_text:
            err = self._jsonp(token_text)
            logger.warning("[oauth] QQ token 返回错误: ret=%s", err.get("error"))
            raise OAuthError("QQ 授权失败，请重新发起")
        token_pairs = dict(
            part.split("=", 1) for part in token_text.split("&") if "=" in part
        )
        access_token = token_pairs.get("access_token") or ""
        if not access_token:
            logger.warning("[oauth] QQ token 响应里没有 access_token")
            raise OAuthError("QQ 授权失败，请重新发起")

        # ② 换 openid：响应是 **JSONP**，不是 JSON
        me = self._jsonp(self._get(
            "https://graph.qq.com/oauth2.0/me", {"access_token": access_token}
        ).text or "")
        openid = str(me.get("openid") or "")
        if not openid:
            raise OAuthError("QQ 授权失败，请重新发起")

        # ③ 换昵称头像（失败不阻断登录：身份已经拿到了）
        nickname, avatar = "", ""
        try:
            info = self._get(
                "https://graph.qq.com/user/get_user_info",
                {
                    "access_token": access_token,
                    "oauth_consumer_key": self.client_id,
                    "openid": openid,
                    "format": "json",
                },
            ).json()
            # ⚠️ QQ 用 ret=0 表示成功。写 `info.get("ret") or -1` 会把 0 当假值
            # 变成 -1，昵称头像静默丢失（测试抓到过）。
            ret = info.get("ret") if isinstance(info, dict) else None
            if ret is not None and int(ret) == 0:
                nickname = str(info.get("nickname") or "")[:50]
                avatar = str(info.get("figureurl_qq_2") or info.get("figureurl_qq_1") or "")[:255]
        except (ValueError, TypeError, OAuthError):
            logger.info("[oauth] QQ 用户资料获取失败（不影响登录）")

        return OAuthIdentity(provider="qq", subject=openid, nickname=nickname, avatar=avatar)


class WechatProvider(BaseProvider):
    def authorize_url(self, state: str) -> str:
        params = {
            "appid": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "snsapi_login",
            "state": state,
        }
        return (
            "https://open.weixin.qq.com/connect/qrconnect?"
            + urlencode(params) + "#wechat_redirect"
        )

    def exchange(self, code: str) -> OAuthIdentity:
        token = self._get(
            "https://api.weixin.qq.com/sns/oauth2/access_token",
            {
                "appid": self.client_id,
                "secret": self.client_secret,
                "code": code,
                "grant_type": "authorization_code",
            },
        ).json()
        if not isinstance(token, dict) or token.get("errcode"):
            logger.warning("[oauth] 微信 token 返回错误: %s", token.get("errcode") if isinstance(token, dict) else "?")
            raise OAuthError("微信授权失败，请重新发起")
        access_token = str(token.get("access_token") or "")
        openid = str(token.get("openid") or "")
        if not access_token or not openid:
            raise OAuthError("微信授权失败，请重新发起")
        unionid = str(token.get("unionid") or "")

        nickname, avatar = "", ""
        try:
            info = self._get(
                "https://api.weixin.qq.com/sns/userinfo",
                {"access_token": access_token, "openid": openid, "lang": "zh_CN"},
            ).json()
            if isinstance(info, dict) and not info.get("errcode"):
                nickname = str(info.get("nickname") or "")[:50]
                avatar = str(info.get("headimgurl") or "")[:255]
        except ValueError:
            logger.info("[oauth] 微信用户资料获取失败（不影响登录）")

        return OAuthIdentity(
            provider="wechat", subject=openid, nickname=nickname,
            avatar=avatar, unionid=unionid,
        )


class MockProvider(BaseProvider):
    """**不发外网**的本地联调实现。

    `authorize_url` 直接指回本服务的 callback，带上确定性 code，
    所以浏览器点按钮 → 跳本服务 → 302 回前端，整条链路能真跑通。
    """

    def authorize_url(self, state: str) -> str:
        subject = os.getenv("OAUTH_MOCK_SUBJECT") or "local_tester"
        # code 里带上 provider，避免两家 mock 撞成同一个账号
        code = f"mock|{self.name}|{subject}"
        return self.redirect_uri + "?" + urlencode({"code": code, "state": state})

    def exchange(self, code: str) -> OAuthIdentity:
        parts = (code or "").split("|")
        if len(parts) != 3 or parts[0] != "mock" or parts[1] != self.name or not parts[2]:
            raise OAuthError("模拟登录凭证无效")
        return OAuthIdentity(
            provider=self.name,
            subject=parts[2],
            nickname=f"{PROVIDER_LABELS[self.name]}测试用户",
        )


def get_provider(name: str) -> BaseProvider:
    """取 provider。未配置时抛 `OAuthNotConfigured`（调用方转 404/400）。"""
    if name not in SUPPORTED_PROVIDERS:
        raise OAuthNotConfigured("不支持的登录方式")
    if not is_configured(name):
        raise OAuthNotConfigured("该登录方式尚未配置")
    if oauth_mode() == "mock":
        return MockProvider(name)
    return QQProvider(name) if name == "qq" else WechatProvider(name)
