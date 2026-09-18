import asyncio
import functools
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)

# 默认重试的网络相关异常（超时、连接错误等）
RETRYABLE_EXCEPTIONS = (
    TimeoutError,
    ConnectionError,
    ConnectionRefusedError,
    ConnectionResetError,
    BrokenPipeError,
    OSError,  # 覆盖一般网络错误
)


def get_time_diff_minutes(last_time):
    if not last_time:
        return 0

    last = datetime.fromisoformat(last_time)
    now = datetime.now()
    diff = now - last
    return diff.total_seconds() / 60


async def retry_async(
    operation,
    max_retries=3,
    base_delay=1.0,
    retryable_exceptions=RETRYABLE_EXCEPTIONS,
):
    """
    异步重试工具 — 对网络超时等临时错误自动重试（指数退避）。

    参数:
        operation: async callable 或 sync callable
        max_retries: 最大尝试次数（含首次），默认 3
        base_delay: 退避基础延迟（秒），每次重试延迟为 base_delay * 2^(attempt-1)
        retryable_exceptions: 哪些异常触发重试（默认网络相关异常）

    返回:
        operation 的返回值

    抛出:
        最后一次失败时的异常（如果所有重试都失败）
    """
    last_exception = None

    for attempt in range(1, max_retries + 1):
        try:
            if asyncio.iscoroutinefunction(operation):
                return await operation()
            elif callable(operation):
                loop = asyncio.get_event_loop()
                return await loop.run_in_executor(None, operation)
            else:
                raise TypeError(f"operation 必须是 callable，收到: {type(operation)}")
        except retryable_exceptions as e:
            last_exception = e
            if attempt < max_retries:
                delay = base_delay * (2 ** (attempt - 1))
                logger.warning(
                    "retry_async 第 %d/%d 次失败 (%s)，%.1fs 后重试...",
                    attempt, max_retries, e, delay,
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "retry_async 全部 %d 次尝试均失败: %s", max_retries, e
                )
        except Exception:
            # 非可重试异常直接抛出
            raise

    # 所有重试耗尽
    if last_exception:
        raise last_exception


def retry_sync(
    operation,
    max_retries=3,
    base_delay=1.0,
    retryable_exceptions=RETRYABLE_EXCEPTIONS,
):
    """
    同步重试工具 — 适用于 FastAPI sync endpoint 中的 API 调用。

    参数与 retry_async 相同，但不使用 asyncio.sleep（用 time.sleep 替代）。
    """
    import time

    last_exception = None

    for attempt in range(1, max_retries + 1):
        try:
            return operation()
        except retryable_exceptions as e:
            last_exception = e
            if attempt < max_retries:
                delay = base_delay * (2 ** (attempt - 1))
                logger.warning(
                    "retry_sync 第 %d/%d 次失败 (%s)，%.1fs 后重试...",
                    attempt, max_retries, e, delay,
                )
                time.sleep(delay)
            else:
                logger.error(
                    "retry_sync 全部 %d 次尝试均失败: %s", max_retries, e
                )
        except Exception:
            raise

    if last_exception:
        raise last_exception


def remove_file_quietly(path, label: str = "file") -> bool:
    """删除单个文件，失败一律降级（不向上抛）。

    **返回值语义 = 「是否已处于删除后的状态」**：文件本来就不存在也算成功（幂等），
    只有真的尝试删除却失败才返回 False。调用方据此决定要不要给用户报 warning——
    把「无需清理」误判成「清理失败」会产出假警告。

    Windows 文件被占用（PermissionError）、只读挂载、杀软拦截都会让 os.remove 抛异常；
    某些沙箱/包装层还会用 SystemExit 表达「拒绝删除」，它是 BaseException，
    `except Exception` 接不住。清理属于 best-effort 副作用，不能把用户可见操作打成 500。

    注意：本函数只做「尽力而为」，**调用方不要依赖它保证文件已删**。
    """
    if not path or not os.path.isfile(path):
        return True
    try:
        os.remove(path)
        return True
    except (Exception, SystemExit) as e:  # noqa: BLE001 - 清理失败必须降级
        logger.warning("[cleanup] %s 删除失败 %s: %s", label, path, e)
        return False
