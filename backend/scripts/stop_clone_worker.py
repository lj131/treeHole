"""把克隆引擎的守护进程停掉。

worker 是**故意**脱离后端进程的（这样后端重启不用重新加载 30 秒的模型），
代价是没有父进程能顺手回收它。所以需要一个显式停止入口。

它自己也会按 `VOICE_CLONE_IDLE_EXIT`（默认 20 分钟）空闲退出；
本脚本是"我想现在就停"用的。

用法（在仓库根目录）：
    .venv/Scripts/python.exe backend/scripts/stop_clone_worker.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from funcation import voice_clone as vc  # noqa: E402


async def main() -> int:
    ep = os.path.join(vc.WORKER_CWD, "data", "tmp", "clone", "worker.json")
    if not os.path.isfile(ep):
        print("没有在跑的 worker（端点文件不存在）")
        return 0
    try:
        with open(ep, encoding="utf-8") as fh:
            info = json.load(fh)
    except (OSError, ValueError):
        print("端点文件坏了，直接删掉")
        vc._try_remove(ep)
        return 0

    print(f"正在停止 worker pid={info.get('pid')} port={info.get('port')} ...")
    ok = await vc.engine.shutdown_worker()
    await asyncio.sleep(0.5)
    if os.path.isfile(ep):
        # worker 没来得及清理端点文件（比如被强杀），补一刀
        vc._try_remove(ep)
    print("已停止" if ok else "worker 没有响应（可能已经退出了）")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
