"""请求级记忆缓存（§3.4）。

## 要守的三条底线

1. **scope 内共享同一个 dict** —— 这是消灭 lost update 的关键
2. **scope 之间必须隔离** —— 用户 A 的请求绝不能看到用户 B 刚写的
3. **写透** —— save 之后磁盘上就是最新的（进程挂掉只丢正在写的那笔）
"""
import asyncio
import contextvars
import json

import pytest

from funcation.memory_center import MemoryCenter, memory_scope, with_memory_scope

USER = 1
CHAR = "linwan"


@pytest.fixture
def mc(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "memories" / str(USER)).mkdir(parents=True)
    return MemoryCenter()


# ============================================================
# 基本行为
# ============================================================

def test_same_dict_object_within_scope(mc):
    """**核心**：scope 内两次 load 返回**同一个对象** —— 别人改的我能看见"""
    with memory_scope():
        a = mc.load_memory(USER, CHAR)
        b = mc.load_memory(USER, CHAR)
        assert a is b


def test_outside_scope_returns_fresh_objects(mc):
    """scope 外行为不变（每次都是新读的）"""
    a = mc.load_memory(USER, CHAR)
    b = mc.load_memory(USER, CHAR)
    assert a is not b
    assert a == b


def test_write_through_to_disk(mc, tmp_path):
    """**写透**：save 后磁盘上立即是最新的（不是等 scope 结束才落盘）"""
    path = tmp_path / "data" / "memories" / str(USER) / f"{CHAR}.json"

    with memory_scope():
        mem = mc.load_memory(USER, CHAR)
        mem["favorability"] = 77
        mc.save_memory(USER, CHAR, mem)

        assert json.loads(path.read_text(encoding="utf-8"))["favorability"] == 77


def test_rag_store_participates_in_scope(mc):
    """`.rag.json` 同样走 scope（add_chat_summary 两次别读两次盘）"""
    with memory_scope():
        mc.add_chat_summary(USER, CHAR, "第一条")
        # 同一 scope 内的 .rag 读取看到刚写的
        assert mc.get_chat_summary(USER, CHAR) == ["第一条"]


def test_rag_written_through(mc, tmp_path):
    path = tmp_path / "data" / "memories" / str(USER) / f"{CHAR}.rag.json"
    with memory_scope():
        mc.add_chat_summary(USER, CHAR, "落盘验证")
        assert "落盘验证" in json.loads(path.read_text(encoding="utf-8"))["chat_summary"]


# ============================================================
# 正确性：消灭 lost update
# ============================================================

def test_no_lost_update_between_writers_in_scope(mc):
    """**这是本功能存在的理由**。

    两个"写者"（模拟聊天流程和后台 agent）在同一个 scope 里先后
    load→改→save，互不覆盖 —— 因为它们拿到的是同一个 dict。
    """
    with memory_scope():
        # 写者 A：改好感度
        mem_a = mc.load_memory(USER, CHAR)
        mem_a["favorability"] = 60
        mc.save_memory(USER, CHAR, mem_a)

        # 写者 B：改心情（模拟另一个 agent，用的是它自己 load 的快照）
        mem_b = mc.load_memory(USER, CHAR)
        mem_b.setdefault("character_state", {})["mood"] = "开心"
        mc.save_memory(USER, CHAR, mem_b)

    final = mc.load_memory(USER, CHAR)
    assert final["favorability"] == 60, "A 的写入被 B 覆盖了（lost update）"
    assert final["character_state"]["mood"] == "开心"


def test_concurrent_writer_before_scope_still_visible(mc):
    """scope 开始**前**磁盘上的数据要能读到（缓存不是从零开始）"""
    mem = mc.load_memory(USER, CHAR)
    mem["favorability"] = 50
    mc.save_memory(USER, CHAR, mem)

    with memory_scope():
        assert mc.load_memory(USER, CHAR)["favorability"] == 50


# ============================================================
# 隔离
# ============================================================

def test_scopes_are_isolated(mc):
    """**另一个 scope 看不到这个 scope 的未落盘外的修改** —— 用户间互不串扰"""
    with memory_scope():
        mem = mc.load_memory(USER, CHAR)
        mem["favorability"] = 88
        mc.save_memory(USER, CHAR, mem)

    # 新 scope 从磁盘重新读（拿到的是落盘后的值 —— 写透保证了一致）
    with memory_scope():
        assert mc.load_memory(USER, CHAR)["favorability"] == 88

    # scope 外同样
    assert mc.load_memory(USER, CHAR)["favorability"] == 88


def test_separate_scopes_do_not_share_unsaved_state(mc):
    """两个并行 scope（模拟两个请求）各自的缓存互不可见"""
    with memory_scope():
        a = mc.load_memory(USER, CHAR)
        a["favorability"] = 11

    with memory_scope():
        b = mc.load_memory(USER, CHAR)
        # a 没 save，b 不能看到 a 的内存态
        assert b.get("favorability") != 11


# ============================================================
# 线程/executor 传播
# ============================================================

def test_scope_visible_inside_copied_context_thread(mc):
    """**关键**：`run_in_executor` 不继承 ContextVar，
    必须用 `copy_context().run` 传播 —— 否则一半走缓存一半读盘，互相覆盖。"""
    seen = {}

    def _worker():
        # 模拟线程池里跑的记忆读写（api.py 的 in_executor 就是这么传播的）
        mem = mc.load_memory(USER, CHAR)
        mem["favorability"] = 99
        mc.save_memory(USER, CHAR, mem)
        seen["from_worker"] = mc.load_memory(USER, CHAR)["favorability"]

    async def main():
        loop = asyncio.get_event_loop()
        with memory_scope():
            # 主协程先 load 一次（建立缓存）
            mc.load_memory(USER, CHAR)
            # 模拟 api.py 的 in_executor：copy_context().run
            await loop.run_in_executor(None, contextvars.copy_context().run, _worker)
            # 主协程必须能看到线程里的写入（同一个 dict）
            assert mc.load_memory(USER, CHAR)["favorability"] == 99

    asyncio.run(main())
    assert seen["from_worker"] == 99


# ============================================================
# 装饰器
# ============================================================

def test_decorator_wraps_sync_and_async(mc):
    """`with_memory_scope` 对同步/异步函数都生效，且保留签名（FastAPI 依赖解析靠它）"""
    import inspect

    @with_memory_scope
    def sync_view():
        # 装饰器自建 scope：同一调用里两次 load 必须是同一个对象
        a = mc.load_memory(USER, CHAR)
        b = mc.load_memory(USER, CHAR)
        return a is b

    @with_memory_scope
    async def async_view():
        a = mc.load_memory(USER, CHAR)
        b = mc.load_memory(USER, CHAR)
        return a is b

    assert sync_view() is True
    assert asyncio.run(async_view()) is True

    # 签名穿透（FastAPI 靠这个解析 Depends）
    def view_with_dep(x: int = 3):
        return x

    wrapped = with_memory_scope(view_with_dep)
    assert list(inspect.signature(wrapped).parameters) == ["x"]


def test_scope_state_does_not_leak_after_exit(mc):
    """scope 退出后 ContextVar 复位 —— 不能把上一个请求的缓存漏给下一个"""
    with memory_scope():
        mc.load_memory(USER, CHAR)

    from funcation.memory_center import _memory_scope

    assert _memory_scope.get() is None
