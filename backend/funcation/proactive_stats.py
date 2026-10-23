"""主动性功能的**触发计数**（埋点）。

## 为什么独立文件而不是塞进 `system_config`

`system_config` 是"只保留已知键"的严格模式
（`{k: v for k, v in raw.items() if k in _FIELD_BY_KEY}`）—— 直接塞计数器
会被**静默丢弃**。而且语义不同：

- `system_config` = **配置**："我想让它怎样"（管理员偶尔改）
- 本模块 = **计数**："实际发生了什么"（**每次聊天都可能写**）

频率和风险都不同，混在一个文件里写不合适。

## 为什么需要它

这三个主动性功能的频率参数**只有理论值，从没基于真实数据定过**：

| 功能 | 参数 | 我实测到的矛盾信号 |
|---|---|---|
| E7 主动来电 | 30%/小时 + 每日 3 次 | 白天 15 小时命中 3 次（**正好打满上限**）→ 上限可能太松 |
| E8 群聊插嘴 | 25%/轮 | 4 条消息中 2 条插嘴（50%）→ **体感偏吵** |
| E11 活动邀请 | 25%/轮 + 好感度 ≥30 | 8 条才命中 1 次（≈12%）→ **可能约不出来** |

三个信号互相矛盾（一个太松、一个太吵、一个太低），说明**不能继续拍脑袋**。

## 存储结构

```json
{
  "activity_invitation": {
    "total": {"triggered": 6, "accepted": 2, "declined": 4},
    "daily": {"2026-10-23": {"triggered": 2, "accepted": 1}}
  }
}
```

- `total`：累计（看长期趋势）
- `daily`：按天（看"最近是不是变吵了"），**只留最近 7 天**，防止文件无限涨
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

#: 统计文件（和配置/数据同目录，被 .gitignore 覆盖）
STATS_FILE = os.path.join(
    os.environ.get("TREEHOLE_DATA_DIR", "data"), "proactive_stats.json"
)

#: daily 保留天数（再老的没意义，还会把文件撑大）
DAILY_KEEP_DAYS = 7

#: 已知的事件类型（**新增类型要加到这里**，防止拼写错误造出无限多的键）
KNOWN_KINDS = ("incoming_call", "group_interjection", "activity_invitation")


def today_str(now: Optional[datetime] = None) -> str:
    return (now or datetime.now()).strftime("%Y-%m-%d")


def record(kind: str, outcome: str, *, now: Optional[datetime] = None) -> bool:
    """记一次事件。返回是否真的记上了。

    ⚠️ **绝不抛** —— 它挂在聊天主链路上，统计失败绝不能影响回复。
    ⚠️ 未知 kind 记不上（返回 False）并打 warning —— 拼错字段名会造出
    无限多的垃圾键，宁可报错也不要静默接受。
    """
    if kind not in KNOWN_KINDS:
        logger.warning("[stats] 未知事件类型 %r（已忽略）", kind)
        return False
    if not outcome:
        return False

    try:
        try:
            data = _load()
        except FileNotFoundError:
            # 第一次计数，文件本来就不存在 —— 这是**正常情况**，不是失败
            data = {}
        day = today_str(now)

        entry = data.setdefault(kind, {})
        total = entry.setdefault("total", {})
        total[outcome] = int(total.get(outcome, 0)) + 1

        daily = entry.setdefault("daily", {})
        day_bucket = daily.setdefault(day, {})
        day_bucket[outcome] = int(day_bucket.get(outcome, 0)) + 1

        # 只留最近 N 天
        for old in sorted(daily.keys())[:-DAILY_KEEP_DAYS] if len(daily) > DAILY_KEEP_DAYS else []:
            daily.pop(old, None)

        _save(data)
        return True
    except (Exception, SystemExit) as e:  # noqa: BLE001 - 统计绝不能影响主链路
        logger.warning("[stats] 记录失败（忽略）: %s", e)
        return False


def snapshot() -> Dict[str, Any]:
    """读全部统计。文件不存在/损坏都返回空 dict（**不抛**，只读场景）。"""
    return _load_lenient()


def summary_lines() -> list[str]:
    """人话摘要（给 `/health` 或日志用）。"""
    data = _load_lenient()
    lines: list[str] = []
    for kind in KNOWN_KINDS:
        entry = data.get(kind) or {}
        total = entry.get("total") or {}
        if not total:
            continue
        parts = [f"{k}={v}" for k, v in sorted(total.items())]
        lines.append(f"{kind}: {' '.join(parts)}")
    return lines


# ── 内部 ────────────────────────────────────────────────────

def _load() -> Dict[str, Any]:
    """读统计。**文件坏时抛异常**，让调用方决定怎么办。

    ⚠️ 刻意不像 `system_config` 那样"坏了退回空 dict"：
    那是配置（退回默认行为是合理的），而这是**计数** ——
    静默退回空 dict 等于**静默清零**，用户丢了历史统计却毫无察觉。
    和 RAG 的误隔离一个模式：**静默失效是最贵的**。
    """
    with open(STATS_FILE, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    if not isinstance(raw, dict):
        raise ValueError(f"{STATS_FILE} 不是 JSON 对象")
    return raw


def _load_lenient() -> Dict[str, Any]:
    """读失败时返回空 dict（**只给 snapshot/summary 这类只读场景用**）。"""
    try:
        return _load()
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError, UnicodeDecodeError, ValueError) as e:
        logger.warning("[stats] %s 读取失败，按空统计处理: %s", STATS_FILE, e)
        return {}


def _save(data: Dict[str, Any]) -> None:
    """原子写（临时文件 + replace），避免写一半崩掉留下坏 JSON。"""
    os.makedirs(os.path.dirname(STATS_FILE) or ".", exist_ok=True)
    tmp = f"{STATS_FILE}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, STATS_FILE)
