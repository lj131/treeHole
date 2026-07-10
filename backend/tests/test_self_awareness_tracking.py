"""self_awareness 轨迹追踪单测 —— A4 核心确定性逻辑，零 LLM。

覆盖：里程碑记录（≤8）、峰值/低谷刷新、好感快照（≤10、同日覆盖）。
"""
from funcation.memory_center import MemoryCenter, create_default_memory


def _fresh_sa():
    """一个空 self_awareness dict，便于直接喂 _track_self_awareness。"""
    return {
        "first_chat_date": "",
        "peak_favorability": 50,
        "peak_fav_date": "",
        "min_favorability": 50,
        "min_fav_date": "",
        "milestones": [],
        "fav_trail": [],
    }


def test_level_change_records_milestone(mc):
    mem = {"favorability": 60, "self_awareness": _fresh_sa()}
    mc._track_self_awareness(mem, old_level="普通", new_level="朋友", favorability=60)
    ms = mem["self_awareness"]["milestones"]
    assert len(ms) == 1
    assert ms[0]["from"] == "普通" and ms[0]["to"] == "朋友"
    assert ms[0]["date"]  # 非空日期


def test_no_level_change_no_milestone(mc):
    mem = {"favorability": 55, "self_awareness": _fresh_sa()}
    mc._track_self_awareness(mem, "普通", "普通", 55)
    assert mem["self_awareness"]["milestones"] == []


def test_milestones_capped_at_8(mc):
    sa = _fresh_sa()
    mem = {"favorability": 50, "self_awareness": sa}
    # 制造 10 次等级变化
    for i in range(10):
        mc._track_self_awareness(mem, "普通", "朋友", 50 + i)
    assert len(sa["milestones"]) == 8   # 最多保留 8 条


def test_peak_and_min_favorability_updated(mc):
    sa = _fresh_sa()  # peak=min=50
    mem = {"favorability": 50, "self_awareness": sa}
    mc._track_self_awareness(mem, "普通", "朋友", 80)   # 新峰
    assert sa["peak_favorability"] == 80
    assert sa["peak_fav_date"]
    mc._track_self_awareness(mem, "朋友", "朋友", 20)   # 新谷
    assert sa["min_favorability"] == 20
    assert sa["min_fav_date"]


def test_peak_not_lowered_by_dip(mc):
    """好感下降刷新低谷，但不应把 peak 也拉低。"""
    sa = _fresh_sa()
    sa["peak_favorability"] = 90
    mem = {"favorability": 90, "self_awareness": sa}
    mc._track_self_awareness(mem, "亲近", "朋友", 40)
    assert sa["peak_favorability"] == 90   # 峰值不动
    assert sa["min_favorability"] == 40


def test_fav_trail_same_day_overwrites(mc):
    sa = _fresh_sa()
    mem = {"favorability": 50, "self_awareness": sa}
    mc._track_self_awareness(mem, "普通", "普通", 55)
    mc._track_self_awareness(mem, "普通", "普通", 60)
    trail = sa["fav_trail"]
    assert len(trail) == 1                 # 同日覆盖
    assert trail[0]["value"] == 60


def test_fav_trail_capped_at_10(mc):
    sa = _fresh_sa()
    mem = {"favorability": 50, "self_awareness": sa}
    # 喂 12 条不同日期快照：手动改 last 条的 date 模拟跨日
    for i in range(12):
        sa["fav_trail"].append({"date": f"2026-01-{i+1:02d}", "value": 50 + i})
    mc._track_self_awareness(mem, "普通", "普通", 99)
    # 触发 today 覆盖逻辑会 append（today 不等于最后日期），然后截断到 10
    assert len(sa["fav_trail"]) <= 10


def test_first_chat_date_set_once(mc):
    sa = _fresh_sa()
    sa["first_chat_date"] = ""
    mem = {"favorability": 50, "self_awareness": sa}
    mc._track_self_awareness(mem, "普通", "普通", 50)
    assert sa["first_chat_date"]  # 首次写入
    first = sa["first_chat_date"]
    mc._track_self_awareness(mem, "普通", "普通", 52)
    assert sa["first_chat_date"] == first   # 不覆盖
