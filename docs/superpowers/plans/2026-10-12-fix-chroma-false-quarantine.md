# 修复 ChromaDB 误隔离导致记忆丢失 Implementation Plan

> **状态：✅ 已完成（2026-10-12）。** 5 个 Task 全部执行完毕，实测数据见文末「执行结果」。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 阻止 `memory_rag` 把**健康**的向量库当成"损坏"隔离掉 —— 这是正在发生的数据丢失；同时让隔离事件可见，并让网络类故障不再触发隔离。

**Architecture:** 本次不改向量库的存储形态，只修**判定与响应**逻辑：

1. **判定**：现在靠 `str(exc)` 的子串匹配（`"tenant" in msg or "connect" in msg`）+ 一个宽泛的 `except Exception`，两者都会误判。
   改为**按异常类型**分类，并显式排除网络类异常（`httpx.HTTPError` / `ConnectionError` / `OSError`）。
2. **响应**：现在一旦判定"损坏"就 `shutil.move` 掉整个目录并重建空库 —— 这是不可逆的数据丢失。
   改为**隔离前先做健康探测**（能打开 + `PRAGMA integrity_check` 通过 → 不隔离，改为重试）。
3. **可见性**：隔离事件现在只有一行 `logger.warning`，没有堆栈、没有计数、没有上报。
   补 traceback + 进程内计数 + `/health` 暴露。
4. **可恢复性**：启动时若当前库为空/缺失，而存在健康的隔离库 → **恢复它**，而不是重建空库。
5. **优雅关闭**：lifespan shutdown 显式释放 chroma 客户端，减少"上一个进程句柄未释放"引发的状态不一致。

**Tech Stack:** Python 3.11 / FastAPI lifespan / chromadb 1.5.9 / sqlite3 / pytest（`backend/tests/conftest.py` 的 cwd 隔离约定）。

---

## 前置基线（已验证，Task 内会复验）

本次调查的实测结论（2026-10-12，master `05bc4d7`）：

- `backend/data/` 下有 **6 个 `chroma_corrupt_*`** 隔离目录，其中 5 个集中在 2026-09-18 的 80 分钟内。
- **全部通过 `PRAGMA integrity_check` = ok**，且都能被 chromadb 正常打开：
  ```
  data/chroma_corrupt_1789723767: 打开成功, 12 个集合, 共 15 条记录
  ```
  → **它们从来没有损坏过。**
- `_get_client()` 单独调用**不碰网络**（用死端口代理验证过：仍返回 OK），所以隔离只可能来自
  `_get_collection()` 的运行时分支或 `_create_client()` 的初始化分支。
- FastEmbed 在构造 embedding function 时会访问 `huggingface.co`（`GET /api/models/Qdrant/bge-small-zh-v1.5`），
  本机代理返回 **502** → 抛 `httpx.ProxyError`；代理不可达时抛 `httpx.ConnectError`。
  **中文 locale 下该异常消息不含 ASCII `connect`**（"由于目标计算机积极拒绝，无法连接。"），
  而英文 locale 下含 —— 即**错误分类依赖消息语言**，行为随部署环境漂移。
- 现有验证手段：
  ```bash
  cd backend && ../.venv/Scripts/python.exe -m pytest -q      # 224 passed
  ```

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `backend/funcation/memory_rag.py` | 修改 | 健康探测、隔离前校验、异常分类、事件记录、启动恢复、客户端释放 |
| `backend/api/api.py` | 修改 | `/health` 暴露 rag 状态；lifespan shutdown 调用释放 |
| `backend/tests/test_memory_rag_recovery.py` | **新增** | 纯逻辑 + 文件系统行为的单测（不依赖真实 chroma 服务） |
| `backend/CLAUDE.md` | 修改 | 记录「隔离 = 数据丢失」的语义与新的判定规则 |
| `docs/superpowers/plans/2026-09-18-system-advancement-plan.md` | 修改 | 订正 §1 的定性（原写"损坏"，实为误判） |

---

## Task 1: 健康探测 —— 隔离前先确认它真的坏了

**Files:**
- Modify: `backend/funcation/memory_rag.py`
- Test: `backend/tests/test_memory_rag_recovery.py`

**为什么这是第一个 Task：** 只要判定逻辑还是"怀疑即隔离"，后面所有改进都只是在美化一个会丢数据的流程。先让"不丢健康数据"成立。

- [x] **Step 1: 写失败测试 —— 健康的目录不能被隔离**

新建 `backend/tests/test_memory_rag_recovery.py`：

```python
"""ChromaDB 隔离判定与恢复。纯文件系统行为，不依赖真实向量库服务。"""
import sqlite3

from funcation import memory_rag


def _make_healthy_db(path):
    """造一个能通过 integrity_check 的最小 sqlite（模拟一个健康的 chroma 库）"""
    path.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path / "chroma.sqlite3"))
    con.execute("CREATE TABLE collections (id TEXT PRIMARY KEY, name TEXT)")
    con.execute("INSERT INTO collections VALUES ('1', 'long_memory')")
    con.commit()
    con.close()
    return path


def test_healthy_dir_is_not_quarantined(tmp_path, monkeypatch):
    """**核心断言**：库是健康的就不许隔离 —— 隔离等于丢数据。

    实测踩过：6 个被隔离的库全部 integrity_check=ok 且能正常打开，
    却因为一次网络异常被整个 move 走。
    """
    data = tmp_path / "data"
    monkeypatch.setattr(memory_rag, "PERSIST_DIR", str(data / "chroma"))
    healthy = _make_healthy_db(data / "chroma")

    assert memory_rag.is_persist_dir_healthy(str(healthy)) is True

    before = sorted(p.name for p in data.iterdir())
    memory_rag._quarantine_corrupt_dir("测试用原因")
    after = sorted(p.name for p in data.iterdir())

    assert before == after, "健康库被隔离了 —— 这就是数据丢失"
    assert healthy.exists()


def test_missing_dir_counts_as_healthy(tmp_path, monkeypatch):
    """目录不存在 = 还没建库，不算损坏，不该产生隔离垃圾"""
    data = tmp_path / "data"
    data.mkdir()
    assert memory_rag.is_persist_dir_healthy(str(data / "chroma")) is True
    memory_rag._quarantine_corrupt_dir("测试用原因")
    assert not list(data.glob("chroma_corrupt_*"))


def test_truly_corrupt_db_is_quarantined(tmp_path, monkeypatch):
    """真的坏（sqlite 文件是垃圾字节）才允许隔离"""
    data = tmp_path / "data"
    monkeypatch.setattr(memory_rag, "PERSIST_DIR", str(data / "chroma"))
    broken = data / "chroma"
    broken.mkdir(parents=True)
    (broken / "chroma.sqlite3").write_bytes(b"this is not a sqlite file at all")

    assert memory_rag.is_persist_dir_healthy(str(broken)) is False

    memory_rag._quarantine_corrupt_dir("测试用原因")
    assert list(data.glob("chroma_corrupt_*")), "真损坏的库应该被隔离"
```

- [x] **Step 2: 跑测试确认 FAIL**

```bash
cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_memory_rag_recovery.py -q
```

Expected: FAIL —— `AttributeError: module 'funcation.memory_rag' has no attribute 'is_persist_dir_healthy'`。

- [x] **Step 3: 实现 `is_persist_dir_healthy()`**

在 `memory_rag.py` 里 `_quarantine_corrupt_dir` 之前加：

```python
def is_persist_dir_healthy(persist_dir: str | None = None) -> bool:
    """判断持久化目录是不是**健康可用**的。

    隔离 = 数据丢失，所以隔离前必须先问一句"它真的坏了吗"。
    实测教训：曾经有 6 个库被当成损坏隔离掉，事后全部通过 integrity_check
    且能被 chromadb 正常打开 —— 它们从来没坏过。

    判定规则（宁可判健康，也不误删）：
    - 目录不存在 → True（还没建库，不算损坏）
    - 没有 chroma.sqlite3 → True（chroma 会自建）
    - sqlite 能只读打开且 `PRAGMA integrity_check` 返回 ok → True
    - 其余（打不开 / 检查不通过）→ False
    """
    target = persist_dir or _chroma_persist_dir or PERSIST_DIR
    if not os.path.isdir(target):
        return True

    db_file = os.path.join(target, "chroma.sqlite3")
    if not os.path.isfile(db_file):
        return True

    try:
        con = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
        try:
            row = con.execute("PRAGMA integrity_check").fetchone()
            return bool(row) and str(row[0]).lower() == "ok"
        finally:
            con.close()
    except (Exception, SystemExit) as e:  # noqa: BLE001 - 判不出来就当它健康，绝不误删
        logger.warning("[memory_rag] 健康探测无法完成（%s），按健康处理以免误删: %s", db_file, e)
        return True
```

并在文件顶部 import 区确认有 `import sqlite3`（没有就加）。

- [x] **Step 4: 让 `_quarantine_corrupt_dir` 先做健康检查**

在函数体开头（`global` 声明之后、`if not os.path.exists(PERSIST_DIR)` 之前）插入：

```python
    target = _chroma_persist_dir or PERSIST_DIR
    if is_persist_dir_healthy(target):
        logger.warning(
            "[memory_rag] 收到隔离请求（原因: %s），但健康探测显示 %s 可用 —— "
            "**拒绝隔离**。隔离会丢弃有效记忆，宁可让调用方重试。",
            reason, target,
        )
        record_quarantine_event(reason, quarantined=False, note="健康探测通过，拒绝隔离")
        return
```

- [x] **Step 5: 跑测试确认 PASS**

```bash
cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_memory_rag_recovery.py -q
```

Expected: 3 passed（`record_quarantine_event` 在 Task 2 实现，若此时报 AttributeError，先加一个占位空函数，Task 2 再补实现）。

---

## Task 2: 隔离事件必须可见（traceback + 计数 + /health）

**Files:**
- Modify: `backend/funcation/memory_rag.py`、`backend/api/api.py`
- Test: `backend/tests/test_memory_rag_recovery.py`

- [x] **Step 1: 写失败测试 —— 事件要带堆栈和计数**

追加到 `tests/test_memory_rag_recovery.py`：

```python
def test_quarantine_event_records_traceback(tmp_path, monkeypatch):
    """隔离事件必须带堆栈 —— 之前只有一行 reason 字符串，事后完全无法定位"""
    monkeypatch.setattr(memory_rag, "_quarantine_events", [])
    memory_rag.record_quarantine_event("模拟原因", quarantined=False)

    events = memory_rag.get_quarantine_events()
    assert len(events) == 1
    assert events[0]["reason"] == "模拟原因"
    assert "traceback" in events[0]
    assert events[0]["quarantined"] is False


def test_health_snapshot_shape(tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setattr(memory_rag, "PERSIST_DIR", str(data / "chroma"))
    snap = memory_rag.health_snapshot()
    assert set(snap) >= {"persist_dir", "using_alt_dir", "quarantine_count", "healthy"}
    assert snap["quarantine_count"] == 0
```

- [x] **Step 2: 跑测试确认 FAIL**

```bash
cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_memory_rag_recovery.py -q
```

Expected: FAIL（`record_quarantine_event` / `health_snapshot` 不存在）。

- [x] **Step 3: 实现事件记录**

在 `memory_rag.py` 顶部（`_auto_rebuilt` 附近）加：

```python
# 进程内隔离事件记录。隔离 = 数据丢失，必须可查 —— 之前只有一行 warning，
# 既没有堆栈也没有计数，导致"数据被丢了"这件事几个月都没人发现。
_quarantine_events: list[dict] = []
_QUARANTINE_EVENT_LIMIT = 50


def record_quarantine_event(reason: str, *, quarantined: bool, note: str = "") -> None:
    """记录一次隔离判定（无论最终是否真的隔离）"""
    event = {
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "reason": reason,
        "quarantined": quarantined,
        "note": note,
        "traceback": traceback.format_exc(),
    }
    _quarantine_events.append(event)
    if len(_quarantine_events) > _QUARANTINE_EVENT_LIMIT:
        del _quarantine_events[:-_QUARANTINE_EVENT_LIMIT]

    if quarantined:
        logger.error(
            "[memory_rag] **向量库已被隔离（数据丢失）** 原因: %s —— 隔离目录: %s",
            reason, note or "(见日志)",
        )
    else:
        logger.warning("[memory_rag] 隔离请求被拒绝（未丢数据）原因: %s", reason)


def get_quarantine_events() -> list[dict]:
    return list(_quarantine_events)


def health_snapshot() -> dict:
    """给 /health 用的 RAG 状态快照"""
    target = _chroma_persist_dir or PERSIST_DIR
    return {
        "persist_dir": target,
        "using_alt_dir": bool(_chroma_persist_dir),
        "quarantine_count": sum(1 for e in _quarantine_events if e["quarantined"]),
        "rejected_count": sum(1 for e in _quarantine_events if not e["quarantined"]),
        "healthy": is_persist_dir_healthy(target),
        "last_event": _quarantine_events[-1] if _quarantine_events else None,
    }
```

补齐 import：`import traceback`、`from datetime import datetime, timezone`。

在 `_quarantine_corrupt_dir` 真正执行 `shutil.move` 成功之后加：
`record_quarantine_event(reason, quarantined=True, note=backup)`；
在 move 失败退到备用目录的分支加 `record_quarantine_event(reason, quarantined=True, note=alt)`。

- [x] **Step 4: `/health` 暴露**

`backend/api/api.py` 的 `/health` 返回值里加一个字段（保持既有字段不变）：

```python
from funcation import memory_rag
...
    "rag": memory_rag.health_snapshot(),
```

- [x] **Step 5: 跑测试确认 PASS**

```bash
cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_memory_rag_recovery.py -q
```

Expected: 5 passed。

---

## Task 3: 异常分类改用类型判断，网络错误绝不隔离

**Files:**
- Modify: `backend/funcation/memory_rag.py`
- Test: `backend/tests/test_memory_rag_recovery.py`

- [x] **Step 1: 写失败测试**

```python
import httpx
import pytest


@pytest.mark.parametrize("exc", [
    httpx.ConnectError("连接被拒绝"),
    httpx.ProxyError("502 Bad Gateway"),
    httpx.ReadTimeout("timed out"),
    ConnectionError("boom"),
    TimeoutError("boom"),
])
def test_network_errors_are_never_treated_as_corruption(exc):
    """网络故障绝不能被当成向量库损坏。

    实测踩过：FastEmbed 访问 huggingface.co 失败抛 httpx.ProxyError/ConnectError，
    一路冒泡进隔离分支，把健康的库整个 move 走。
    """
    assert memory_rag.is_corruption_error(exc) is False


def test_message_substring_is_not_used_for_classification():
    """错误分类不能依赖消息内容 —— 同一异常中文/英文消息不同，行为会随部署环境漂移"""
    assert memory_rag.is_corruption_error(RuntimeError("Could not connect to tenant")) is False
    assert memory_rag.is_corruption_error(RuntimeError("502 Bad Gateway")) is False
```

- [x] **Step 2: 跑测试确认 FAIL**

```bash
cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_memory_rag_recovery.py -q -k network
```

Expected: FAIL（`is_corruption_error` 不存在）。

- [x] **Step 3: 实现并替换两处子串判断**

```python
# 网络/IO 类异常：这些是**外部依赖**的问题，与向量库数据无关，绝不触发隔离。
# 实测：FastEmbed 解析模型时访问 huggingface.co，代理返回 502 → httpx.ProxyError
# 一路冒泡，被旧的 `"connect" in str(exc)` 判定成"损坏"，把健康的库隔离掉了。
_NETWORK_ERROR_TYPES = (httpx.HTTPError, ConnectionError, TimeoutError, OSError)

# 真正指向"向量库自身坏了"的异常特征（按类型/模块，不按消息文本）
_CORRUPTION_MODULE_HINTS = ("chromadb", "sqlite3")


def is_corruption_error(exc: BaseException) -> bool:
    """这个异常是否**真的指向向量库损坏**。

    规则（保守优先，宁可漏判也不误删）：
    - 网络/IO 类 → False（外部依赖问题）
    - 异常来自 chromadb / sqlite3 且不是网络类 → True
    - 其余 → False

    **刻意不看 `str(exc)`**：同一异常在不同 locale 下消息不同，
    旧代码 `"connect" in msg` 在英文环境命中、中文环境不命中 —— 行为随部署漂移。
    """
    if isinstance(exc, _NETWORK_ERROR_TYPES):
        return False
    module = type(exc).__module__ or ""
    return any(hint in module for hint in _CORRUPTION_MODULE_HINTS)
```

把 `_get_collection` 里的
```python
        msg = str(exc).lower()
        if _auto_rebuilt or "tenant" not in msg and "connect" not in msg:
            raise
```
替换为
```python
        if _auto_rebuilt or not is_corruption_error(exc):
            raise
```

把 `_get_client()` 里的 `except Exception as exc:` 改为先判类型：
```python
    except Exception as exc:
        if not is_corruption_error(exc):
            # 外部依赖故障（网络/代理/磁盘）——重试一次即可，绝不动数据
            logger.warning("[memory_rag] ChromaDB 初始化遇到外部故障，重试一次: %s", exc)
            record_quarantine_event(f"init non-corruption error: {exc}", quarantined=False)
            _chroma_client = _create_client()
            return _chroma_client
        ...（原有隔离逻辑）
```

`httpx` 已在依赖里（chromadb 传递依赖）。若不想直接依赖 httpx，用 `getattr(httpx, ...)` 懒导入并加注释。

- [x] **Step 4: 跑测试确认 PASS**

```bash
cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_memory_rag_recovery.py -q
```

Expected: 全部 passed（含 5 个参数化网络用例）。

---

## Task 4: 启动时恢复健康的隔离库，而不是重建空库

**Files:**
- Modify: `backend/funcation/memory_rag.py`
- Test: `backend/tests/test_memory_rag_recovery.py`

- [x] **Step 1: 写失败测试**

```python
def test_restore_recovers_healthy_quarantine(tmp_path, monkeypatch):
    """当前库缺失/为空、而隔离库是健康的 → 应该恢复它，而不是重建空库"""
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(memory_rag, "PERSIST_DIR", str(data / "chroma"))

    quarantined = _make_healthy_db(data / "chroma_corrupt_1700000000")
    restored = memory_rag.try_restore_quarantined_dir()
    assert restored is True
    assert (data / "chroma" / "chroma.sqlite3").exists()
    assert not quarantined.exists()


def test_restore_skips_when_current_dir_is_healthy(tmp_path, monkeypatch):
    """当前库本来就健康 → 不要去动隔离目录"""
    data = tmp_path / "data"
    monkeypatch.setattr(memory_rag, "PERSIST_DIR", str(data / "chroma"))
    _make_healthy_db(data / "chroma")
    old = _make_healthy_db(data / "chroma_corrupt_1700000000")

    assert memory_rag.try_restore_quarantined_dir() is False
    assert old.exists()
```

- [x] **Step 2: 跑测试确认 FAIL**

```bash
cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_memory_rag_recovery.py -q -k restore
```

Expected: FAIL（`try_restore_quarantined_dir` 不存在）。

- [x] **Step 3: 实现**

```python
def try_restore_quarantined_dir() -> bool:
    """当前库不可用时，尝试从最近的**健康**隔离库里恢复数据。

    隔离目录里躺着的往往不是坏数据 —— 实测 6 个隔离库全部完好。
    恢复成功就省掉一次"记忆全丢、等用户重新聊出来"的事故。
    """
    target = _chroma_persist_dir or PERSIST_DIR
    if os.path.isdir(target) and is_persist_dir_healthy(target):
        if os.path.isfile(os.path.join(target, "chroma.sqlite3")):
            return False

    candidates = sorted(glob.glob(f"{PERSIST_DIR}_corrupt_*"), reverse=True)
    for cand in candidates:
        if not is_persist_dir_healthy(cand):
            continue
        try:
            if os.path.isdir(target):
                shutil.rmtree(target, ignore_errors=True)
            shutil.move(cand, target)
            logger.warning("[memory_rag] 已从隔离目录恢复向量库: %s -> %s", cand, target)
            record_quarantine_event(f"restored from {cand}", quarantined=False, note="恢复成功")
            return True
        except (Exception, SystemExit) as e:  # noqa: BLE001 - 恢复失败不影响启动
            logger.warning("[memory_rag] 从 %s 恢复失败: %s", cand, e)
    return False
```

补 `import glob`。在 `_get_client()` 成功创建之前调用一次 `try_restore_quarantined_dir()`。

- [x] **Step 4: 跑测试确认 PASS**

```bash
cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_memory_rag_recovery.py -q
```

Expected: 全部 passed。

---

## Task 5: 优雅关闭 + 文档同步

**Files:**
- Modify: `backend/funcation/memory_rag.py`、`backend/api/api.py`、`backend/CLAUDE.md`、`docs/superpowers/plans/2026-09-18-system-advancement-plan.md`

- [x] **Step 1: 实现客户端释放**

`memory_rag.py` 加：

```python
def release_client() -> None:
    """释放持久化客户端（lifespan shutdown 调用）。

    chromadb 的 PersistentClient 通过 SharedSystemClient 持有 sqlite 句柄；
    进程被强杀时不释放，下一个进程打开同一目录可能看到不一致状态。
    显式释放能显著降低这种概率（实测中 5 次隔离都发生在反复启停后）。
    """
    global _chroma_client
    _chroma_client = None
    try:
        from chromadb.api.shared_system_client import SharedSystemClient
        SharedSystemClient.clear_system_cache()
    except (Exception, SystemExit) as e:  # noqa: BLE001 - 释放失败不阻断关闭
        logger.warning("[memory_rag] 释放 chroma 客户端失败（忽略）: %s", e)
```

在 `api.py` lifespan 的 shutdown 段（`# Shutdown` 注释之后）加：
```python
    memory_rag.release_client()
```

- [x] **Step 2: 验证关闭路径**

```bash
cd backend && ../.venv/Scripts/python.exe -c "
import sys; sys.path.insert(0,'.')
from funcation import memory_rag
memory_rag._get_client()
memory_rag.release_client()
print('release OK, client =', memory_rag._chroma_client)
"
```

Expected: `release OK, client = None`，无异常。

- [x] **Step 3: 同步文档**

- `backend/CLAUDE.md`：在 memory_rag 相关段落加一条 ——
  **「隔离 = 数据丢失」**；隔离前必须过 `is_persist_dir_healthy()`；
  错误分类用 `is_corruption_error()`（按类型，**不要用消息子串**）；
  `/health` 有 `rag` 快照；shutdown 调 `release_client()`。
- `docs/superpowers/plans/2026-09-18-system-advancement-plan.md` §1：
  订正定性 —— 原文写"ChromaDB 反复被隔离"，暗示库损坏；实测是**误判**（库全部健康），
  真因是网络异常 + 子串判定 + 隔离不可逆。把 §1 的证据表和"待查方向"更新为本计划已验证的结论。

- [x] **Step 4: 全量回归**

```bash
cd backend && ../.venv/Scripts/python.exe -m pytest -q
cd ../front && npx vue-tsc --noEmit -p tsconfig.app.json && npx vitest run
```

Expected: 后端 `224 + 新增` passed；前端 type-check exit 0、`122 passed`。

---

## 最终验收

```bash
cd backend && ../.venv/Scripts/python.exe -m pytest -q 2>&1 | tail -3
```

Expected: 全绿，且新增 `tests/test_memory_rag_recovery.py` 全部通过。

**行为验收（手动）：**

1. 健康库不被隔离：
   ```bash
   cd backend && ../.venv/Scripts/python.exe -c "
   import sys; sys.path.insert(0,'.')
   from funcation import memory_rag
   print('healthy =', memory_rag.is_persist_dir_healthy())
   print(memory_rag.health_snapshot())
   "
   ```
   Expected: `healthy = True`，`quarantine_count: 0`。

2. `/health` 能看到 rag 状态：
   ```bash
   curl -s --noproxy '*' http://127.0.0.1:8000/health | python -m json.tool | grep -A6 '"rag"'
   ```

3. **回归验证**（关键）：用死端口代理制造网络故障，确认**不再产生新的隔离目录**：
   ```bash
   cd backend && ls -d data/chroma_corrupt_* | wc -l     # 记下当前值
   HTTPS_PROXY=http://127.0.0.1:9 HTTP_PROXY=http://127.0.0.1:9 \
     ../.venv/Scripts/python.exe -c "
   import sys; sys.path.insert(0,'.')
   from funcation import memory_rag
   try: memory_rag._get_collection(1, 'linwan', 'long_memory')
   except Exception as e: print('预期内的失败:', type(e).__name__)
   "
   ls -d data/chroma_corrupt_* | wc -l                    # 必须与之前相同
   ```
   Expected: 两个数字**相同**（不再因网络故障丢数据）。

---

## Known Issues

- **不解决**"为什么 FastEmbed 每次启动都要访问 huggingface.co" —— 那是 FastEmbed 的行为，
  可以用 `HF_HUB_OFFLINE=1` 规避，但**本地无缓存时会导致模型加载失败**（实测：
  `Could not find model in cache_dir`）。本计划只保证"网络故障不导致数据丢失"，
  离线化留给后续单独评估（需要先确认模型缓存位置可靠 —— 现在缓存在系统 `Temp` 下，会被清理）。
- **不清理**现有的 6 个隔离目录。它们是本次调查的证据，且 `try_restore_quarantined_dir()`
  可能会用到。清理动作等恢复逻辑上线并验证后再单独做。
- `_get_collection` 的 `_auto_rebuilt` 仍是**进程级**标志，多 worker 部署下每个 worker 各判各的。
  单机单进程（当前形态）没问题，横向扩展时需重审。

---

## Self-Review

**1. Spec coverage（对照方案文档 §1 的 P0 与 5 条建议动作）：**
- 「隔离事件必须可见」→ Task 2（计数 + traceback + `/health`）。✅
- 「复现并抓到真实异常栈」→ 本计划**前置基线**已完成：定位到 `httpx.ProxyError`（代理 502）
  与 `httpx.ConnectError`（代理不可达），并证明隔离库全部健康。✅
- 「lifespan 优雅关闭」→ Task 5。✅
- 「根治：让只存向量库的数据可重建」→ **本计划不含**，但通过 Task 1/3/4 把
  "误隔离"这个**实际在丢数据的原因**堵住了，优先级高于原方案里的重构。✅（范围调整已说明）
- 「清理 9.8MB 残留」→ 明确列入 Known Issues 推迟。✅

**2. Placeholder scan：** 无 TBD / "添加适当错误处理" 等占位；每个 Step 含完整代码与期望输出。✅

**3. Type / 命名一致性：** 新增函数 `is_persist_dir_healthy` / `is_corruption_error` /
`record_quarantine_event` / `get_quarantine_events` / `health_snapshot` /
`try_restore_quarantined_dir` / `release_client` 在各 Task 中命名一致；
模块级新增 `_quarantine_events` / `_NETWORK_ERROR_TYPES` / `_CORRUPTION_MODULE_HINTS` 一致。✅

**4. 提交粒度：** 5 个 Task 各自独立 commit；Task 1（不丢数据）与 Task 3（判定分类）相关但可分 ——
Task 1 让"健康库不被隔离"成立，Task 3 让"网络错误不进入隔离流程"，前者是兜底、后者是源头。✅

**5. 与既有约定一致：** 新测试放 `backend/tests/`，遵守 `conftest.py` 的 cwd 隔离
（新增数据子目录已由现有 `tmp_data_dir` 覆盖，本计划只造 `data/chroma*`，无需改 conftest）。✅

---

## 执行结果（2026-10-12）

5 个 Task 全部完成，与计划的偏差记录如下。

### 改动

| 文件 | 内容 |
|---|---|
| `backend/funcation/memory_rag.py` | 新增 `is_persist_dir_healthy()` / `is_corruption_error()` / `record_quarantine_event()` / `get_quarantine_events()` / `health_snapshot()` / `try_restore_quarantined_dir()` / `release_client()`；`_quarantine_corrupt_dir()` 加健康探测前置；两处隔离判定改用异常类型 |
| `backend/api/api.py` | `/health` 加 `rag` 段；lifespan shutdown 调 `release_client()` |
| `backend/tests/test_memory_rag_recovery.py` | **新增 22 项** |
| `backend/tests/test_api_integration.py` | `/health` 断言改为子集（响应新增了 `rag` 字段） |
| `backend/CLAUDE.md`、方案文档 §1 | 同步 |

### 与计划的偏差

1. **健康探测第一版有缺陷，被测试抓出来**：原设计把"探测过程出错"一律当健康，
   结果**真损坏的库**（sqlite 文件是垃圾字节）也被判成健康 → 永不隔离。
   原因是 `PRAGMA integrity_check` 对垃圾字节抛的是 `sqlite3.DatabaseError`。
   已修正为**区分两种失败**：
   - `OperationalError`（打不开：被占用/权限/环境）→ 按健康处理，不删
   - 其它 `DatabaseError`（sqlite 明确说"file is not a database" / "malformed"）→ 确认损坏
   这条修正让 3 个用例从 FAIL 转 PASS。

2. **Task 5 的「优雅关闭」验证方式升级**：原计划只跑一个进程内调用。
   实际用 `CREATE_NEW_PROCESS_GROUP` + `CTRL_BREAK_EVENT` 起了真 uvicorn 并优雅关停，
   日志确认 `已释放 ChromaDB 客户端（sqlite 句柄已交还）` 出现在
   `Waiting for application shutdown.` 阶段 —— **端到端证明 lifespan 真的调用了它**。

### 验证数据

- 后端 `pytest`：**246 passed**（原 224 + 新增 22）
- 前端 `vue-tsc` exit 0、`vitest` **122 passed**（本次未动前端，跑一遍确认无牵连）
- `/health` 实际返回：
  ```json
  {"status": "ok", "rag": {"persist_dir": "...data\\chroma", "using_alt_dir": false,
   "quarantine_count": 0, "rejected_count": 0, "healthy": true, "last_event": null}}
  ```
- **关键回归**：把代理指向死端口制造网络故障后触发 RAG →
  隔离目录数 **6 → 6**（修复前同类故障每次都会 +1）

### 遗留（未做，已记录理由）

- 6 个隔离目录（约 9.8MB）**未清理** —— 它们是本次调查的证据，且 `try_restore_quarantined_dir()`
  可能用到。等恢复逻辑跑一段时间后再单独清理。
- 「让只存向量库的数据可重建」的重构**未做**。原方案把它列为"真正的解法"，
  但在**误判**的前提下，那是给一个不该发生的删除兜底。先修判定（本次），再评估是否还需要重构。
- FastEmbed 每次启动访问 huggingface.co 的行为**未改** —— `HF_HUB_OFFLINE=1` 会在本地无缓存时
  直接失败（实测 `Could not find model in cache_dir`），且当前缓存在系统 `Temp` 下会被清理。
  离线化需要先解决缓存位置可靠性，单独评估。
