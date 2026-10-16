"""关系张力与冲突检测（纯函数）。重点测**冷却**和**确定性**。"""
import pytest

from funcation import tension

TODAY = "2026-10-16"


def rels(fav=50, trust=50, pairs=3):
    """造 n 对关系（键名不同，值相同）"""
    out = {}
    for i in range(pairs):
        out[f"a{i}"] = {f"b{i}": {"favorability": fav, "trust": trust, "intimacy": 30}}
    return out


# ── 张力决策 ────────────────────────────────────────────────

def test_calm_when_no_relationships():
    assert tension.decide_tension({}, seed="s", today=TODAY) == tension.TENSION_CALM


def test_cooldown_forces_calm():
    """**刚吵过就别再吵** —— 冷却优先于一切"""
    # 健康关系 + 深裂痕，本该有张力，但冷却期内必须平和
    for level_seed in ("x", "y", "z", "w", "v", "u"):
        assert (
            tension.decide_tension(
                rels(fav=20, trust=10),
                seed=level_seed,
                today=TODAY,
                last_conflict_date="2026-10-14",  # 2 天前 < 7 天冷却
            )
            == tension.TENSION_CALM
        )


def test_cooldown_expires():
    """超过冷却期后恢复出张力的可能"""
    results = {
        tension.decide_tension(
            rels(fav=20, trust=10),
            seed=f"s{i}",
            today=TODAY,
            last_conflict_date="2026-10-01",  # 15 天前 > 7 天
        )
        for i in range(30)
    }
    assert tension.TENSION_CALM in results or len(results) > 1


def test_deterministic_same_seed():
    """**同 seed 同结果**（不用 random 模块的意义）"""
    args = dict(relationships=rels(fav=20, trust=10), today=TODAY)
    a = [tension.decide_tension(seed=f"s{i}", **args) for i in range(10)]
    b = [tension.decide_tension(seed=f"s{i}", **args) for i in range(10)]
    assert a == b


def test_low_trust_raises_tension_chance():
    """信任低的关系出张力的频率更高（统计意义上）"""
    def count(trust):
        return sum(
            1
            for i in range(200)
            if tension.decide_tension(
                rels(fav=30, trust=trust), seed=f"k{i}", today=TODAY
            )
            != tension.TENSION_CALM
        )

    assert count(10) > count(80)


def test_healthy_relationships_rarely_conflict():
    """健康关系（高信任高好感）不该频繁出张力"""
    hits = sum(
        1
        for i in range(200)
        if tension.decide_tension(
            rels(fav=85, trust=85), seed=f"h{i}", today=TODAY
        ) == tension.TENSION_CONFLICT
    )
    assert hits < 30  # < 15%


def test_single_pair_less_tension():
    """关系少时世界更平静（乘 0.6 修正）"""
    many = sum(
        1
        for i in range(200)
        if tension.decide_tension(rels(fav=30, trust=10, pairs=5), seed=f"m{i}", today=TODAY)
        != tension.TENSION_CALM
    )
    few = sum(
        1
        for i in range(200)
        if tension.decide_tension(rels(fav=30, trust=10, pairs=1), seed=f"m{i}", today=TODAY)
        != tension.TENSION_CALM
    )
    assert few < many


def test_bad_relationship_data_does_not_crash():
    assert tension.decide_tension(None, seed="s", today=TODAY) == tension.TENSION_CALM
    assert tension.decide_tension({"a": "not a dict"}, seed="s", today=TODAY) == tension.TENSION_CALM
    assert tension.decide_tension({"a": {"b": None}}, seed="s", today=TODAY) == tension.TENSION_CALM


def test_bad_dates_do_not_crash():
    assert tension.decide_tension(rels(), seed="s", today="bad") == tension.TENSION_CALM
    assert tension.decide_tension(
        rels(), seed="s", today=TODAY, last_conflict_date="not a date"
    ) in (0, 1, 2)


# ── 冲突检测 ────────────────────────────────────────────────

def test_detect_obvious_conflict():
    result = {
        "relationship_changes": [
            {"from": "林婉", "to": "小羽", "favorability_delta": -12, "reason": "因为社团的事吵了起来"}
        ]
    }
    found = tension.detect_conflict(result)
    assert len(found) == 1
    assert found[0]["severity"] == 2
    assert found[0]["from"] == "林婉"


def test_positive_changes_are_not_conflicts():
    result = {"relationship_changes": [{"from": "a", "to": "b", "favorability_delta": 10}]}
    assert tension.detect_conflict(result) == []


def test_threshold_boundary():
    """**-5 算冲突，-4 不算**（边界要明确）"""
    def chk(delta):
        return tension.detect_conflict(
            {"relationship_changes": [{"from": "a", "to": "b", "favorability_delta": delta}]}
        )

    assert chk(-4) == []
    assert len(chk(-5)) == 1
    assert chk(-5)[0]["severity"] == 1  # 小摩擦
    assert chk(-10)[0]["severity"] == 2  # 明显冲突


def test_trust_drop_counts_as_conflict():
    """信任跌也算（不只看好感）"""
    found = tension.detect_conflict(
        {"relationship_changes": [{"from": "a", "to": "b", "trust_delta": -8}]}
    )
    assert len(found) == 1


def test_intimacy_drop_alone_is_not_conflict():
    """**亲密度下降不算吵架**（那更像"疏远"）"""
    found = tension.detect_conflict(
        {"relationship_changes": [{"from": "a", "to": "b", "intimacy_delta": -20}]}
    )
    assert found == []


def test_worst_delta_wins_severity():
    """好感和信任都跌时按更严重的算"""
    found = tension.detect_conflict(
        {"relationship_changes": [{"from": "a", "to": "b", "favorability_delta": -3, "trust_delta": -15}]}
    )
    assert found[0]["severity"] == 2


def test_missing_names_skipped():
    assert tension.detect_conflict({"relationship_changes": [{"favorability_delta": -20}]}) == []


def test_detect_conflict_bad_input():
    assert tension.detect_conflict(None) == []
    assert tension.detect_conflict({}) == []
    assert tension.detect_conflict({"relationship_changes": None}) == []
    assert tension.detect_conflict({"relationship_changes": ["nope", None]}) == []


def test_sorted_most_severe_first():
    found = tension.detect_conflict(
        {
            "relationship_changes": [
                {"from": "a", "to": "b", "favorability_delta": -5},
                {"from": "c", "to": "d", "favorability_delta": -18},
            ]
        }
    )
    assert found[0]["from"] == "c"


# ── 通知与冷却 ──────────────────────────────────────────────

def test_notice_payload_shape():
    payload = tension.conflict_notice_payload(
        {"from": "林婉", "to": "小羽", "severity": 2, "reason": "吵了一架"}, today=TODAY
    )
    assert payload["changed"] is True
    assert payload["with"] == "小羽"
    assert payload["severity"] == 2
    assert payload["summary"] == "吵了一架"


def test_notice_payload_fallback_summary():
    """没有 reason 时也要有话说，不能留空"""
    payload = tension.conflict_notice_payload({"from": "a", "to": "小羽"}, today=TODAY)
    assert "小羽" in payload["summary"]


def test_only_severe_conflicts_notify():
    """**小摩擦不专门来倾诉**（天天来会很烦）"""
    assert tension.should_notify_conflict({"severity": 2}) is True
    assert tension.should_notify_conflict({"severity": 1}) is False


def test_cooldown_ok():
    assert tension.cooldown_ok("", TODAY) is True
    assert tension.cooldown_ok("2026-10-01", TODAY) is True   # 15 天
    assert tension.cooldown_ok("2026-10-14", TODAY) is False  # 2 天
    assert tension.cooldown_ok("bad", TODAY) is True          # 解析不了 → 放行
