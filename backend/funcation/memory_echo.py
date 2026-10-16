"""记忆回响 —— 挑出"该展示给用户看"的那几条召回结果。

## 要解决的问题

RAG 每轮都在召回长期记忆注入 prompt，但用户**完全看不见**。
陪伴类产品最核心的体验是"**被记住**" —— 这件事真实发生着，用户却感受不到。

## ⚠️ 措辞是设计决策，不是文案

**不写"她想起了你说过 XX"** —— 召回 ≠ 使用。
把记忆注入 prompt 不等于模型采纳了它。一旦用户发现"她说想起了 X 但我根本没说过 X"，
信任就没了。

用**「参考了 N 条记忆」**：准确、不撒谎，点开能看到具体内容让用户自己判断。
**诚实 > 煽情。**

## ⚠️ 三个实测结论（决定了实现方式）

1. `score` 是 **distance**（越小越相关），不是相似度
2. 分数区间**极窄**（实测 1.22 ~ 1.47）→ **不能用绝对阈值过滤**，只能相对排序取前 N
3. **不是所有集合都适合当"记忆回响"**（见 `_ECHO_COLLECTIONS`）
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

#: 只有这些集合能当"记忆回响"。
#:
#: 排除 `story` 和 `relationship` 的理由：它们是**剧情设定**和**关系状态**，
#: 不是"她记得你说过的事"。混进去会让用户看到一堆设定文本，
#: 反而看不出"被记住"这件事。
_ECHO_COLLECTIONS = frozenset({"long_memory", "profile", "events"})

#: 展示上限。太多会变成"记忆列表"，失去"回响"的轻量感。
DEFAULT_LIMIT = 3

#: 短于此长度的文本没有信息量（"用户姓名：未知" 之类）
_MIN_TEXT_LEN = 6

#: 这些占位词说明该条没有真实内容，展示出来只是噪音
_PLACEHOLDER_MARKERS = ("未知", "无变化", "暂无", "没有记录", "空")


def pick_echoes(
    retrieved: Optional[Iterable[Dict[str, Any]]],
    *,
    limit: int = DEFAULT_LIMIT,
) -> List[Dict[str, str]]:
    """从召回结果里挑出该展示的几条。

    返回 `[{"text": ..., "collection": ...}]` —— **不带 `score`**：
    前端不需要，而且把 distance 显示给用户只会造成误解（"1.2 是什么意思？"）。
    """
    if not retrieved:
        return []

    try:
        cap = max(1, int(limit))
    except (TypeError, ValueError):
        cap = DEFAULT_LIMIT

    candidates: List[tuple] = []
    for item in retrieved:
        if not isinstance(item, dict):
            continue
        collection = str(item.get("collection") or "")
        if collection not in _ECHO_COLLECTIONS:
            continue

        text = str(item.get("text") or "").strip()
        if not _is_meaningful(text):
            continue

        # score 是 distance：越小越相关。解析不了排到最后（而不是丢掉）。
        score = item.get("score")
        sort_key = score if isinstance(score, (int, float)) else float("inf")
        candidates.append((sort_key, text, collection))

    candidates.sort(key=lambda c: c[0])

    out: List[Dict[str, str]] = []
    seen = set()
    for _, text, collection in candidates:
        # 同一条记忆可能在多个集合里重复出现（不同 collection 权重不同）
        if text in seen:
            continue
        seen.add(text)
        out.append({"text": text, "collection": collection})
        if len(out) >= cap:
            break

    return out


def _is_meaningful(text: str) -> bool:
    """这条有没有真实内容可展示。"""
    if len(text) < _MIN_TEXT_LEN:
        return False
    # 占位词只在**文本很短**时才算噪音 —— "未知" 出现在长句里可能是有意义的叙述
    if len(text) < 20 and any(marker in text for marker in _PLACEHOLDER_MARKERS):
        return False
    return True


def echo_summary(echoes: Optional[Iterable[Dict[str, str]]]) -> str:
    """给 UI 用的一句话。空列表返回空串（前端据此不显示标记）。"""
    count = len(list(echoes or []))
    if count <= 0:
        return ""
    return f"参考了 {count} 条记忆"
