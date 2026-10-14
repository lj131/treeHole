"""手动磁盘清理（跑完即删）。

启动时 `api.py` 的 lifespan 已经会跑一次（只清**超过保留期**的），
这个脚本是给"我想现在就清"用的。

用法（在 backend/ 目录）：
    ../.venv/Scripts/python.exe scripts/cleanup_disk.py              # 按默认 30 天
    ../.venv/Scripts/python.exe scripts/cleanup_disk.py --days 0     # 全清
    ../.venv/Scripts/python.exe scripts/cleanup_disk.py --dry-run    # 只看不删
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from funcation import disk_cleanup as dc  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="清理 backend/data 里的隔离残留目录与克隆日志")
    ap.add_argument("--days", type=int, default=dc.DEFAULT_RETENTION_DAYS,
                    help=f"保留期（天），默认 {dc.DEFAULT_RETENTION_DAYS}")
    ap.add_argument("--dry-run", action="store_true", help="只看会删什么，不真删")
    args = ap.parse_args()

    print("=== 当前隔离目录 ===")
    for d in dc.find_quarantine_dirs():
        age = (time.time() - d["mtime"]) / 86400
        print(f"  {d['name']:32s} {dc._human(d['size']):>7s}  {age:6.1f} 天前")

    active = os.path.join("data", dc.ACTIVE_CHROMA_DIR)
    print(f"\n活跃索引目录 {active} 不会被触碰")

    print(f"\n=== 清理（保留期 {args.days} 天{'，DRY RUN' if args.dry_run else ''}）===")
    result = dc.cleanup_quarantine_dirs(max_age_days=args.days, dry_run=args.dry_run)
    for name in result["removed"]:
        print(f"  {'将删除' if args.dry_run else '已删除'}  {name}")
    for name in result["kept"]:
        print(f"  保留      {name}（未超过保留期）")
    print(f"\n释放空间：{result['freed_human']}")

    log = os.path.join("data", "tmp", "clone", "worker.log")
    if os.path.exists(log):
        size = os.path.getsize(log)
        print(f"\nworker.log 当前 {dc._human(size)}"
              f"{'（超过阈值，会只留尾部）' if size > dc.WORKER_LOG_MAX_BYTES else '（未超阈值）'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
