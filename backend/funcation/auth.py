"""
用户认证与权限模块

- SQLite 持久化用户表（SQLAlchemy ORM）
- JWT Token 签发/验证
- 密码哈希（bcrypt）
- FastAPI Depends 依赖注入
- 首次启动自动创建管理员账号
- 预留 OAuth 字段（oauth_provider / oauth_id）
- 用户配额（每日 chat 次数 / 角色数）
"""

import json
import logging
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from sqlalchemy import Column, DateTime, Integer, String, create_engine, text
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

    # 配额（admin 不限）
    daily_chat_limit = Column(Integer, nullable=False, default=100)   # 0 = 不限
    character_limit = Column(Integer, nullable=False, default=10)
    # 当前角色 / 世界（per-user，替代旧的全局 current_*.json）
    current_character_id = Column(String(50), nullable=True)
    current_world_id = Column(String(50), nullable=True)

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
            "daily_chat_limit": self.daily_chat_limit,
            "character_limit": self.character_limit,
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


def require_chat_quota(
    user: User = Depends(require_approved),
    db: Session = Depends(get_db),
) -> User:
    """检查每日 chat 配额（仅对普通用户）"""
    if user.is_admin:
        return user
    limit = user.daily_chat_limit
    if limit <= 0:  # 0 = 不限
        return user
    from funcation.usage import get_today_chat_count
    today_count = get_today_chat_count(user.id, db)
    if today_count >= limit:
        raise HTTPException(
            status_code=429,
            detail=f"今日对话次数已达上限({limit}次)，请明天再来",
        )
    return user


# ============================================================
# 首次启动：创建默认管理员
# ============================================================

def _migrate_user_columns():
    """对已有 users 表追加新列（SQLAlchemy create_all 不会 ALTER 已有表）。

    PRAGMA table_info 查现有列，缺哪个 ALTER TABLE 加哪个。
    幂等：列已存在时跳过。
    """
    new_cols = [
        ("daily_chat_limit",     "INTEGER NOT NULL DEFAULT 100"),
        ("character_limit",      "INTEGER NOT NULL DEFAULT 10"),
        ("current_character_id", "VARCHAR(50)"),
        ("current_world_id",     "VARCHAR(50)"),
    ]
    try:
        with engine.begin() as conn:
            existing_cols = {
                row[1] for row in conn.execute(text("PRAGMA table_info(users)"))
            }
            for col_name, col_def in new_cols:
                if col_name not in existing_cols:
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN {col_name} {col_def}"))
                    logger.info("[auth] users 表追加列: %s", col_name)
    except Exception as exc:
        logger.warning("[auth] 列迁移失败（可能首次建表，忽略）: %s", exc)


def _migrate_legacy_to_admin():
    """一次性迁移：旧的全局共享数据归 admin（user_id=1）名下。

    迁移内容：
      - data/memories/*.json → data/memories/{admin_id}/
      - memories/*_memory.json → data/chat_history/{admin_id}/
      - current_character.json → admin.current_character_id
      - current_world.json → admin.current_world_id

    标记文件 data/.migrated_to_user_isolation 防止重复执行。
    ChromaDB 集合用懒迁移（在 memory_rag._get_collection 中处理），不在这里。
    """
    marker = Path("data/.migrated_to_user_isolation")
    if marker.exists():
        return

    admin_id = 1

    # 1. data/memories/*.json → data/memories/{admin_id}/
    try:
        old_dir = Path("data/memories")
        new_dir = old_dir / str(admin_id)
        if old_dir.exists():
            new_dir.mkdir(parents=True, exist_ok=True)
            for f in old_dir.glob("*.json"):
                if f.parent == old_dir:  # 只移顶层文件
                    target = new_dir / f.name
                    if not target.exists():
                        shutil.move(str(f), str(target))
            logger.info("[auth] 迁移 data/memories/*.json → data/memories/%s/", admin_id)
    except Exception as exc:
        logger.warning("[auth] 迁移 data/memories 失败: %s", exc)

    # 2. memories/*_memory.json → data/chat_history/{admin_id}/{char_id}.json
    #    （顺便把旧的 "{char_id}_memory.json" 重命名为新的 "{char_id}.json"）
    try:
        old_chat = Path("memories")
        new_chat = Path("data/chat_history") / str(admin_id)
        if old_chat.exists():
            new_chat.mkdir(parents=True, exist_ok=True)
            for f in old_chat.glob("*_memory.json"):
                # linwan_memory.json → linwan.json
                new_name = f.name.replace("_memory.json", ".json")
                target = new_chat / new_name
                if not target.exists():
                    shutil.move(str(f), str(target))
            logger.info("[auth] 迁移 memories/*_memory.json → data/chat_history/%s/", admin_id)
    except Exception as exc:
        logger.warning("[auth] 迁移聊天历史失败: %s", exc)

    # 3. current_character.json / current_world.json → admin user 字段
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.id == admin_id).first()
        if admin:
            try:
                with open("current_character.json", "r", encoding="utf-8") as f:
                    admin.current_character_id = json.load(f).get("character_id")
            except Exception:
                pass
            try:
                with open("current_world.json", "r", encoding="utf-8") as f:
                    admin.current_world_id = json.load(f).get("world_id")
            except Exception:
                pass
            db.commit()
            logger.info(
                "[auth] admin 当前角色=%s 当前世界=%s",
                admin.current_character_id,
                admin.current_world_id,
            )
    finally:
        db.close()

    # 4. 写迁移标记
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()
    except Exception as exc:
        logger.warning("[auth] 写迁移标记失败: %s", exc)


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


# 创建表 + 迁移列 + 确保管理员 + 迁移旧数据
Base.metadata.create_all(bind=engine)
_migrate_user_columns()
_ensure_admin()
_migrate_legacy_to_admin()
