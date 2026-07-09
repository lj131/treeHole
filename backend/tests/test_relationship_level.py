"""relationship_agent.get_relationship_level 阈值单测 —— 纯函数，20/40/60/80 分档。"""
import pytest

from funcation.relationship_agent import get_relationship_level


@pytest.mark.parametrize("fav,expected", [
    (0, "陌生"),
    (19, "陌生"),
    (20, "普通"),
    (39, "普通"),
    (40, "朋友"),
    (59, "朋友"),
    (60, "亲近"),
    (79, "亲近"),
    (80, "暧昧"),
    (100, "暧昧"),
])
def test_thresholds(fav, expected):
    assert get_relationship_level(fav) == expected


def test_boundary_exact():
    """边界值：刚好等于阈值跳档。"""
    assert get_relationship_level(20) == "普通"   # <20 才陌生
    assert get_relationship_level(60) == "亲近"   # <60 才朋友
    assert get_relationship_level(80) == "暧昧"   # <80 才亲近


def test_all_levels_reachable():
    levels = {get_relationship_level(f) for f in (0, 30, 50, 70, 90)}
    assert levels == {"陌生", "普通", "朋友", "亲近", "暧昧"}
