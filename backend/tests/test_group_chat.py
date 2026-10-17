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
