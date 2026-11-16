"""多人群聊选人。重点：**插嘴者不能是主角**、概率真的在生效、确定性。"""
import pytest

from funcation import group_chat


def test_heckler_is_never_the_primary():
    """**插嘴者不能是主角**（自己接自己的话很怪）"""
    cands = ["linwan", "maid", "xiaomei"]
    for i in range(30):
        picked = group_chat.pick_heckler(cands, primary_id="linwan", seed=f"s{i}")
        assert picked in ("maid", "xiaomei")


def test_empty_candidates_returns_none():
    assert group_chat.pick_heckler([], primary_id="linwan", seed="s") is None
    assert group_chat.pick_heckler(None, primary_id="linwan", seed="s") is None


def test_only_primary_in_candidates_returns_none():
    """候选里只有主角自己 → 没人可插嘴"""
    assert group_chat.pick_heckler(["linwan"], primary_id="linwan", seed="s") is None
    assert group_chat.pick_heckler(["linwan", "linwan"], primary_id="linwan", seed="s") is None


def test_single_candidate_is_picked():
    assert group_chat.pick_heckler(["maid"], primary_id="linwan", seed="s") == "maid"


def test_bad_candidates_filtered():
    """非字符串/空串被丢掉，不抛"""
    picked = group_chat.pick_heckler(
        ["maid", "", None, 42, "  "], primary_id="linwan", seed="s"
    )
    assert picked == "maid"


# ── 概率 ────────────────────────────────────────────────────

def test_heckle_chance_is_real():
    """**概率真的生效**：100 个 seed 有打有不打（≈25%）"""
    results = {group_chat.should_heckle(f"s{i}") for i in range(100)}
    assert True in results and False in results
    hits = sum(1 for i in range(200) if group_chat.should_heckle(f"k{i}"))
    assert 30 <= hits <= 80  # 25% ± 合理波动


def test_chance_zero_and_hundred():
    assert group_chat.should_heckle("s", chance=0) is False
    assert group_chat.should_heckle("s", chance=100) is True


def test_bad_chance_falls_back():
    assert group_chat.should_heckle("s", chance="abc") in (True, False)
    assert group_chat.should_heckle("s", chance=None) in (True, False)


# ── plan_group ──────────────────────────────────────────────

def test_plan_group_no_heckle_when_chance_zero():
    plan = group_chat.plan_group(
        ["maid", "xiaomei"], primary_id="linwan", seed="s", chance=0
    )
    assert plan.primary == "linwan"
    assert plan.hecklers == []


def test_plan_group_respects_max_hecklers():
    """上限生效：最多 1 个（默认）"""
    cands = ["a", "b", "c", "d"]
    for i in range(20):
        plan = group_chat.plan_group(cands, primary_id="linwan", seed=f"s{i}", chance=100)
        assert len(plan.hecklers) <= 1


def test_plan_group_multi_hecklers_when_allowed():
    """放宽上限时能选多个，且不重复、不含主角"""
    plan = group_chat.plan_group(
        ["a", "b", "c", "linwan"], primary_id="linwan", seed="s", max_hecklers=3, chance=100
    )
    assert len(plan.hecklers) == 3
    assert len(set(plan.hecklers)) == 3
    assert "linwan" not in plan.hecklers


def test_plan_group_bad_max_hecklers():
    plan = group_chat.plan_group(["maid"], primary_id="linwan", seed="s", max_hecklers="x", chance=100)
    assert len(plan.hecklers) <= 1  # 兜底到默认


def test_plan_group_empty_candidates():
    plan = group_chat.plan_group([], primary_id="linwan", seed="s", chance=100)
    assert plan.hecklers == []
    assert plan.primary == "linwan"


# ── 确定性 ──────────────────────────────────────────────────

def test_deterministic():
    cands = ["maid", "xiaomei"]
    a = group_chat.plan_group(cands, primary_id="linwan", seed="fixed")
    b = group_chat.plan_group(cands, primary_id="linwan", seed="fixed")
    assert a == b


# ============================================================
# 加权调度（批次 2，2026-11-16）
# ============================================================

def test_weights_relevant_is_strongest():
    """内容相关（聊到谁）的权重要**明显高于**纯关系好的"""
    w = group_chat.weights_for(
        ["maid", "xiaomei"],
        affinity={"maid": 100},      # 关系满值
        relevant={"xiaomei"},        # 但本轮聊到小梅
    )
    assert w["xiaomei"] > w["maid"], w


def test_weights_sleeping_is_hard_gate():
    """睡着的人权重必须是 0（硬门，不是降权）"""
    w = group_chat.weights_for(
        ["maid", "xiaomei"],
        affinity={"maid": 100}, relevant={"maid"},
        sleeping=["maid"],
    )
    assert w["maid"] == 0.0
    assert w["xiaomei"] > 0


def test_weights_recent_is_demoted_not_banned():
    """最近插过的人**降权但不禁止** —— 禁止会显得机械"""
    base = group_chat.weights_for(["maid"])
    demoted = group_chat.weights_for(["maid"], recent=["maid"])
    assert demoted["maid"] > 0, "降权不是禁止"
    assert demoted["maid"] < base["maid"] * 0.2, "但要降得够狠才防得住连庄"


def test_weights_bad_affinity_does_not_raise():
    """脏数据（None/字符串）不抛，退化成 0"""
    w = group_chat.weights_for(
        ["a", "b"], affinity={"a": None, "b": "bad"}
    )
    assert w == {"a": 1.0, "b": 1.0}


def test_plan_with_signals_is_deterministic():
    kw = dict(
        primary_id="linwan", seed="fixed", chance=100,
        affinity={"maid": 80, "xiaomei": 60}, relevant={"xiaomei"},
    )
    a = group_chat.plan_group_with_signals(["maid", "xiaomei"], **kw)
    b = group_chat.plan_group_with_signals(["maid", "xiaomei"], **kw)
    assert a == b


def test_plan_with_signals_respects_all_gates():
    """主角排除 / 上限 / 同轮不重复 —— 和旧版语义一致"""
    plan = group_chat.plan_group_with_signals(
        ["linwan", "maid", "xiaomei", "xiaoyu"],
        primary_id="linwan", seed="s", chance=100, max_hecklers=2,
    )
    assert len(plan.hecklers) <= 2
    assert "linwan" not in plan.hecklers
    assert len(set(plan.hecklers)) == len(plan.hecklers)


def test_plan_with_signals_all_sleeping_returns_empty():
    """全员睡 → 不插嘴"""
    plan = group_chat.plan_group_with_signals(
        ["maid", "xiaomei"], primary_id="linwan", seed="s",
        chance=100, sleeping=["maid", "xiaomei"],
    )
    assert plan.hecklers == []


def test_plan_with_signals_relevant_wins_statistically():
    """统计意义：聊到谁，多数情况下就是谁接话（但非 100%，保留自然感）"""
    hits = 0
    for i in range(40):
        plan = group_chat.plan_group_with_signals(
            ["maid", "xiaomei"], primary_id="linwan", seed=f"s{i}",
            chance=100, relevant={"xiaomei"},
        )
        hits += plan.hecklers == ["xiaomei"]
    assert hits >= 28, f"相关内容应占多数，实际 {hits}/40"


def test_plan_with_signals_recent_demotes_streak():
    """防连庄：把一个人标成"刚插过"，他被再选中的次数要明显下降"""
    picks_without = sum(
        group_chat.plan_group_with_signals(
            ["maid", "xiaomei"], primary_id="linwan", seed=f"s{i}",
            chance=100,
        ).hecklers == ["maid"]
        for i in range(40)
    )
    picks_with = sum(
        group_chat.plan_group_with_signals(
            ["maid", "xiaomei"], primary_id="linwan", seed=f"s{i}",
            chance=100, recent=["maid"],
        ).hecklers == ["maid"]
        for i in range(40)
    )
    assert picks_with < picks_without, (picks_with, picks_without)


# ============================================================
# 加权调度（批次 2，2026-11-16）
# ============================================================

def test_weights_relevant_is_strongest():
    """内容相关（聊到谁）的权重要**明显高于**纯关系好的"""
    w = group_chat.weights_for(
        ["maid", "xiaomei"],
        affinity={"maid": 100},      # 关系满值
        relevant={"xiaomei"},        # 但本轮聊到小梅
    )
    assert w["xiaomei"] > w["maid"], w


def test_weights_sleeping_is_hard_gate():
    """睡着的人权重必须是 0（硬门，不是降权）"""
    w = group_chat.weights_for(
        ["maid", "xiaomei"],
        affinity={"maid": 100}, relevant={"maid"},
        sleeping=["maid"],
    )
    assert w["maid"] == 0.0
    assert w["xiaomei"] > 0


def test_weights_recent_is_demoted_not_banned():
    """最近插过的人**降权但不禁止** —— 禁止会显得机械"""
    base = group_chat.weights_for(["maid"])
    demoted = group_chat.weights_for(["maid"], recent=["maid"])
    assert demoted["maid"] > 0, "降权不是禁止"
    assert demoted["maid"] < base["maid"] * 0.2, "但要降得够狠才防得住连庄"


def test_weights_bad_affinity_does_not_raise():
    """脏数据（None/字符串）不抛，退化成 0"""
    w = group_chat.weights_for(
        ["a", "b"], affinity={"a": None, "b": "bad"}
    )
    assert w == {"a": 1.0, "b": 1.0}


def test_plan_with_signals_is_deterministic():
    kw = dict(
        primary_id="linwan", seed="fixed", chance=100,
        affinity={"maid": 80, "xiaomei": 60}, relevant={"xiaomei"},
    )
    a = group_chat.plan_group_with_signals(["maid", "xiaomei"], **kw)
    b = group_chat.plan_group_with_signals(["maid", "xiaomei"], **kw)
    assert a == b


def test_plan_with_signals_respects_all_gates():
    """主角排除 / 上限 / 同轮不重复 —— 和旧版语义一致"""
    plan = group_chat.plan_group_with_signals(
        ["linwan", "maid", "xiaomei", "xiaoyu"],
        primary_id="linwan", seed="s", chance=100, max_hecklers=2,
    )
    assert len(plan.hecklers) <= 2
    assert "linwan" not in plan.hecklers
    assert len(set(plan.hecklers)) == len(plan.hecklers)


def test_plan_with_signals_all_sleeping_returns_empty():
    """全员睡 → 不插嘴"""
    plan = group_chat.plan_group_with_signals(
        ["maid", "xiaomei"], primary_id="linwan", seed="s",
        chance=100, sleeping=["maid", "xiaomei"],
    )
    assert plan.hecklers == []


def test_plan_with_signals_relevant_wins_statistically():
    """统计意义：聊到谁，多数情况下就是谁接话（但非 100%，保留自然感）"""
    hits = 0
    for i in range(40):
        plan = group_chat.plan_group_with_signals(
            ["maid", "xiaomei"], primary_id="linwan", seed=f"s{i}",
            chance=100, relevant={"xiaomei"},
        )
        hits += plan.hecklers == ["xiaomei"]
    assert hits >= 28, f"相关内容应占多数，实际 {hits}/40"


def test_plan_with_signals_recent_demotes_streak():
    """防连庄：把一个人标成"刚插过"，他被再选中的次数要明显下降"""
    picks_without = sum(
        group_chat.plan_group_with_signals(
            ["maid", "xiaomei"], primary_id="linwan", seed=f"s{i}",
            chance=100,
        ).hecklers == ["maid"]
        for i in range(40)
    )
    picks_with = sum(
        group_chat.plan_group_with_signals(
            ["maid", "xiaomei"], primary_id="linwan", seed=f"s{i}",
            chance=100, recent=["maid"],
        ).hecklers == ["maid"]
        for i in range(40)
    )
    assert picks_with < picks_without, (picks_with, picks_without)
