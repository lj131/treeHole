"""ChromaDB 隔离判定与恢复。

背景（2026-10-12 实测）：`backend/data/` 下有 6 个 `chroma_corrupt_*` 隔离目录，
**全部通过 `PRAGMA integrity_check` 且能被 chromadb 正常打开**（各 12 个集合、15 条记录）——
它们从来没坏过。真因是 FastEmbed 访问 huggingface.co 失败抛 `httpx.ProxyError` /
`httpx.ConnectError`，冒泡进隔离分支后把健康库整个 move 走。

本文件锁住"不再误隔离"这条底线。纯文件系统行为，不依赖真实向量库服务。
"""
import sqlite3

import pytest

from funcation import memory_rag


def _make_healthy_db(path):
    """造一个能通过 integrity_check 的最小 sqlite（模拟健康的 chroma 库）"""
    path.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path / "chroma.sqlite3"))
    con.execute("CREATE TABLE collections (id TEXT PRIMARY KEY, name TEXT)")
    con.execute("INSERT INTO collections VALUES ('1', 'long_memory')")
    con.commit()
    con.close()
    return path


@pytest.fixture(autouse=True)
def _reset_events(monkeypatch):
    """每个用例都从干净的事件表开始，避免互相污染"""
    monkeypatch.setattr(memory_rag, "_quarantine_events", [])


# ============================================================
# 健康探测
# ============================================================

def test_healthy_dir_is_not_quarantined(tmp_path, monkeypatch):
    """**核心断言**：库健康就不许隔离 —— 隔离等于丢数据"""
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
    monkeypatch.setattr(memory_rag, "PERSIST_DIR", str(data / "chroma"))

    assert memory_rag.is_persist_dir_healthy(str(data / "chroma")) is True
    memory_rag._quarantine_corrupt_dir("测试用原因")
    assert not list(data.glob("chroma_corrupt_*"))


def test_dir_without_sqlite_counts_as_healthy(tmp_path):
    """只有集合子目录、还没建 sqlite → chroma 会自建，不算损坏"""
    d = tmp_path / "chroma"
    (d / "some-collection").mkdir(parents=True)
    assert memory_rag.is_persist_dir_healthy(str(d)) is True


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


# ============================================================
# 隔离事件可见性
# ============================================================

def test_rejected_quarantine_is_recorded(tmp_path, monkeypatch):
    """被拒绝的隔离请求也要记下来 —— 否则"差点丢数据"这件事依然不可见"""
    data = tmp_path / "data"
    monkeypatch.setattr(memory_rag, "PERSIST_DIR", str(data / "chroma"))
    _make_healthy_db(data / "chroma")

    memory_rag._quarantine_corrupt_dir("模拟网络异常")

    events = memory_rag.get_quarantine_events()
    assert len(events) == 1
    assert events[0]["quarantined"] is False
    assert events[0]["reason"] == "模拟网络异常"
    assert "健康探测" in events[0]["note"]


def test_quarantine_event_records_traceback():
    """隔离事件必须带堆栈 —— 之前只有一行 reason 字符串，事后完全无法定位"""
    memory_rag.record_quarantine_event("模拟原因", quarantined=True, note="/tmp/backup")
    events = memory_rag.get_quarantine_events()
    assert len(events) == 1
    assert events[0]["quarantined"] is True
    assert events[0]["note"] == "/tmp/backup"
    assert "traceback" in events[0]


def test_event_list_is_capped():
    """事件表不能无限增长"""
    for i in range(memory_rag._QUARANTINE_EVENT_LIMIT + 20):
        memory_rag.record_quarantine_event(f"r{i}", quarantined=False)
    assert len(memory_rag.get_quarantine_events()) == memory_rag._QUARANTINE_EVENT_LIMIT


def test_health_snapshot_shape(tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setattr(memory_rag, "PERSIST_DIR", str(data / "chroma"))
    _make_healthy_db(data / "chroma")

    snap = memory_rag.health_snapshot()
    assert set(snap) >= {"persist_dir", "using_alt_dir", "quarantine_count", "healthy"}
    assert snap["quarantine_count"] == 0
    assert snap["healthy"] is True
    assert snap["last_event"] is None


def test_health_snapshot_counts_quarantine(tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setattr(memory_rag, "PERSIST_DIR", str(data / "chroma"))
    broken = data / "chroma"
    broken.mkdir(parents=True)
    (broken / "chroma.sqlite3").write_bytes(b"garbage")

    memory_rag._quarantine_corrupt_dir("真损坏")

    snap = memory_rag.health_snapshot()
    assert snap["quarantine_count"] == 1
    assert snap["last_event"]["quarantined"] is True


# ============================================================
# 异常分类：网络错误绝不等于数据损坏
# ============================================================

@pytest.mark.parametrize("exc", [
    ConnectionError("boom"),
    TimeoutError("boom"),
    OSError("disk full"),
])
def test_builtin_network_errors_are_not_corruption(exc):
    assert memory_rag.is_corruption_error(exc) is False


def test_httpx_errors_are_not_corruption():
    """实测真凶：FastEmbed 访问 huggingface.co 抛的就是这两种"""
    httpx = pytest.importorskip("httpx")
    for exc in (httpx.ConnectError("连接被拒绝"), httpx.ProxyError("502 Bad Gateway")):
        assert memory_rag.is_corruption_error(exc) is False


def test_classification_does_not_use_message_text():
    """错误分类不能依赖消息内容。

    旧代码 `"connect" in str(exc)` 在英文 locale 的 ConnectError 消息里命中、
    在中文 locale 的「无法连接」里不命中 —— 同一份代码行为随部署环境漂移。
    """
    assert memory_rag.is_corruption_error(RuntimeError("Could not connect to tenant")) is False
    assert memory_rag.is_corruption_error(RuntimeError("502 Bad Gateway")) is False
    assert memory_rag.is_corruption_error(RuntimeError("无法连接")) is False


def test_sqlite_corruption_is_detected():
    exc = sqlite3.DatabaseError("database disk image is malformed")
    assert memory_rag.is_corruption_error(exc) is True


def test_unrelated_errors_are_not_corruption():
    """业务错误（参数错之类）不该触发重建"""
    assert memory_rag.is_corruption_error(ValueError("bad parameter")) is False
    assert memory_rag.is_corruption_error(KeyError("missing")) is False


# ============================================================
# 从隔离目录恢复
# ============================================================

def test_restore_recovers_healthy_quarantine(tmp_path, monkeypatch):
    """当前库缺失、而隔离库健康 → 应该恢复它，而不是重建空库"""
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(memory_rag, "PERSIST_DIR", str(data / "chroma"))

    quarantined = _make_healthy_db(data / "chroma_corrupt_1700000000")

    assert memory_rag.try_restore_quarantined_dir() is True
    assert (data / "chroma" / "chroma.sqlite3").exists()
    assert not quarantined.exists(), "恢复应该是 move，不是 copy"


def test_restore_skips_when_current_dir_is_healthy(tmp_path, monkeypatch):
    """当前库本来就健康 → 不要去动隔离目录"""
    data = tmp_path / "data"
    monkeypatch.setattr(memory_rag, "PERSIST_DIR", str(data / "chroma"))
    _make_healthy_db(data / "chroma")
    old = _make_healthy_db(data / "chroma_corrupt_1700000000")

    assert memory_rag.try_restore_quarantined_dir() is False
    assert old.exists()


def test_restore_prefers_newest_healthy_candidate(tmp_path, monkeypatch):
    """多个候选时取最新的那个"""
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(memory_rag, "PERSIST_DIR", str(data / "chroma"))

    _make_healthy_db(data / "chroma_corrupt_1600000000")
    newest = _make_healthy_db(data / "chroma_corrupt_1700000000")

    assert memory_rag.try_restore_quarantined_dir() is True
    assert not newest.exists()


def test_restore_skips_corrupt_candidate(tmp_path, monkeypatch):
    """候选是坏的就不恢复，也不该抛异常"""
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(memory_rag, "PERSIST_DIR", str(data / "chroma"))

    bad = data / "chroma_corrupt_1700000000"
    bad.mkdir(parents=True)
    (bad / "chroma.sqlite3").write_bytes(b"garbage bytes")

    assert memory_rag.try_restore_quarantined_dir() is False


def test_restore_noop_when_nothing_to_restore(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(memory_rag, "PERSIST_DIR", str(data / "chroma"))
    assert memory_rag.try_restore_quarantined_dir() is False


# ============================================================
# 客户端释放
# ============================================================

def test_release_client_is_idempotent(monkeypatch):
    """关闭路径要能安全重复调用"""
    memory_rag.release_client()
    memory_rag.release_client()
    assert memory_rag._chroma_client is None
