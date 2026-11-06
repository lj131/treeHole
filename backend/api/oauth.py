"""第三方登录路由（QQ / 微信）。

## 回调节奏（QQ 的硬性要求）

QQ 官方 WIKI 明确：**回调地址不能用 localhost / 端口，且回调域不能带 `#`**。
而本项目前端是 Vue hash 路由。所以链路是：

```
前端点按钮 → 后端 /authorize 返回第三方 URL
          → 浏览器跳 QQ/微信
          → 第三方 302 回【后端】/auth/oauth/{p}/callback   ← 注册在开放平台的地址
          → 后端 302 回【前端】{FRONTEND_BASE}/#/oauth/callback?token=...
          → 前端读 token 写进 authStore，并清掉地址栏
```

token 放在 `#` **之后**的 query 里：fragment 不会随 HTTP 请求发到服务器，
也不会进服务端访问日志。前端落地后要 `replaceState` 清掉。

## 账号策略（可在 env 调）

- `OAUTH_DEFAULT_STATUS=approved`（默认）：扫码即用，免管理员审批
- 设为 `pending` 则沿用现有注册审批流
- QQ 的 openid 与微信的 openid **互不相通** —— 同一个人用两家登会得到两个账号，
  本期接受，不做绑定/合并（见 plans/2026-11-06-oauth-login.md）
"""
from __future__ import annotations

import hashlib
import logging
import os
import secrets
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from funcation import oauth
from funcation.auth import (
    User,
    create_token,
    get_db,
    hash_password,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["oauth"])

#: 第三方新用户的初始状态。**approved = 免审批**，改成 pending 走原有审批流
OAUTH_DEFAULT_STATUS = "approved"


def _default_status() -> str:
    val = (os.getenv("OAUTH_DEFAULT_STATUS") or OAUTH_DEFAULT_STATUS).strip().lower()
    return val if val in ("approved", "pending", "rejected") else OAUTH_DEFAULT_STATUS


def _frontend_callback(**params) -> str:
    query = "&".join(f"{k}={quote(str(v))}" for k, v in params.items() if v is not None)
    return f"{oauth.frontend_base_url()}/#/oauth/callback" + (f"?{query}" if query else "")


@router.get("/oauth/providers")
def list_oauth_providers():
    """前端据此渲染按钮。没配好 AppID 的 provider 显示 `enabled: false`（不隐藏，便于排查）。"""
    return {"providers": oauth.configured_providers()}


@router.get("/oauth/{provider}/authorize")
def authorize(provider: str):
    """返回第三方授权 URL 和一次性 state。前端 `location.href = url`。"""
    try:
        prov = oauth.get_provider(provider)
    except oauth.OAuthNotConfigured as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    state = oauth.issue_state(provider)
    return {"provider": provider, "url": prov.authorize_url(state), "state": state}


def _unique_username(db: Session, provider: str, subject: str) -> str:
    """第三方号 → 本系统用户名。确定性 + 冲突时加后缀。

    用 hash 而不是昵称：昵称会重复、会变、可能带表情/空格，不适合当唯一键。
    """
    base = f"{provider}_{hashlib.sha1(subject.encode('utf-8')).hexdigest()[:12]}"
    candidate = base
    for i in range(1, 100):
        if not db.query(User).filter(User.username == candidate).first():
            return candidate
        candidate = f"{base}_{i}"
    return f"{base}_{secrets.token_hex(4)}"


def find_or_create_oauth_user(db: Session, identity: oauth.OAuthIdentity) -> tuple[User, bool]:
    """按 `(oauth_provider, oauth_id)` 查/建用户。返回 `(user, is_new)`。

    **并发安全**：唯一索引挡住并发建号，`IntegrityError` 后重查复用，不抛 500。
    """
    existing = (
        db.query(User)
        .filter(User.oauth_provider == identity.provider, User.oauth_id == identity.subject)
        .first()
    )
    if existing:
        return existing, False

    user = User(
        username=_unique_username(db, identity.provider, identity.subject),
        # password_hash 是 NOT NULL。给一个随机串当占位 —— OAuth 用户不该能用密码登录，
        # 而这个随机值没人知道，等价于"密码登录关闭"。避免改表结构的迁移风险。
        password_hash=hash_password(secrets.token_urlsafe(32)),
        role="user",
        status=_default_status(),
        oauth_provider=identity.provider,
        oauth_id=identity.subject,
        nickname=(identity.nickname or "")[:50] or None,
        avatar=(identity.avatar or "")[:255] or None,
    )
    db.add(user)
    try:
        db.commit()
        db.refresh(user)
        logger.info("[oauth] 新建第三方用户 id=%s provider=%s status=%s",
                    user.id, identity.provider, user.status)
        return user, True
    except IntegrityError:
        db.rollback()
        raced = (
            db.query(User)
            .filter(User.oauth_provider == identity.provider, User.oauth_id == identity.subject)
            .first()
        )
        if raced:
            return raced, False
        # 重名冲突（极小概率）：重试一次并让 _unique_username 再挑一个
        user.username = _unique_username(db, identity.provider, identity.subject)
        db.add(user)
        db.commit()
        db.refresh(user)
        return user, True


@router.get("/oauth/{provider}/callback")
def oauth_callback(
    provider: str,
    code: str = "",
    state: str = "",
    error: str = "",
    db: Session = Depends(get_db),
):
    """第三方回调。**任何失败都 302 回前端带 error**，不返回裸 500 / 不泄漏第三方响应。"""
    if error:
        # 用户在 QQ/微信页面点了取消
        return RedirectResponse(_frontend_callback(error="授权已取消"), status_code=302)

    try:
        oauth.consume_state(state, provider)       # 一次性 + 过期 + provider 绑定
        prov = oauth.get_provider(provider)
        identity = prov.exchange(code)
        if not identity.subject:
            raise oauth.OAuthError("第三方未返回有效身份")
    except oauth.OAuthNotConfigured as exc:
        return RedirectResponse(_frontend_callback(error=str(exc)), status_code=302)
    except oauth.OAuthError as exc:
        return RedirectResponse(_frontend_callback(error=str(exc)), status_code=302)
    except Exception as exc:  # noqa: BLE001 - 回调绝不能给用户一个裸 500
        logger.exception("[oauth] %s 回调未预期异常: %s", provider, type(exc).__name__)
        return RedirectResponse(_frontend_callback(error="登录失败，请稍后重试"), status_code=302)

    try:
        user, is_new = find_or_create_oauth_user(db, identity)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[oauth] 建号失败: %s", type(exc).__name__)
        return RedirectResponse(_frontend_callback(error="账号创建失败，请稍后重试"), status_code=302)

    if user.status == "deactivated":
        return RedirectResponse(_frontend_callback(error="该账号已被停用"), status_code=302)

    token = create_token(user)
    logger.info("[oauth] 登录成功 user=%s provider=%s is_new=%s", user.id, provider, is_new)
    return RedirectResponse(
        _frontend_callback(token=token, provider=provider, is_new=1 if is_new else 0),
        status_code=302,
    )
