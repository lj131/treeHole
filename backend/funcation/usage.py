"""
用户用量统计与配额

- UsageLog 模型（SQLite）：记录每次 API 调用的 token 消耗
- 内存缓存：每日 chat 次数计数器（跨天自动清空）
- get_today_chat_count() / record_usage()
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Session

from funcation.auth import engine, Base

logger = logging.getLogger(__name__)


# ============================================================
# UsageLog 模型
# ============================================================

class UsageLog(Base):
    __tablename__ = "usage_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, index=True, nullable=False)
    endpoint = Column(String(50), nullable=False)         # "chat" / "character_create" / "voice_chat"
    tokens_in = Column(Integer, default=0)                # response.usage.prompt_tokens
    tokens_out = Column(Integer, default=0)               # response.usage.completion_tokens
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


# ============================================================
# 内存缓存：每日 chat 计数
# ============================================================

_daily_chat_cache: dict[int, int] = {}
_cache_date: str = ""  # "YYYY-MM-DD"


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _refresh_cache(db):
    """从 usage_log 重建今日缓存"""
    global _daily_chat_cache, _cache_date
    today = _today_str()
    _daily_chat_cache.clear()
    _cache_date = today
    try:
        from sqlalchemy import func
        rows = (
            db.query(UsageLog.user_id, func.count())
            .filter(
                UsageLog.endpoint.in_(["chat", "voice_chat"]),
                UsageLog.created_at >= today,
            )
            .group_by(UsageLog.user_id)
            .all()
        )
        for user_id, count in rows:
            _daily_chat_cache[user_id] = count
        logger.info("[usage] 今日缓存已重建: %d 活跃用户", len(_daily_chat_cache))
    except Exception as exc:
        logger.warning("[usage] 缓存重建失败: %s", exc)


def get_today_chat_count(user_id: int, db: Session) -> int:
    """返回用户今日 chat 次数（从缓存查，缓存失效时重建）"""
    global _daily_chat_cache, _cache_date
    today = _today_str()
    if _cache_date != today or not _daily_chat_cache:
        _refresh_cache(db)
    return _daily_chat_cache.get(user_id, 0)


def record_usage(
    user_id: int,
    endpoint: str,
    tokens_in: int = 0,
    tokens_out: int = 0,
    db_session: Session | None = None,
):
    """记录一次 API 调用到 usage_log + 更新内存缓存"""
    global _daily_chat_cache, _cache_date

    # 更新缓存
    if endpoint in ("chat", "voice_chat"):
        today = _today_str()
        if _cache_date != today:
            _daily_chat_cache.clear()
            _cache_date = today
        _daily_chat_cache[user_id] = _daily_chat_cache.get(user_id, 0) + 1

    # 写 DB
    try:
        if db_session:
            log = UsageLog(
                user_id=user_id,
                endpoint=endpoint,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            )
            db_session.add(log)
            db_session.commit()
    except Exception as exc:
        logger.warning("[usage] 记录失败: %s", exc)


def get_user_usage_summary(user_id: int, days: int = 7, db: Session = None) -> dict:
    """返回用户最近 N 天的用量汇总"""
    from datetime import timedelta

    since = datetime.now(timezone.utc) - timedelta(days=days)
    try:
        from sqlalchemy import func
        rows = (
            db.query(
                UsageLog.endpoint,
                func.count().label("count"),
                func.sum(UsageLog.tokens_in).label("total_in"),
                func.sum(UsageLog.tokens_out).label("total_out"),
            )
            .filter(UsageLog.user_id == user_id, UsageLog.created_at >= since)
            .group_by(UsageLog.endpoint)
            .all()
        )
        by_endpoint = {}
        for ep, count, tin, tout in rows:
            by_endpoint[ep] = {
                "count": count,
                "tokens_in": tin or 0,
                "tokens_out": tout or 0,
            }
        return {"user_id": user_id, "days": days, "by_endpoint": by_endpoint}
    except Exception as exc:
        logger.warning("[usage] 查询用量失败: %s", exc)
        return {"user_id": user_id, "days": days, "error": str(exc)}


# 建表
Base.metadata.create_all(bind=engine)
