"""
后台世界 Tick 调度器

每 N 分钟为活跃用户的当前世界推进一次:
- 推进现有 world events 进度
- 必要时生成新事件
- 应用 character impact 到当前角色
- 标记 proactive 通知,用户下次上线时会看到 "刚才发生了什么"

启动: 在 api/api.py 的 lifespan 中调用 start_world_tick_scheduler()
关闭开关: 设置环境变量 RUN_BACKGROUND_TICK=0 完全禁用

设计要点:
- 用 asyncio.create_task 启动单一后台循环,不引入 APScheduler 依赖
  (项目已经有几个 asyncio 后台任务,继续这个模式)
- 限流: 每个 (user_id, world_id) 至少间隔 MIN_TICK_INTERVAL 分钟
- 限活跃用户: 只处理 last_chat_time 在 7 天内的用户(避免空跑)
- 每用户独立 try/except,一个用户失败不影响其他
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta

from funcation import world_event_agent
from funcation.memory_center import MemoryCenter

logger = logging.getLogger(__name__)

# ============================================================
# 配置
# ============================================================

# 调度间隔: 主循环每 N 秒检查一次
TICK_LOOP_INTERVAL_SEC = int(os.getenv("WORLD_TICK_LOOP_SEC", "1800"))  # 30 min

# 单个 (user, world) 最小 tick 间隔(分钟)
MIN_TICK_INTERVAL_MIN = int(os.getenv("WORLD_TICK_MIN_INTERVAL_MIN", "30"))

# 用户活跃判定: last_chat_time 在 N 天内
ACTIVE_USER_DAYS = int(os.getenv("WORLD_TICK_ACTIVE_DAYS", "7"))


# ============================================================
# 调度器
# ============================================================

_scheduler_task: asyncio.Task | None = None
_stop_event: asyncio.Event | None = None


def _get_active_users():
    """从 SQLite 取所有 approved 状态的用户。

    返回 [{id, current_character_id, current_world_id}, ...]
    不在这里过滤"7 天内活跃"——那需要 last_chat_time,但 last_chat_time 存在
    每个角色的 memory.json 里,扫一遍开销大。先按 status='approved' 过滤,
    后续在 _tick_user 里检查 last_chat_time 决定是否真的 tick。
    """
    from funcation.auth import SessionLocal, User

    db = SessionLocal()
    try:
        users = db.query(User).filter(User.status == "approved").all()
        return [
            {
                "id": u.id,
                "current_character_id": u.current_character_id,
                "current_world_id": u.current_world_id,
            }
            for u in users
        ]
    finally:
        db.close()


def _should_tick_user(mc: MemoryCenter, user_id: int, character_id: str) -> bool:
    """检查该用户是否值得 tick:
    - last_chat_time 在 ACTIVE_USER_DAYS 天内
    - 距上次 background tick 超过 MIN_TICK_INTERVAL_MIN 分钟
    """
    try:
        last_chat = mc.get_last_chat_time(user_id, character_id)
    except Exception:
        return False

    if not last_chat:
        return False

    try:
        last_dt = datetime.fromisoformat(last_chat)
    except (ValueError, TypeError):
        return False

    if datetime.now() - last_dt > timedelta(days=ACTIVE_USER_DAYS):
        return False

    return True


def _world_tick_due(mc: MemoryCenter, world_id: str, user_id: int) -> bool:
    """根据 world_state 的 last_bg_tick_time 字段判断是否到了 tick 时间。
    按 user mode 路由到公共/私人 world_state 副本。"""
    try:
        mode = mc.get_user_world_mode(user_id)
        world_data = mc.load_world_state(world_id, user_id, mode)
    except Exception:
        return True  # 加载失败时让 tick 流程自己处理

    runtime = world_data.get("world_state", {})
    last_bg_tick = runtime.get("last_bg_tick_time", "")
    if not last_bg_tick:
        return True

    try:
        last_dt = datetime.fromisoformat(last_bg_tick)
    except (ValueError, TypeError):
        return True

    return datetime.now() - last_dt > timedelta(minutes=MIN_TICK_INTERVAL_MIN)


def _mark_world_ticked(mc: MemoryCenter, world_id: str, user_id: int):
    """记录这一轮 background tick 的时间到 world_state（按 user mode 路由）。

    注意:与原有的 last_tick_date(按天) 不同,这是 background 单独的字段。
    /chat 触发的 tick 仍然走原有的 last_tick_date 逻辑。
    """
    try:
        mode = mc.get_user_world_mode(user_id)
        world_data = mc.load_world_state(world_id, user_id, mode)
        runtime = world_data.setdefault("world_state", {})
        runtime["last_bg_tick_time"] = datetime.now().isoformat()
        mc.save_world_state(world_id, world_data, user_id, mode)
    except Exception as exc:
        logger.warning("[world_tick] 标记 last_bg_tick_time 失败: %s", exc)


async def _tick_one_user(mc: MemoryCenter, user_info: dict, loop):
    """为单个用户的当前世界 tick 一次。

    所有阻塞调用走 run_in_executor,避免阻塞调度器。
    """
    user_id = user_info["id"]
    character_id = user_info.get("current_character_id") or "linwan"
    world_id = user_info.get("current_world_id") or "campus"

    # 1. 检查用户是否活跃
    if not await loop.run_in_executor(
        None, lambda: _should_tick_user(mc, user_id, character_id)
    ):
        return None

    # 2. 检查 world 是否到 tick 间隔（按用户 mode 路由）
    if not await loop.run_in_executor(
        None, lambda: _world_tick_due(mc, world_id, user_id)
    ):
        return None

    # 3. 加载角色和世界定义
    try:
        character = await loop.run_in_executor(
            None, lambda: mc.load_character_by_id(character_id)
        )
        world = await loop.run_in_executor(
            None, lambda: mc.load_world_by_id(world_id)
        )
    except Exception as exc:
        logger.warning(
            "[world_tick] user=%s 加载角色/世界失败,跳过: %s", user_id, exc
        )
        return None

    if not world:
        return None

    # 4. force=True 跳过 world_event_agent 内部的"今天已 tick"判断,
    #    因为 background tick 和 chat-triggered tick 是两套独立节律。
    try:
        result = await loop.run_in_executor(
            None,
            lambda: world_event_agent.tick(mc, user_id, character, world, force=True),
        )
        # 5. 记录 background tick 时间（按用户 mode 路由）
        await loop.run_in_executor(
            None, lambda: _mark_world_ticked(mc, world_id, user_id)
        )
        return result
    except Exception as exc:
        logger.warning("[world_tick] user=%s tick 失败: %s", user_id, exc)
        return None


async def _scheduler_loop():
    """主循环:每 TICK_LOOP_INTERVAL_SEC 秒扫一遍活跃用户。"""
    mc = MemoryCenter()
    loop = asyncio.get_event_loop()
    logger.info(
        "[world_tick] 后台调度器启动 (loop=%ds, min_interval=%dmin, active_days=%d)",
        TICK_LOOP_INTERVAL_SEC,
        MIN_TICK_INTERVAL_MIN,
        ACTIVE_USER_DAYS,
    )

    # 启动后等 60s 再开始第一轮,避免和 startup 抢资源
    try:
        await asyncio.wait_for(_stop_event.wait(), timeout=60.0)
        return  # stop 被 set
    except asyncio.TimeoutError:
        pass

    while not _stop_event.is_set():
        try:
            users = await loop.run_in_executor(None, _get_active_users)
            ticked = 0
            for user_info in users:
                if _stop_event.is_set():
                    break
                if not user_info.get("current_character_id"):
                    continue
                result = await _tick_one_user(mc, user_info, loop)
                if result and result.get("action") == "ticked":
                    ticked += 1
                # 用户之间小间隔,避免集中调 LLM
                await asyncio.sleep(0.5)
            if ticked:
                logger.info("[world_tick] 本轮 tick 完成: %d/%d 个用户", ticked, len(users))
        except Exception as exc:
            logger.exception("[world_tick] 主循环异常: %s", exc)

        # 等下一轮 (用 wait_for 支持快速停止)
        try:
            await asyncio.wait_for(
                _stop_event.wait(), timeout=TICK_LOOP_INTERVAL_SEC
            )
            return  # stop 被 set
        except asyncio.TimeoutError:
            continue


# ============================================================
# 公开 API
# ============================================================

def start_world_tick_scheduler() -> asyncio.Task | None:
    """启动后台世界 tick 调度器。

    返回创建的 Task,供 lifespan 在 shutdown 时 cancel。
    若 RUN_BACKGROUND_TICK=0,返回 None(完全跳过)。
    """
    global _scheduler_task, _stop_event

    if os.getenv("RUN_BACKGROUND_TICK", "1") == "0":
        logger.info("[world_tick] RUN_BACKGROUND_TICK=0,后台调度器已禁用")
        return None

    if _scheduler_task and not _scheduler_task.done():
        logger.warning("[world_tick] 调度器已运行,跳过重复启动")
        return _scheduler_task

    _stop_event = asyncio.Event()
    _scheduler_task = asyncio.create_task(_scheduler_loop())
    return _scheduler_task


async def stop_world_tick_scheduler():
    """优雅停止后台调度器。"""
    global _scheduler_task, _stop_event

    if _stop_event is not None:
        _stop_event.set()

    if _scheduler_task is not None and not _scheduler_task.done():
        try:
            await asyncio.wait_for(_scheduler_task, timeout=5.0)
        except asyncio.TimeoutError:
            _scheduler_task.cancel()
            try:
                await _scheduler_task
            except (asyncio.CancelledError, Exception):
                pass
        logger.info("[world_tick] 后台调度器已停止")

    _scheduler_task = None
    _stop_event = None
