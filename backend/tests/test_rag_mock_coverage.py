"""校验 `conftest.RAG_MUTATING_FUNCS` **双向覆盖**。

背景（踩过两次）：`upsert_memory` / `rebuild_collection_from_items` 刚加时
没进 conftest 的 mock 列表，跑一次全量测试就往**真实的开发库**写
（`PERSIST_DIR` 是绝对路径，不受 `tmp_data_dir` 的 chdir 隔离保护）。

这个测试就是防止第三次：
- **正向**：名单里每个名字都真实存在于 `memory_rag`（防拼错、防函数被删后名单失效）
- **反向**：用命名启发式扫 `memory_rag` 的公开函数，**新写函数必须已在名单里**
  （防将来新增又漏）
"""
import re

from funcation import memory_rag

import conftest

#: 名字像"会写/会破坏"的前缀。保守起见故意宽一点 —— 宁可多报让人来确认，
#: 也不要漏掉一个真写函数。
MUTATING_PREFIXES = re.compile(
    r"^(add|update|delete|upsert|rebuild|purge|record|restore|save|write|"
    r"remove|clear|reset|mark|set|insert|append|extend|pop|drop|create)_"
)


def test_listed_funcs_actually_exist():
    """**正向**：名单里的每个名字都必须真实存在（拼错/被删会在这里暴露）"""
    for name in conftest.RAG_MUTATING_FUNCS:
        assert hasattr(memory_rag, name), (
            f"RAG_MUTATING_FUNCS 里的 {name!r} 在 memory_rag 里不存在 "
            "（拼错了？还是函数被删了？）"
        )
    for name in conftest.RAG_READING_FUNCS:
        assert hasattr(memory_rag, name), f"RAG_READING_FUNCS 里的 {name!r} 不存在"


def test_no_unlisted_mutating_func():
    """**反向**：启发式扫出来的写函数必须已在名单里（防将来新增又漏）"""
    listed = set(conftest.RAG_MUTATING_FUNCS)
    unlisted = []
    for name in dir(memory_rag):
        if name.startswith("_"):
            continue
        if not MUTATING_PREFIXES.match(name):
            continue
        if not callable(getattr(memory_rag, name, None)):
            continue
        if name in listed:
            continue
        unlisted.append(name)

    assert not unlisted, (
        f"memory_rag 里有疑似写函数但没进 RAG_MUTATING_FUNCS: {unlisted}\n"
        "漏了它们，集成测试就会往真实开发库写数据。\n"
        "如果确认某个是纯读/无害的，把它加进 RAG_READING_FUNCS 或在名单里注明。"
    )


def test_dangerous_ones_are_covered():
    """两个**破坏性**操作必须在名单里（写文件 / rename 数据目录）"""
    for name in ("record_quarantine_event", "try_restore_quarantined_dir"):
        assert name in conftest.RAG_MUTATING_FUNCS, f"{name} 会写文件/改目录，必须被 mock"
