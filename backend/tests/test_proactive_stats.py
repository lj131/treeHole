"""主动性功能埋点计数。重点：**绝不抛**（挂主链路）、**未知类型记不上**、
**daily 只留 7 天**。"""
from datetime import datetime, timedelta

import pytest

from funcation import proactive_stats as ps


@pytest.fixture(autouse=True)
def _isolate_file(tmp_path, monkeypatch):
    """隔离到 tmp_path，绝不碰真实 data/proactive_stats.json"""
    f = tmp_path / "proactive_stats.json"
    monkeypatch.setattr(ps, "STATS_FILE", str(f))
    yield f


NOW = datetime(2026, 10, 23, 14, 40)


def test_record_increments_total_and_daily(_isolate_file):
    assert ps.record("activity_invitation", "triggered", now=NOW) is True
    assert ps.record("activity_invitation", "triggered", now=NOW) is True
    assert ps.record("activity_invitation", "accepted", now=NOW) is True

    snap = ps.snapshot()
    assert snap["activity_invitation"]["total"] == {"triggered": 2, "accepted": 1}
    assert snap["activity_invitation"]["daily"]["2026-10-23"] == {"triggered": 2, "accepted": 1}


def test_record_unknown_kind_is_rejected(_isolate_file):
    """**未知类型记不上** —— 拼错字段名会造出无限多的垃圾键"""
    assert ps.record("activty_invitation", "triggered") is False   # 拼错
    assert ps.record("", "triggered") is False
    assert ps.record("incoming_call", "") is False                 # 空 outcome
    assert ps.snapshot() == {}


def test_record_never_raises_on_bad_file(_isolate_file, monkeypatch):
    """**统计失败绝不影响主链路** —— 文件坏/不可写都要安静返回 False"""
    _isolate_file.write_text("{ 坏 JSON", encoding="utf-8")
    assert ps.record("incoming_call", "triggered") is False   # 读失败 → False，不抛

    # 不可写（把 STATS_FILE 指向一个目录）
    monkeypatch.setattr(ps, "STATS_FILE", str(_isolate_file.parent))
    assert ps.record("incoming_call", "triggered") is False


def test_daily_keeps_only_7_days(_isolate_file):
    """daily 只留最近 7 天（防止文件无限涨）"""
    for i in range(10):
        day = (NOW - timedelta(days=i)).strftime("%Y-%m-%d")
        ps.record("incoming_call", "triggered", now=datetime.strptime(day, "%Y-%m-%d"))

    daily = ps.snapshot()["incoming_call"]["daily"]
    assert len(daily) == ps.DAILY_KEEP_DAYS
    # 最早的那 3 天被丢掉
    oldest_kept = (NOW - timedelta(days=6)).strftime("%Y-%m-%d")
    assert oldest_kept in daily
    assert (NOW - timedelta(days=9)).strftime("%Y-%m-%d") not in daily


def test_total_survives_daily_pruning(_isolate_file):
    """**daily 被裁剪，但 total 不动** —— 否则"长期趋势"就没意义了"""
    for i in range(10):
        day = (NOW - timedelta(days=i)).strftime("%Y-%m-%d")
        ps.record("incoming_call", "triggered", now=datetime.strptime(day, "%Y-%m-%d"))
    assert ps.snapshot()["incoming_call"]["total"] == {"triggered": 10}


def test_snapshot_on_missing_file(_isolate_file):
    assert ps.snapshot() == {}


def test_summary_lines(_isolate_file):
    ps.record("activity_invitation", "triggered", now=NOW)
    ps.record("activity_invitation", "accepted", now=NOW)
    lines = ps.summary_lines()
    assert any("activity_invitation" in l and "triggered=1" in l for l in lines)
    # 没有数据的类型不出现在摘要里
    assert not any("incoming_call" in l for l in lines)


def test_known_kinds_cover_the_three_features():
    """三个要埋点的功能都必须在 KNOWN_KINDS 里"""
    for kind in ("incoming_call", "group_interjection", "activity_invitation"):
        assert kind in ps.KNOWN_KINDS
