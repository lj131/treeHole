"""磁盘清理策略（P0 §3.2）。

**最重要的断言**：清理绝不许碰到活跃的 `data/chroma` ——
一个写错的前缀匹配就能把正在用的索引删掉，那是真丢数据。
其余都是普通行为测试：保留期、幂等、删不掉不抛。
"""
import os
import time

import pytest

from funcation import disk_cleanup as dc


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """造一个 data/ 目录：活跃 chroma + 几个不同年龄的隔离目录"""
    d = tmp_path / "data"
    d.mkdir()

    # 活跃索引（**绝不能被动**）
    active = d / dc.ACTIVE_CHROMA_DIR
    active.mkdir()
    (active / "chroma.sqlite3").write_bytes(b"x" * 5000)

    # 隔离目录：一个老（超期）、一个还在保留期内、一个不带隔离前缀（普通目录）
    old = d / "chroma_corrupt_1111111111"
    old.mkdir()
    (old / "a.bin").write_bytes(b"x" * 1000)

    recent = d / "chroma_corrupt_2222222222"
    recent.mkdir()
    (recent / "b.bin").write_bytes(b"x" * 2000)

    other = d / "chroma_backup_should_not_touch"
    other.mkdir()
    (other / "c.bin").write_bytes(b"x" * 3000)

    # 把老的改老一点、新的改新一点
    now = time.time()
    os.utime(old, (now - 40 * 86400, now - 40 * 86400))       # 40 天前
    os.utime(recent, (now - 3 * 86400, now - 3 * 86400))       # 3 天前

    monkeypatch.chdir(tmp_path)
    return d


# ============================================================
# 安全：绝不碰活跃索引
# ============================================================

def test_active_chroma_dir_is_never_removed(data_dir):
    """**核心安全断言** —— 清成什么样都不许把活跃索引删掉"""
    active = data_dir / dc.ACTIVE_CHROMA_DIR
    assert (active / "chroma.sqlite3").exists()

    # 保留期 0 天 = "全清"，这是最激进的情况
    dc.cleanup_quarantine_dirs(max_age_days=0)

    assert active.is_dir(), "活跃索引目录被删了"
    assert (active / "chroma.sqlite3").exists(), "活跃索引内容被删了"


def test_active_dir_not_even_listed(data_dir):
    """`find_quarantine_dirs` 就不该把活跃目录列出来（双保险）"""
    names = [d["name"] for d in dc.find_quarantine_dirs()]
    assert dc.ACTIVE_CHROMA_DIR not in names


def test_dirs_without_quarantine_prefix_are_left_alone(data_dir):
    """前缀白名单外的目录一个都不能动（比如 `chroma_backup_should_not_touch`）"""
    dc.cleanup_quarantine_dirs(max_age_days=0)
    assert (data_dir / "chroma_backup_should_not_touch" / "c.bin").exists()


# ============================================================
# 保留期
# ============================================================

def test_respects_retention_window(data_dir):
    """未超过保留期的不删"""
    result = dc.cleanup_quarantine_dirs(max_age_days=30)
    assert "chroma_corrupt_1111111111" in result["removed"]     # 40 天前 → 删
    assert "chroma_corrupt_2222222222" in result["kept"]        # 3 天前 → 留
    assert (data_dir / "chroma_corrupt_2222222222").is_dir()


def test_zero_retention_clears_everything_quarantine(data_dir):
    """保留期 0 = 全清隔离目录（但活跃目录仍在，见上面的安全断言）"""
    result = dc.cleanup_quarantine_dirs(max_age_days=0)
    assert set(result["removed"]) == {"chroma_corrupt_1111111111", "chroma_corrupt_2222222222"}
    assert not (data_dir / "chroma_corrupt_1111111111").exists()


def test_dry_run_does_not_delete(data_dir):
    """dry-run 一个字节都不许动"""
    result = dc.cleanup_quarantine_dirs(max_age_days=0, dry_run=True)
    assert "chroma_corrupt_1111111111" in result["removed"]
    assert (data_dir / "chroma_corrupt_1111111111").is_dir(), "dry-run 竟然真删了"


def test_freed_bytes_are_reported(data_dir):
    """报告释放了多少字节（用户要能看到效果）"""
    result = dc.cleanup_quarantine_dirs(max_age_days=0, dry_run=True)
    assert result["freed"] == 3000      # 1000 + 2000
    assert result["freed_human"]


def test_repeated_run_is_idempotent(data_dir):
    """跑两次结果一样（删掉的自然就没了）"""
    dc.cleanup_quarantine_dirs(max_age_days=0)
    second = dc.cleanup_quarantine_dirs(max_age_days=0)
    assert second["removed"] == []


# ============================================================
# 健壮性
# ============================================================

def test_cleanup_survives_deletion_failure(data_dir, monkeypatch):
    """删不掉（Windows 文件锁 / 环境的删除保护）只跳过，绝不抛"""
    def _boom(_p):
        raise PermissionError("被占了")

    monkeypatch.setattr(dc.shutil, "rmtree", _boom)
    result = dc.cleanup_quarantine_dirs(max_age_days=0)
    assert result["removed"] == []          # 没删成也不算删成功
    assert (data_dir / "chroma_corrupt_1111111111").is_dir()


def test_cleanup_handles_missing_data_dir(tmp_path, monkeypatch):
    """data/ 不存在 → 返回空，不抛"""
    monkeypatch.chdir(tmp_path)
    result = dc.cleanup_quarantine_dirs()
    assert result["removed"] == []


def test_startup_cleanup_never_raises(tmp_path, monkeypatch):
    """启动路径必须 best-effort —— 清理失败不该影响启动"""
    def _boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(dc, "cleanup_quarantine_dirs", _boom)
    monkeypatch.setattr(dc, "truncate_worker_log", _boom)
    dc.run_startup_cleanup()      # 不该抛


# ============================================================
# worker.log 轮转
# ============================================================

def _make_log(data_dir, size: int) -> str:
    path = data_dir / "tmp" / "clone" / "worker.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return str(path)


def test_worker_log_truncates_when_too_big(data_dir, monkeypatch):
    """只追加的日志超过阈值就只留尾部"""
    monkeypatch.chdir(data_dir.parent)
    _make_log(data_dir, dc.WORKER_LOG_MAX_BYTES + 10)
    path = os.path.join("data", "tmp", "clone", "worker.log")

    freed = dc.truncate_worker_log()

    assert freed > 0
    assert os.path.getsize(path) <= dc.WORKER_LOG_KEEP_BYTES


def test_worker_log_leaves_small_file_alone(data_dir, monkeypatch):
    """没超阈值就不动"""
    monkeypatch.chdir(data_dir.parent)
    _make_log(data_dir, 10_000)
    path = os.path.join("data", "tmp", "clone", "worker.log")
    before = os.path.getsize(path)

    assert dc.truncate_worker_log() == 0
    assert os.path.getsize(path) == before


def test_worker_log_truncation_keeps_whole_lines(data_dir, monkeypatch):
    """截断后别留半行（从第一个完整行开始）"""
    monkeypatch.chdir(data_dir.parent)
    path = data_dir / "tmp" / "clone" / "worker.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = (b"line a\n" * 100000)
    path.write_bytes(body)

    dc.truncate_worker_log()

    text = path.read_bytes()
    assert not text.startswith(b"a\n")          # 半行被切掉了
    assert text.endswith(b"\n") or b"\n" in text


# ============================================================
# 回归测试（2026-10-14 资深开发评审后补）
# ============================================================

def test_startup_cleanup_dry_run_does_not_touch_log(data_dir, monkeypatch):
    """**回归**：dry-run 必须**一路透传**到日志截断。

    原 bug：`run_startup_cleanup(dry_run=True)` 漏传给 `truncate_worker_log`，
    于是 dry-run 下隔离目录是"预演"，**日志却被真实截断了** ——
    "先看会删什么再动手"的承诺在日志这一项上不成立。
    """
    monkeypatch.chdir(data_dir.parent)
    log = data_dir / "tmp" / "clone" / "worker.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_bytes(b"A" * (dc.WORKER_LOG_MAX_BYTES + 500))
    before = log.read_bytes()

    dc.run_startup_cleanup(dry_run=True)

    assert log.read_bytes() == before, "dry-run 竟然动了日志"


#: 模拟 worker 后续写入的标记。bytes 字面量只允许 ASCII，所以用纯英文。
MSG_B = b"worker-append-after-truncate\n"


def test_truncate_keeps_inode_for_live_appender(data_dir, monkeypatch):
    """**回归**：必须原地 truncate，不能 tmp + replace。

    原 bug：replace 换文件。worker 是 `open(..., "ab")` **长驻追加**的：
    - POSIX：replace 后它的 fd 指向已 unlink 的旧 inode，之后日志写进黑洞
    - Windows：replace 被占用的文件直接 PermissionError，被吞后永远"截断失败"

    原地 truncate 保留 inode —— 用一个一直开着的 fd 模拟 worker。
    """
    monkeypatch.chdir(data_dir.parent)
    log = data_dir / "tmp" / "clone" / "worker.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_bytes(b"\n".join(b"line %d" % i for i in range(60000)) + b"\n")

    # 像 worker 那样长期持有追加 fd
    live = open(log, "ab")

    dc.truncate_worker_log()

    # 关键断言：worker 的 fd 依然有效（没变成指向黑洞的旧 inode）
    live.write(MSG_B)
    live.flush()
    assert MSG_B in log.read_bytes(), (
        "worker 的 fd 失效了 —— 日志写进了黑洞（replace 才会这样）"
    )
    live.close()


def test_find_quarantine_dirs_survives_missing_dir(data_dir, monkeypatch):
    """**回归**：列目录期间某个刚好被外部删掉，不能让整轮作废。

    原 bug：`os.path.getmtime` 裸调用，一个目录被删就 FileNotFoundError 冒泡，
    本该删的其它目录这一轮全被跳过。
    """
    monkeypatch.chdir(data_dir.parent)

    # 造两个隔离目录，然后让其中一个在 listdir 之后、getmtime 之前"消失"
    (data_dir / "chroma_corrupt_a").mkdir()
    (data_dir / "chroma_corrupt_b").mkdir()

    real_makedirs = dc.os.path.isdir

    calls = {"n": 0}

    def flaky_isdir(p):
        # 第二次调用时把 a 目录删掉（模拟并发消失）
        if calls["n"] == 1:
            import shutil

            shutil.rmtree(data_dir / "chroma_corrupt_a", ignore_errors=True)
        calls["n"] += 1
        return real_makedirs(p)

    monkeypatch.setattr(dc.os.path, "isdir", flaky_isdir)

    found = dc.find_quarantine_dirs()      # 不该抛

    names = [d["name"] for d in found]
    assert "chroma_corrupt_a" not in names, "已经消失的目录还在列表里"
    assert "chroma_corrupt_b" in names, "顺带把其它目录也漏掉了（整轮作废）"
