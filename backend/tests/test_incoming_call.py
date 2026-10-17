"""主动来电决策。重点：**深夜不打**、**被拒绝后冷却**、**确定性**。"""
from datetime import datetime, timedelta

from funcation import incoming_call


NOW = datetime(2026, 10, 17, 15, 30)          # 下午，清醒时段
MIDNIGHT = datetime(2026, 10, 17, 3, 0)       # 凌晨


def mem(**record):
    return {"incoming_call": record} if record else {}


# ── 时段 ────────────────────────────────────────────────────

def test_never_at_late_night():
    """**凌晨/深夜绝不响** —— 这是最硬的约束"""
    for hour in (0, 1, 2, 3, 4, 22, 23):
        d = incoming_call.should_call(None, now=datetime(2026, 10, 17, hour, 0), seed="s")
        assert d.call is False
        assert d.reason


def test_can_call_during_day():
    """白天清醒时段可以打（有记录时也可，只要不违反冷却）"""
    d = incoming_call.should_call(mem(), now=NOW, seed="lucky")
    # seed 决定概率，这里只验证"不被时段拦"
    assert d.reason != "深夜，不该打扰"


# ── 冷却 ────────────────────────────────────────────────────

def test_decline_cooldown_blocks():
    """**被拒绝后 2 小时内不再打**"""
    d = incoming_call.should_call(
        mem(declined_at=(NOW - timedelta(minutes=30)).isoformat()),
        now=NOW, seed="lucky",
    )
    assert d.call is False
    assert "冷却" in d.reason


def test_decline_cooldown_expires():
    """超过 2 小时后允许再打（不被冷却拦）"""
    d = incoming_call.should_call(
        mem(declined_at=(NOW - timedelta(minutes=200)).isoformat()),
        now=NOW, seed="lucky",
    )
    assert "冷却" not in d.reason


def test_decline_cooldown_boundary():
    """边界：120 分钟整"""
    at_119 = incoming_call.should_call(
        mem(declined_at=(NOW - timedelta(minutes=119)).isoformat()), now=NOW, seed="lucky"
    )
    at_121 = incoming_call.should_call(
        mem(declined_at=(NOW - timedelta(minutes=121)).isoformat()), now=NOW, seed="lucky"
    )
    assert at_119.call is False
    assert at_121.call is True


def test_answered_cooldown_blocks():
    """刚接完不久不打"""
    d = incoming_call.should_call(
        mem(answered_at=(NOW - timedelta(minutes=10)).isoformat()), now=NOW, seed="lucky"
    )
    assert d.call is False
    assert "间隔" in d.reason


def test_answered_cooldown_boundary():
    at_29 = incoming_call.should_call(
        mem(answered_at=(NOW - timedelta(minutes=29)).isoformat()), now=NOW, seed="lucky"
    )
    at_31 = incoming_call.should_call(
        mem(answered_at=(NOW - timedelta(minutes=31)).isoformat()), now=NOW, seed="lucky"
    )
    assert at_29.call is False
    assert at_31.call is True


# ── 每日上限 ────────────────────────────────────────────────

def test_daily_cap():
    """硬上限：一天最多 3 次"""
    d = incoming_call.should_call(
        mem(calls_today=3, calls_today_date="2026-10-17"), now=NOW, seed="lucky"
    )
    assert d.call is False
    assert "3 次" in d.reason


def test_daily_cap_resets_next_day():
    """昨天的计数不该拦今天"""
    d = incoming_call.should_call(
        mem(calls_today=3, calls_today_date="2026-10-16"), now=NOW, seed="lucky"
    )
    assert d.call is True


# ── 确定性 / 概率 ───────────────────────────────────────────

def test_deterministic_same_seed():
    a = incoming_call.should_call(None, now=NOW, seed="fixed")
    b = incoming_call.should_call(None, now=NOW, seed="fixed")
    assert a == b


def test_not_every_time_calls():
    """**概率生效**：不同 seed 有打有不打"""
    results = {
        incoming_call.should_call(None, now=NOW, seed=f"s{i}").call for i in range(40)
    }
    assert True in results and False in results


def test_call_decision_has_greeting_hint():
    """该打时给 UI 一句招呼提示"""
    # 找一个必定命中的 seed
    for i in range(60):
        d = incoming_call.should_call(None, now=NOW, seed=f"k{i}")
        if d.call:
            assert d.reason
            assert d.greeting_hint
            break
    else:
        raise AssertionError("60 个 seed 里没有一次命中，概率实现有问题")


# ── 坏数据 ──────────────────────────────────────────────────

def test_bad_input_does_not_crash():
    assert incoming_call.should_call(None, now=NOW, seed="s").call in (True, False)
    assert incoming_call.should_call({}, now=NOW, seed="s").call in (True, False)
    assert incoming_call.should_call({"incoming_call": "bad"}, now=NOW, seed="s").call in (True, False)
    # 坏时间戳 → 当成"没有记录"，不被拦
    d = incoming_call.should_call(mem(declined_at="not-a-date"), now=NOW, seed="lucky")
    assert d.call is True


def test_default_now_works():
    """不传 now 用当前时间（不崩）"""
    d = incoming_call.should_call(None)
    assert isinstance(d.call, bool)


# ── 反馈记录 ────────────────────────────────────────────────

def test_answer_record_answered():
    r = incoming_call.build_answer_record("answered", NOW)
    assert r["last_action"] == "answered"
    assert r["answered_at"]
    assert "declined_at" not in r          # 只回本次字段（调用方 merge）


def test_answer_record_declined():
    r = incoming_call.build_answer_record("declined", NOW)
    assert r["last_action"] == "declined"
    assert r["declined_at"]
    assert "answered_at" not in r


def test_answer_record_rejects_unknown_action():
    """非法动作不写任何东西（也不抛）"""
    assert incoming_call.build_answer_record("whatever", NOW) == {}
    assert incoming_call.build_answer_record("", NOW) == {}


def test_note_call_made_counts_per_day():
    """计数按**当天**累加。真实写入总是 date+count 成对出现。"""
    assert incoming_call.note_call_made({}, NOW)["calls_today"] == 1
    today_pair = {"calls_today": 2, "calls_today_date": "2026-10-17"}
    assert incoming_call.note_call_made(today_pair, NOW)["calls_today"] == 3
    # 跨天归零
    yesterday = {"calls_today": 3, "calls_today_date": "2026-10-16"}
    assert incoming_call.note_call_made(yesterday, NOW)["calls_today"] == 1
    # 缺 date 的半个记录也归零（保守：不把旧计数算进今天）
    assert incoming_call.note_call_made({"calls_today": 2}, NOW)["calls_today"] == 1
    # None 不崩
    assert incoming_call.note_call_made(None, NOW)["calls_today"] == 1
