"""长期记忆的时间轴：给记忆文本加一个日期前缀。

## 为什么是"前缀"而不是改数据结构

`long_memory` 在 `.rag.json` 里是 `list[str]`。改成 `list[{text, at}]` 要同步迁移
真源、`_index_to_rag`、导出、记忆编辑页和一堆测试 —— 收益一样，风险大一个数量级。
前缀方案零迁移：老数据没有前缀就保持原样，读取侧一句话兜住。

## 格式

```
（2026-10-30）我们约好明天下午三点去后勤处理漏水。
```

用 ISO 日期而不是「10月30日」：**跨年不歧义**，模型也能直接解析。
中文全角括号避免和正文里的英文括号混。

## 铁律

`update_long_memory` / `delete_long_memory` 原本按**文本完全相等**匹配。
加前缀后 LLM 返回的 `old_memory` 不会精确复现「（2026-10-30）」，
更新会**静默失败**。所以凡是"找一条记忆"的地方都必须走
`same_memory()`（剥掉前缀再比），不能直接用 `==` / `in`。
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional

# 只匹配**开头**的日期前缀，正文里出现同样的字串不受影响
DATE_PREFIX_RE = re.compile(r"^（(\d{4}-\d{2}-\d{2})）\s*")


def stamp(text: Any, now: Optional[datetime] = None) -> str:
    """给一条记忆加当天日期前缀。

    - 空文本 → 空串（调用方自行决定是否写入）
    - **已经有合法前缀就不再加**（重复写入/重新提取不会叠两层）
    - 已经是带日期的正文但格式不同 → 原样保留，交给调用方
    """
    body = str(text or "").strip()
    if not body:
        return ""
    if DATE_PREFIX_RE.match(body):
        return body
    day = (now or datetime.now()).strftime("%Y-%m-%d")
    return f"（{day}）{body}"


def strip_stamp(text: Any) -> str:
    """去掉开头的日期前缀，返回正文。没有前缀就原样返回。"""
    return DATE_PREFIX_RE.sub("", str(text or "").strip())


def prefix_of(text: Any) -> str:
    """返回形如 `（2026-10-30）` 的前缀；没有则空串。"""
    m = DATE_PREFIX_RE.match(str(text or "").strip())
    return m.group(0).rstrip() if m else ""


def date_of(text: Any) -> str:
    """返回 `2026-10-30`；没有前缀则空串。"""
    m = DATE_PREFIX_RE.match(str(text or "").strip())
    return m.group(1) if m else ""


def same_memory(a: Any, b: Any) -> bool:
    """**前缀无关**地比较两条记忆是不是同一条（按正文）。"""
    return strip_stamp(a) == strip_stamp(b)


def with_same_date(new_body: Any, reference: Any, now: Optional[datetime] = None) -> str:
    """把 `new_body` 套上 `reference` 的日期（用于"更新"：改内容但别改时间）。

    `reference` 没有前缀（老数据）→ 新条目也不加日期，避免把一条老记忆
    伪造成今天发生的。
    """
    prefix = prefix_of(reference)
    body = strip_stamp(new_body)
    if prefix:
        return f"{prefix}{body}"
    return body


# ============================================================
# 渲染层：把记忆里的相对时间"去活化"
# ============================================================
#
# 为什么需要：实测（2026-11-09）里，光靠一句"记忆里的时间是过去的"规则，
# 模型照样把老记忆中的「明天三点半后勤门口见」说成未来的约定
# （3 句里 2 句复发了）。**指令压不住一个看起来很具体的日程**。
#
# 所以不跟模型讲道理，直接让它看到的文本里就没有可直接执行的时间：
#   「明天三点半后勤门口见」→「当时的『明天』三点半后勤门口见」
# 模型读到的是**被引述的旧话**，不是一个待办事项。
#
# ⚠️ 只作用于给模型看的渲染结果，**绝不写真源** —— 可逆、零迁移。

RELATIVE_TIME_WORDS = (
    "明天", "后天", "明早", "明晚", "今早", "今晚", "今夜",
    "下周", "下个月", "待会儿", "待会", "一会儿", "等下", "回头",
)


def defuse_relative_time(text: Any) -> str:
    """把记忆里的相对时间词包成"当时的『X』"，避免被读成当前日程。"""
    body = str(text or "")
    for word in RELATIVE_TIME_WORDS:
        body = body.replace(word, f"当时的『{word}』")
    return body
