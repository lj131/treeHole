"""
用户认证与权限模块

- SQLite 持久化用户表（SQLAlchemy ORM）
- JWT Token 签发/验证
- 密码哈希（bcrypt）
- FastAPI Depends 依赖注入
- 首次启动自动创建管理员账号
- 预留 OAuth 字段（oauth_provider / oauth_id）
"""

import logging
import os
from datetime import datetime, timedelta, timezone

import jwt
from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from sqlalchemy import Column, DateTime, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

load_dotenv()

logger = logging.getLogger(__name__)

# ============================================================
# 数据库配置
# ============================================================

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/users.db")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


# ============================================================
# User 模型
# ============================================================

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    password_hash = Column(String(128), nullable=False)
    role = Column(String(20), nullable=False, default="user")  # "admin" | "user"
    status = Column(String(20), nullable=False, default="pending")  # "pending" | "approved" | "rejected"
    # 预留第三方登录
    oauth_provider = Column(String(20), nullable=True)
    oauth_id = Column(String(100), nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def is_approved(self) -> bool:
        return self.status == "approved" or self.is_admin

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "role": self.role,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
        }


# ============================================================
# 密码哈希
# ============================================================

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(raw: str) -> str:
    return _pwd_ctx.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    return _pwd_ctx.verify(raw, hashed)


# ============================================================
# JWT 工具
# ============================================================

_JWT_SECRET = os.getenv("JWT_SECRET_KEY", "amy-dev-secret-change-in-production")
_JWT_ALGORITHM = "HS256"
_JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "72"))


def create_token(user: User) -> str:
    """签发 JWT，payload 含 user_id / role / status"""
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "role": user.role,
        "status": user.status,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=_JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """验证 JWT，返回 payload。失败抛 jwt.PyJWTError。"""
    return jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])


# ============================================================
# 认证依赖（FastAPI Depends）
# ============================================================

_bearer = HTTPBearer(auto_error=False)


def get_db() -> Session:
    """获取数据库会话（FastAPI Depends）"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User | None:
    """从 Bearer token 解析当前用户。无 token 或无效 → None（允许可选认证）。"""
    if credentials is None:
        return None
    try:
        payload = decode_token(credentials.credentials)
        user_id = int(payload["sub"])
        user = db.query(User).filter(User.id == user_id).first()
        if user is None:
            return None
        return user
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def require_auth(user: User | None = Depends(get_current_user)) -> User:
    """强制认证：未登录 → 401"""
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    return user


def require_approved(user: User = Depends(require_auth)) -> User:
    """已审批用户或管理员：未审批 → 403"""
    if not user.is_approved:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="您的账号尚未通过审批，请联系管理员",
        )
    return user


def require_admin(user: User = Depends(require_auth)) -> User:
    """管理员：非 admin → 403"""
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅管理员可操作")
    return user


# ============================================================
# 首次启动：创建默认管理员
# ============================================================

def _ensure_admin():
    """若无 admin 用户，自动创建默认管理员"""
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.role == "admin").first()
        if existing is not None:
            return
        admin_pwd = os.getenv("ADMIN_DEFAULT_PASSWORD", "admin123")
        admin = User(
            username="admin",
            password_hash=hash_password(admin_pwd),
            role="admin",
            status="approved",
        )
        db.add(admin)
        db.commit()
        logger.info("默认管理员已创建: admin / %s（请登录后修改密码）", admin_pwd)
    except Exception as exc:
        logger.warning("创建管理员失败（可能已存在）: %s", exc)
    finally:
        db.close()


# 创建表 + 确保管理员
Base.metadata.create_all(bind=engine)
_ensure_admin()
