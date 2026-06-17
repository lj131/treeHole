"""
认证路由：注册 / 登录 / 当前用户 / 管理员审批
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from funcation.auth import (
    User,
    create_token,
    get_db,
    hash_password,
    require_admin,
    require_auth,
    verify_password,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])


# ============================================================
# Pydantic 模型
# ============================================================

class RegisterRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: int
    username: str
    role: str
    status: str
    created_at: str | None = None
    daily_chat_limit: int = 100
    character_limit: int = 10


class TokenResponse(BaseModel):
    token: str
    user: UserResponse


# ============================================================
# 公开端点
# ============================================================

@router.post("/register")
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    """注册新账号，状态为 pending（等待审批）"""
    username = req.username.strip()
    password = req.password

    # 校验
    if len(username) < 2 or len(username) > 20:
        raise HTTPException(status_code=422, detail="用户名需 2-20 个字符")
    if not username.replace("_", "").replace("-", "").isalnum():
        raise HTTPException(status_code=422, detail="用户名仅支持字母、数字、下划线、连字符")
    if len(password) < 4:
        raise HTTPException(status_code=422, detail="密码至少 4 个字符")

    # 查重
    existing = db.query(User).filter(User.username == username).first()
    if existing:
        raise HTTPException(status_code=409, detail="用户名已被注册")

    user = User(
        username=username,
        password_hash=hash_password(password),
        role="user",
        status="pending",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    logger.info("新用户注册: %s (id=%d, status=pending)", username, user.id)
    return {"message": "注册成功，请等待管理员审批", "user": user.to_dict()}


@router.post("/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    """登录，返回 JWT token"""
    user = db.query(User).filter(User.username == req.username.strip()).first()
    if user is None or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    token = create_token(user)
    logger.info("用户登录: %s (role=%s, status=%s)", user.username, user.role, user.status)
    return TokenResponse(token=token, user=UserResponse(**user.to_dict()))


# ============================================================
# 需认证端点
# ============================================================

@router.get("/me")
def me(user: User = Depends(require_auth)):
    """获取当前登录用户信息"""
    return {"user": user.to_dict()}


# ============================================================
# 管理员端点
# ============================================================

@router.get("/admin/pending")
def list_pending_users(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """列出所有待审批用户"""
    users = db.query(User).filter(User.status == "pending").order_by(User.created_at).all()
    return {"users": [u.to_dict() for u in users]}


@router.post("/admin/approve/{user_id}")
def approve_user(
    user_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """审批通过一个用户"""
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.status != "pending":
        raise HTTPException(status_code=400, detail="该用户不是待审批状态")
    user.status = "approved"
    db.commit()
    logger.info("管理员 %s 审批通过用户 %s (id=%d)", admin.username, user.username, user.id)
    return {"message": f"已通过 {user.username} 的审批", "user": user.to_dict()}


@router.post("/admin/reject/{user_id}")
def reject_user(
    user_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """拒绝一个用户（设为 rejected）"""
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.status = "rejected"
    db.commit()
    logger.info("管理员 %s 拒绝用户 %s (id=%d)", admin.username, user.username, user.id)
    return {"message": f"已拒绝 {user.username}", "user": user.to_dict()}


# ============================================================
# 配额管理（管理员）
# ============================================================

class QuotaUpdateRequest(BaseModel):
    daily_chat_limit: int | None = None
    character_limit: int | None = None


@router.get("/admin/users")
def list_all_users(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """列出所有用户（含配额 + 今日用量 + 角色数）"""
    from funcation.usage import get_today_chat_count
    from funcation.memory_center import MemoryCenter
    mc = MemoryCenter()

    users = db.query(User).order_by(User.created_at).all()
    result = []
    for u in users:
        d = u.to_dict()
        d["today_chat_count"] = get_today_chat_count(u.id, db)
        # 统计该用户创建的角色数
        all_chars = mc.get_all_characters()
        d["character_count"] = sum(1 for c in all_chars if c.get("created_by") == u.id)
        result.append(d)
    return {"users": result}


@router.post("/admin/quota/{user_id}")
def update_user_quota(
    user_id: int,
    req: QuotaUpdateRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """修改用户的配额"""
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if req.daily_chat_limit is not None:
        user.daily_chat_limit = req.daily_chat_limit
    if req.character_limit is not None:
        user.character_limit = req.character_limit
    db.commit()
    logger.info("管理员 %s 更新用户 %s 配额: chat_limit=%s char_limit=%s",
                admin.username, user.username, user.daily_chat_limit, user.character_limit)
    return {"message": "配额已更新", "user": user.to_dict()}


@router.get("/admin/usage/{user_id}")
def get_user_usage(
    user_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """查看用户最近 7 天用量"""
    from funcation.usage import get_user_usage_summary
    return get_user_usage_summary(user_id, days=7, db=db)
