"""活动邀请决策。重点：**好感度门槛**、**不重复**、**拒绝冷却**。"""
from datetime import datetime, timedelta

import pytest

from funcation import activity_invite


NOW = datetime(2026, 10, 20, 15, 30)      # 下午，合适时段
NIGHT = datetime(2026, 10, 20, 2, 0)      # 凌晨


def mem(**kw):
    d = dict(kw)
    return d


def with_record(**rec):
    return {"activity_invitation": rec}


# ── 不重复 / 冷却 ───────────────────────────────────────────

def test_pending_invitation_blocks_new_one():
    """**已有 pending 邀请时不再约**（用户还没答呢）"""
    d = activity_invite.should_invite(
        with_record(status="pending", activity="摄影展"), now=NOW, seed="lucky"
    )
    assert d.invite is False
    assert d.reason


def test_declined_within_cooldown_blocks():
    """**被拒绝后 3 天内不再约**"""
    d = activity_invite.should_invite(
        with_record(status="declined", declined_at=(NOW - timedelta(days=1)).isoformat()),
        now=NOW, seed="lucky",
    )
    assert d.invite is False
    assert "冷却" in d.reason


def test_declined_cooldown_expires():
    d = activity_invite.should_invite(
        {**with_record(status="declined",
                       declined_at=(NOW - timedelta(days=4)).isoformat()),
         "favorability": 80},
        now=NOW, seed="lucky",
    )
    assert d.invite is True


def test_decline_cooldown_boundary():
    at_2d = activity_invite.should_invite(
        {**with_record(status="declined",
                       declined_at=(NOW - timedelta(days=2, hours=23)).isoformat()),
         "favorability": 80},
        now=NOW, seed="lucky",
    )
    at_3d = activity_invite.should_invite(
        {**with_record(status="declined",
                       declined_at=(NOW - timedelta(days=3, hours=1)).isoformat()),
         "favorability": 80},
        now=NOW, seed="lucky",
    )
    assert at_2d.invite is False
    assert at_3d.invite is True


def test_accepted_also_cooldowns():
    """接受后也不该立刻再约一个（一次一个）"""
    d = activity_invite.should_invite(
        with_record(status="accepted", activity="摄影展"),
        now=NOW, seed="lucky",
    )
    assert d.invite is False


# ── 好感度门槛 ──────────────────────────────────────────────

def test_low_favorability_blocks():
    """**好感度不够不约**（不熟就约太突兀）"""
    d = activity_invite.should_invite(mem(favorability=20), now=NOW, seed="lucky")
    assert d.invite is False
    assert "好感度" in d.reason


def test_favorability_boundary():
    at_29 = activity_invite.should_invite(mem(favorability=29), now=NOW, seed="lucky")
    at_30 = activity_invite.should_invite(mem(favorability=30), now=NOW, seed="lucky")
    assert at_29.invite is False
    assert at_30.invite is True


def test_missing_favorability_is_conservative():
    """没有 favorability 字段 → 当 0 处理（保守：不约）"""
    d = activity_invite.should_invite({}, now=NOW, seed="lucky")
    assert d.invite is False


def test_bad_favorability_type():
    """字符串/None → 0（不崩、不约）"""
    assert activity_invite.should_invite(mem(favorability="abc"), now=NOW, seed="l").invite is False
    assert activity_invite.should_invite(mem(favorability=None), now=NOW, seed="l").invite is False


# ── 时段 ────────────────────────────────────────────────────

def test_no_invite_at_night():
    """深夜不约人"""
    for hour in (0, 1, 2, 3, 4, 22, 23):
        d = activity_invite.should_invite(
            mem(favorability=80), now=datetime(2026, 10, 20, hour, 0), seed="lucky"
        )
        assert d.invite is False


def test_invite_during_day_ok():
    d = activity_invite.should_invite(mem(favorability=80), now=NOW, seed="lucky")
    assert d.invite is True
    assert d.reason


# ── 概率 / 确定性 ───────────────────────────────────────────

def test_chance_is_real():
    results = {activity_invite.should_invite(mem(favorability=80), now=NOW, seed=f"s{i}").invite
               for i in range(40)}
    assert True in results and False in results


def test_deterministic():
    a = activity_invite.should_invite(mem(favorability=80), now=NOW, seed="fixed")
    b = activity_invite.should_invite(mem(favorability=80), now=NOW, seed="fixed")
    assert a == b


def test_seed_by_content_gives_varied_results():
    """**seed 用内容 hash**：不同消息应有不同判定（同 E8 教训）"""
    hits = sum(
        1 for i in range(20)
        if activity_invite.should_invite(mem(favorability=80), now=NOW, seed=f"hash{i}").invite
    )
    assert 0 < hits < 20  # 既不全中也不全不中


# ── 坏输入 ──────────────────────────────────────────────────

def test_bad_input_does_not_crash():
    assert activity_invite.should_invite(None, now=NOW, seed="s").invite in (True, False)
    assert activity_invite.should_invite({}, now=NOW, seed="s").invite in (True, False)
    assert activity_invite.should_invite(
        {"activity_invitation": "bad"}, now=NOW, seed="s"
    ).invite in (True, False)
    # 坏时间戳 → 当没有记录
    d = activity_invite.should_invite(
        {**with_record(status="declined", declined_at="not-a-date"),
         "favorability": 80},
        now=NOW, seed="lucky"
    )
    assert d.invite is True


def test_default_now_works():
    d = activity_invite.should_invite(mem(favorability=80))
    assert isinstance(d.invite, bool)


# ── answer 记录 ─────────────────────────────────────────────

def test_answer_record_accepted():
    r = activity_invite.build_answer_record("accepted", NOW)
    assert r["status"] == "accepted"
    assert r["answered_at"]
    assert "declined_at" not in r          # 只回本次字段
    # 接受时必须算出**绝对时间**，之后判断"到点没有"只靠它
    assert r["scheduled_at"]
    assert r["delay_hours"] == activity_invite.DEFAULT_DELAY_HOURS


def test_answer_record_uses_when_hours():
    r = activity_invite.build_answer_record("accepted", NOW, when_hours=6)
    assert r["delay_hours"] == 6
    assert r["scheduled_at"] == (NOW + timedelta(hours=6)).isoformat()


def test_answer_record_clamps_bad_when_hours():
    """非法/越界 → 回退默认值（不能变成"立刻就去"或十年后）"""
    for bad in (None, 0, -5, 500, "abc", True):
        r = activity_invite.build_answer_record("accepted", NOW, when_hours=bad)
        assert r["delay_hours"] == activity_invite.DEFAULT_DELAY_HOURS, f"{bad!r}"


def test_answer_record_declined():
    r = activity_invite.build_answer_record("declined", NOW)
    assert r["status"] == "declined"
    assert r["declined_at"]                # 冷却靠它


def test_answer_record_rejects_unknown():
    assert activity_invite.build_answer_record("whatever", NOW) == {}
    assert activity_invite.build_answer_record("", NOW) == {}


# ── 闭环第 4 步：prompt 注入 ────────────────────────────────

def test_activity_prompt_only_when_accepted():
    """**只有 accepted/done 才注入** —— pending 时不能说"你们约好了" """
    assert activity_invite.activity_prompt(with_record(status="pending", activity="摄影展")) == ""
    assert activity_invite.activity_prompt(with_record(status="declined", activity="摄影展")) == ""


def test_activity_prompt_has_activity():
    text = activity_invite.activity_prompt(
        with_record(status="accepted", activity="周末的摄影展")
    )
    assert "摄影展" in text
    assert "约好" in text


def test_activity_prompt_empty_or_bad():
    assert activity_invite.activity_prompt(None) == ""
    assert activity_invite.activity_prompt({}) == ""
    assert activity_invite.activity_prompt({"activity_invitation": "bad"}) == ""
    # 没有 activity 内容时不注入（空约定没意义）
    assert activity_invite.activity_prompt(with_record(status="accepted", activity="")) == ""


def test_activity_prompt_today_and_past():
    """**约定就在今天 / 已经过了** 要说不同的话（否则她会一直说"约好了要去"）"""
    today_later = activity_invite.activity_prompt(
        with_record(status="accepted", activity="河堤", scheduled_at=(NOW + timedelta(hours=3)).isoformat()),
        now=NOW,
    )
    assert "今天" in today_later

    overdue = activity_invite.activity_prompt(
        with_record(status="accepted", activity="河堤", scheduled_at=(NOW - timedelta(hours=3)).isoformat()),
        now=NOW,
    )
    assert "过了" in overdue

    tomorrow = activity_invite.activity_prompt(
        with_record(status="accepted", activity="河堤", scheduled_at=(NOW + timedelta(hours=30)).isoformat()),
        now=NOW,
    )
    assert "明天" in tomorrow


def test_activity_prompt_done_becomes_memory():
    """**done 之后是回忆**，不是"约好了" —— 这是"过程"闭环的可见结果"""
    text = activity_invite.activity_prompt(
        with_record(status="done", activity="摄影展", done_at=NOW.isoformat()), now=NOW
    )
    assert "摄影展" in text
    assert "去过" in text
    assert "约好" not in text


# ── 状态机：accepted → done ─────────────────────────────────

def test_settle_due_only_after_scheduled():
    rec = with_record(
        status="accepted", activity="摄影展",
        scheduled_at=(NOW + timedelta(hours=2)).isoformat(),
    )
    assert activity_invite.settle_due(rec, now=NOW) is None      # 还没到
    due = activity_invite.settle_due(rec, now=NOW + timedelta(hours=3))
    assert due["record"]["status"] == "done"
    assert due["record"]["done_at"]
    assert "摄影展" in due["memory_text"]                        # 要落长期记忆


def test_settle_due_ignores_non_accepted():
    for status in ("pending", "declined", "done", None):
        rec = {"activity_invitation": {"status": status, "activity": "摄影展",
                                       "scheduled_at": (NOW - timedelta(days=1)).isoformat()}}
        assert activity_invite.settle_due(rec, now=NOW) is None


def test_settle_due_legacy_record_without_scheduled_at():
    """老数据只有 `answered_at`（没有 scheduled_at）→ 用默认延迟，不能永远不结算"""
    old = with_record(status="accepted", activity="摄影展",
                      answered_at=(NOW - timedelta(hours=30)).isoformat())
    assert activity_invite.settle_due(old, now=NOW) is not None
    fresh = with_record(status="accepted", activity="摄影展",
                        answered_at=(NOW - timedelta(hours=2)).isoformat())
    assert activity_invite.settle_due(fresh, now=NOW) is None


def test_settle_due_idempotent():
    """结算两次：第二次必须返回 None（否则记忆会重复写）"""
    rec = with_record(status="accepted", activity="摄影展",
                      scheduled_at=(NOW - timedelta(hours=1)).isoformat())
    due = activity_invite.settle_due(rec, now=NOW)
    assert due is not None
    merged = {"activity_invitation": {**rec["activity_invitation"], **due["record"]}}
    assert activity_invite.settle_due(merged, now=NOW) is None


# ── 状态机：accepted / done 会挡住新邀请 ─────────────────────

def test_accepted_future_blocks_new_invite():
    """**约好了还没去 → 别再约**（否则新邀请会把那条约定覆盖掉，静默丢约定）"""
    d = activity_invite.should_invite(
        {**with_record(status="accepted", activity="摄影展",
                       scheduled_at=(NOW + timedelta(hours=5)).isoformat()),
         "favorability": 80},
        now=NOW, seed="lucky",
    )
    assert d.invite is False
    assert "约定" in d.reason


def test_accepted_overdue_does_not_block_forever():
    """已过点但还没结算（settle 没跑）→ 不能永久挡住邀请"""
    d = activity_invite.should_invite(
        {**with_record(status="accepted", activity="摄影展",
                       scheduled_at=(NOW - timedelta(hours=5)).isoformat()),
         "favorability": 80},
        now=NOW, seed="lucky",
    )
    assert d.invite is True


def test_done_recent_blocks_then_expires():
    """刚一起出去过 → 缓一天；超过一天可以再约"""
    recent = activity_invite.should_invite(
        {**with_record(status="done", activity="摄影展",
                       done_at=(NOW - timedelta(hours=3)).isoformat()),
         "favorability": 80},
        now=NOW, seed="lucky",
    )
    assert recent.invite is False

    old = activity_invite.should_invite(
        {**with_record(status="done", activity="摄影展",
                       done_at=(NOW - timedelta(days=2)).isoformat()),
         "favorability": 80},
        now=NOW, seed="lucky",
    )
    assert old.invite is True


def test_pending_expires_so_user_is_not_blocked_forever():
    """**pending 过期**：用户直接关页面不回，原来会永久挡住所有后续邀请"""
    fresh = activity_invite.should_invite(
        {**with_record(status="pending", activity="摄影展",
                       created_at=(NOW - timedelta(hours=2)).isoformat()),
         "favorability": 80},
        now=NOW, seed="lucky",
    )
    assert fresh.invite is False

    stale = activity_invite.should_invite(
        {**with_record(status="pending", activity="摄影展",
                       created_at=(NOW - timedelta(hours=60)).isoformat()),
         "favorability": 80},
        now=NOW, seed="lucky",
    )
    assert stale.invite is True


# ── LLM 产出清洗 ───────────────────────────────────────────

def test_clean_invitation_payload():
    ok = activity_invite.clean_invitation_payload({"activity": "摄影展", "message": "要不要一起去"})
    assert ok == {"activity": "摄影展", "message": "要不要一起去"}


def test_clean_payload_drops_extra_fields():
    """LLM 可能返回一堆额外字段，**不该原样存进用户数据**"""
    ok = activity_invite.clean_invitation_payload(
        {"activity": "摄影展", "message": "一起去", "internal_note": "x", "score": 0.9}
    )
    assert set(ok.keys()) == {"activity", "message"}


def test_clean_payload_rejects_bad():
    assert activity_invite.clean_invitation_payload({"activity": "", "message": "x"}) is None
    assert activity_invite.clean_invitation_payload({"activity": "x"}) is None
    assert activity_invite.clean_invitation_payload({"activity": "x" * 40, "message": "y"}) is None
    assert activity_invite.clean_invitation_payload({"activity": "x", "message": "y" * 70}) is None
    assert activity_invite.clean_invitation_payload(None) is None
    assert activity_invite.clean_invitation_payload("bad") is None


def test_clean_payload_keeps_valid_when_hours():
    ok = activity_invite.clean_invitation_payload(
        {"activity": "傍晚的河堤", "message": "一起去", "when_hours": 6}
    )
    assert ok["when_hours"] == 6
    # 字符串数字也认（LLM 常给 "6"）
    ok2 = activity_invite.clean_invitation_payload(
        {"activity": "傍晚的河堤", "message": "一起去", "when_hours": "6"}
    )
    assert ok2["when_hours"] == 6


def test_clean_payload_drops_invalid_when_hours():
    """非法 when_hours **整个键丢掉**（不是存 0 或负数）→ 交给默认延迟兜底"""
    for bad in (0, -3, 999, "abc", None, True, {}):
        ok = activity_invite.clean_invitation_payload(
            {"activity": "河堤", "message": "一起去", "when_hours": bad}
        )
        assert ok is not None
        assert "when_hours" not in ok, f"when_hours={bad!r} 应该被丢掉"
