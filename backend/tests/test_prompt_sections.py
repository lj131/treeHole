"""prompt 渲染段单测 —— _build_self_awareness_section + build_memory_summary（纯文本拼接）。"""
from funcation.prompt import _build_self_awareness_section, build_memory_summary


# ---------- _build_self_awareness_section ----------

def test_empty_self_awareness_returns_empty():
    assert _build_self_awareness_section(None, 50, "普通") == ""
    assert _build_self_awareness_section({}, 50, "普通") == ""


def test_milestone_renders_trail():
    sa = {
        "milestones": [
            {"date": "2026-01-01", "from": "陌生", "to": "普通"},
            {"date": "2026-02-01", "from": "普通", "to": "朋友"},
        ],
        "fav_trail": [],
        "peak_favorability": 50,
    }
    out = _build_self_awareness_section(sa, 60, "朋友")
    assert "陌生 → 普通 → 朋友" in out
    assert "自我觉察" in out


def test_warming_when_diff_ge_8():
    # 需 len(fav_trail)>=2 才进入升温/冷却判断；earlier 取 fav_trail[0]
    sa = {"milestones": [], "fav_trail": [{"date": "d1", "value": 50}, {"date": "d2", "value": 55}],
          "peak_favorability": 60}
    out = _build_self_awareness_section(sa, 60, "朋友")   # 60-50=10 >= 8
    assert "更有好感" in out


def test_cooling_when_diff_le_neg8():
    sa = {"milestones": [], "fav_trail": [{"date": "d1", "value": 70}, {"date": "d2", "value": 65}],
          "peak_favorability": 70}
    out = _build_self_awareness_section(sa, 60, "朋友")   # 60-70=-10 <= -8
    assert "回落" in out


def test_no_warming_when_diff_small():
    sa = {"milestones": [], "fav_trail": [{"date": "d1", "value": 55}, {"date": "d2", "value": 56}],
          "peak_favorability": 60}
    out = _build_self_awareness_section(sa, 60, "朋友")   # diff=5
    assert "更有好感" not in out
    assert "回落" not in out


def test_nostalgia_when_peak_drop_ge_15():
    sa = {"milestones": [], "fav_trail": [], "peak_favorability": 90}
    out = _build_self_awareness_section(sa, 70, "朋友")   # 90-70=20 >= 15
    assert "曾经更亲近" in out or "怀念" in out


def test_fav_trail_needs_two_entries():
    """只有一条快照时不做升温/冷却判断（需 len>=2）。"""
    sa = {"milestones": [], "fav_trail": [{"date": "d1", "value": 10}], "peak_favorability": 90}
    out = _build_self_awareness_section(sa, 90, "亲近")
    # 单条快照：不报升温（diff 算不出趋势），但 peak=90 fav=90 不触发怀念
    assert "更有好感" not in out


# ---------- build_memory_summary ----------

def test_build_memory_summary_empty():
    out = build_memory_summary([], [], [], chat_summary=None, retrieved_memories=None)
    assert "暂无" in out
    assert "【最近聊天】" in out
    assert "【长期记忆】" in out
    assert "【关键事件】" in out
    assert "【聊天摘要】" in out


def test_build_memory_summary_with_data():
    msgs = [{"role": "user", "content": "你好"}, {"role": "assistant", "content": "嗨"}]
    long_mem = ["用户喜欢猫"]
    events = [{"event": "下雨了"}]
    out = build_memory_summary(msgs, long_mem, events, chat_summary=["聊过天气"])
    assert "你好" in out            # 最近聊天取 user 消息
    assert "用户喜欢猫" in out
    assert "下雨了" in out
    assert "聊过天气" in out


def test_build_memory_summary_with_rag():
    rag = [{"collection": "profile", "text": "用户叫小明"},
           {"collection": "long_memory", "text": "用户在北京"}]
    out = build_memory_summary([], [], [], retrieved_memories=rag)
    assert "相关记忆" in out
    assert "用户叫小明" in out
    assert "用户在北京" in out
