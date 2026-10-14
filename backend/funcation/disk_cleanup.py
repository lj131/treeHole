"""磁盘清理策略。

## 背景

`backend/data/` 被 `.gitignore`，所以它一直在长也**没人会注意到**。
实测（2026-10-14）454MB，其中：

| 项 | 体积 | 性质 |
|---|---|---|
| `data/openvoice/` | 432M | 模型权重，**故意留着**（重新下要 480MB 流量） |
| `data/chroma/` | 9.3M | 活跃索引，**绝不能删** |
| `chroma_corrupt_*` + `chroma_new` | 12M | 历史误隔离的残留 |
| `data/tmp/clone/worker.log` | 105K | 克隆 worker 的日志，**只追加不轮转** |

## 为什么现在才敢清理隔离目录

2026-10-14 之前，`long_memory`/`events`/`chat_summary` **只存在于向量库**，
隔离目录是"可能还有救"的最后一份数据，删了就是真没了。
真源统一到 `data/memories/*.rag.json` 之后，向量库**只是可重建的索引**
（见 `memory_center` 的 docstring），隔离目录才变成纯粹的垃圾。

## 安全约束（改这个模块前先读）

1. **绝不碰 `data/chroma`** —— 那是活跃索引。用白名单前缀匹配，不做模糊删除。
2. **按保留期删**，不是"见到就删"。默认 30 天，给"事后还想翻一下"留窗口。
3. **best-effort**：删不掉就跳过（Windows 文件锁、CLI shim 拦 `os.remove`），
   绝不因为清理失败而影响启动。
4. **有 dry-run**，先看会删什么再动手。
"""
from __future__ import annotations

import logging
import os
import shutil
import time
from typing import Any

logger = logging.getLogger(__name__)

#: 隔离目录的**前缀白名单**。只删这些，绝不做模糊匹配 ——
#: 一个写错的 glob 就能把 data/chroma 连带删掉。
QUARANTINE_PREFIXES = ("chroma_corrupt_", "chroma_new")

#: 活跃索引目录名，显式排除（双保险）
ACTIVE_CHROMA_DIR = "chroma"

#: 默认保留期（天）
DEFAULT_RETENTION_DAYS = 30

#: worker.log 超过这个大小就截断（只留尾部）
WORKER_LOG_MAX_BYTES = 1_000_000

#: 截断后保留的尾部大小
WORKER_LOG_KEEP_BYTES = 200_000


def _human(n: float) -> str:
    for unit in ("B", "K", "M", "G"):
        if abs(n) < 1024:
            return f"{n:.0f}{unit}"
        n /= 1024
    return f"{n:.1f}T"


def find_quarantine_dirs(data_dir: str = "data") -> list[dict]:
    """列出隔离目录（按 mtime 从旧到新）。返回 [{path, name, mtime, size}]"""
    if not os.path.isdir(data_dir):
        return []
    found = []
    for name in os.listdir(data_dir):
        if name == ACTIVE_CHROMA_DIR:
            continue
        if not name.startswith(QUARANTINE_PREFIXES):
            continue
        path = os.path.join(data_dir, name)
        if not os.path.isdir(path):
            continue
        size = 0
        for root, _dirs, files in os.walk(path):
            for f in files:
                try:
                    size += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
        found.append({
            "path": path,
            "name": name,
            "mtime": os.path.getmtime(path),
            "size": size,
        })
    found.sort(key=lambda x: x["mtime"])
    return found


def cleanup_quarantine_dirs(
    data_dir: str = "data",
    max_age_days: int = DEFAULT_RETENTION_DAYS,
    dry_run: bool = False,
) -> dict:
    """删掉超过保留期的隔离目录。返回统计。

    **不会碰 `data/chroma`**（活跃索引）。
    """
    cutoff = time.time() - max_age_days * 86400
    dirs = find_quarantine_dirs(data_dir)

    removed, kept, freed = [], [], 0
    for d in dirs:
        if d["mtime"] > cutoff:
            kept.append(d)
            continue
        if dry_run:
            removed.append(d)
            freed += d["size"]
            continue
        try:
            shutil.rmtree(d["path"])
            removed.append(d)
            freed += d["size"]
            logger.info("[cleanup] 删除隔离目录 %s（%s）", d["name"], _human(d["size"]))
        except (Exception, SystemExit) as e:  # noqa: BLE001
            # 删不掉不算错：可能是 Windows 文件锁，也可能是环境的删除保护
            logger.warning("[cleanup] 删除 %s 失败（跳过）：%s", d["name"], e)

    return {
        "removed": [d["name"] for d in removed],
        "kept": [d["name"] for d in kept],
        "freed": freed,
        "freed_human": _human(freed),
        "dry_run": dry_run,
    }


def truncate_worker_log(
    data_dir: str = "data",
    max_bytes: int = WORKER_LOG_MAX_BYTES,
    keep_bytes: int = WORKER_LOG_KEEP_BYTES,
) -> int:
    """克隆 worker 的日志超过阈值就只留尾部。返回释放的字节数（0 = 没动）。

    那个日志是**只追加**的（`open(..., "ab")`），worker 每次重启都往里写，
    不轮转的话会一直长。
    """
    path = os.path.join(data_dir, "tmp", "clone", "worker.log")
    try:
        size = os.path.getsize(path)
    except OSError:
        return 0
    if size <= max_bytes:
        return 0

    try:
        with open(path, "rb") as f:
            f.seek(-keep_bytes, os.SEEK_END)
            tail = f.read()
        # 从第一个完整行开始，免得留半行
        nl = tail.find(b"\n")
        if nl != -1:
            tail = tail[nl + 1 :]
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(tail)
        os.replace(tmp, path)
    except (Exception, SystemExit) as e:  # noqa: BLE001
        logger.warning("[cleanup] 截断 worker.log 失败（跳过）：%s", e)
        return 0

    freed = size - len(tail)
    logger.info("[cleanup] 截断 worker.log：%s → %s", _human(size), _human(len(tail)))
    return freed


def run_startup_cleanup(data_dir: str = "data", dry_run: bool = False) -> dict:
    """启动时跑一次。**绝不抛** —— 清理失败不该影响启动。"""
    result: dict[str, Any] = {"quarantine": {}, "worker_log_freed": 0}
    try:
        result["quarantine"] = cleanup_quarantine_dirs(data_dir, dry_run=dry_run)
    except (Exception, SystemExit) as e:  # noqa: BLE001
        logger.warning("[cleanup] 隔离目录清理失败（忽略）：%s", e)
    try:
        result["worker_log_freed"] = truncate_worker_log(data_dir)
    except (Exception, SystemExit) as e:  # noqa: BLE001
        logger.warning("[cleanup] 日志截断失败（忽略）：%s", e)
    return result
