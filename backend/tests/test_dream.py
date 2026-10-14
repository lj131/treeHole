"""梦境日记（P3-D2）。

## 本文件要守的两条底线

1. **不骚扰用户**：一天一场、不叠加投递、没有新素材就不生成。
2. **梦不能被吃掉**：被冷却拦下时不能清 flag，否则用户永远看不到。

其余是普通行为测试。
"""
from datetime import datetime, timedelta

import pytest

from funcation import dream_agent
from funcation.proactive import proactive_engine, proactive_trigger


@pytest.fixture
def mc(tmp_path, monkeypatch):
    """隔离的 MemoryCenter（主 JSON + .rag.json 都落在 tmp 里）

    ⚠️ 必须 monkeypatch `memory_rag.PERSIST_DIR` —— 它是**绝对路径**
    （`BASE_DIR/data/chroma`），不受 `monkeypatch.chdir` 影响。
    不 patch 的话 `_index_to_rag` / `_migrate_from_chroma` 会读写**真实的开发库**
    （踩过：跑一轮 dream 测试把 `u1_linwan_chat_summary` 写进 10 条垃圾）。
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "memories" / "1").mkdir(parents=True)
    (tmp_path / "data" / "characters").mkdir(parents=True)

    from funcation import memory_rag
    from funcation.memory_center import MemoryCenter

    monkeypatch.setattr(memory_rag, "PERSIST_DIR", str(tmp_path / "data" / "chroma"))
    monkeypatch.setattr(memory_rag, "_chroma_persist_dir", None)
    memory_rag.release_client()

    return MemoryCenter()


CHARACTER = {"id": "linwan", "name": "林婉", "description": "校庆筹备委员会的学姐"}
USER = 1
CHAR = "linwan"


def _seed_chats(mc, n=3, last_chat=None):
    """造几轮聊天摘要，并（可选）设定 last_chat_time"""
    for i in range(n):
        mc.add_chat_summary(USER, CHAR, f"用户: {i}号话题")
    if last_chat:
        mem = mc.load_memory(USER, CHAR)
        mem["last_chat_time"] = last_chat
        mc.save_memory(USER, CHAR, mem)


def _fake_llm(monkeypatch, text="我梦到图书馆的灯全灭了，你举着一盏灯走过来。"):
    """把 dream_agent 的 LLM 换成假实现（模块级 client 是导入时建的，直接 patch 函数）"""
    calls = {"n": 0}

    def _llm(mc, user_id, character_id, character, memory_data=None):
        calls["n"] += 1
        return text

    monkeypatch.setattr(dream_agent, "generate_dream", _llm)
    return calls


# ============================================================
# 生成闸门
# ============================================================

def test_generates_when_there_is_new_material(mc, monkeypatch):
    """有新素材 → 生成，且 pending 落盘"""
    _seed_chats(mc, 3, last_chat=datetime.now().isoformat())
    calls = _fake_llm(monkeypatch)

    dream = dream_agent.ensure_dream_pending(mc, USER, CHAR, CHARACTER)

    assert calls["n"] == 1
    assert dream["text"]
    assert dream["delivered"] is False
    assert dream["date"] == datetime.now().strftime("%Y-%m-%d")
    # 落盘了（重新加载还在）
    assert mc.load_memory(USER, CHAR)["dream"]["text"] == dream["text"]


def test_does_not_stack_undelivered_dreams(mc, monkeypatch):
    """已有 pending 未投递的梦 → **不叠加**，否则攒一堆骚扰用户"""
    _seed_chats(mc, 3, last_chat=datetime.now().isoformat())
    _fake_llm(monkeypatch, "第一场梦")

    dream_agent.ensure_dream_pending(mc, USER, CHAR, CHARACTER)
    # 再造点新素材
    _seed_chats(mc, 2, last_chat=datetime.now().isoformat())

    second = dream_agent.ensure_dream_pending(mc, USER, CHAR, CHARACTER)

    assert second is None, "已经有一场没投递的梦，不该再生成"
    mem = mc.load_memory(USER, CHAR)
    assert mem["dream"]["text"] == "第一场梦"


def test_skips_when_no_chat_since_last_dream(mc, monkeypatch):
    """上次做梦之后没聊过天 → 没素材，跳过"""
    yesterday = (datetime.now() - timedelta(days=1)).isoformat()
    _seed_chats(mc, 3, last_chat=yesterday)
    calls = _fake_llm(monkeypatch)

    # 先造一场已投递的梦（日期是昨天）
    mem = mc.load_memory(USER, CHAR)
    mem["dream"] = {"text": "旧梦", "date": datetime.now().strftime("%Y-%m-%d"),
                    "delivered": True}
    mc.save_memory(USER, CHAR, mem)

    assert dream_agent.ensure_dream_pending(mc, USER, CHAR, CHARACTER) is None
    assert calls["n"] == 0


def test_skips_when_today_already_generated(mc, monkeypatch):
    """今天已经生成过 → 一天一场"""
    _seed_chats(mc, 3, last_chat=datetime.now().isoformat())
    _fake_llm(monkeypatch)
    today = datetime.now().strftime("%Y-%m-%d")

    mem = mc.load_memory(USER, CHAR)
    mem["dream"] = {"text": "今天的梦", "date": today, "delivered": True}
    mc.save_memory(USER, CHAR, mem)

    assert dream_agent.ensure_dream_pending(mc, USER, CHAR, CHARACTER) is None


def test_skips_when_no_chat_summary(mc, monkeypatch):
    """完全没有聊天摘要 → 跳过（没素材硬编就是鸡汤）"""
    mem = mc.load_memory(USER, CHAR)
    mem["last_chat_time"] = datetime.now().isoformat()
    mc.save_memory(USER, CHAR, mem)
    calls = _fake_llm(monkeypatch)

    assert dream_agent.ensure_dream_pending(mc, USER, CHAR, CHARACTER) is None
    assert calls["n"] == 0


def test_dream_due_returns_reason_for_logging():
    """`_dream_due` 返回原因而不是布尔 —— 后台任务要能解释为什么没生成"""
    assert dream_agent._dream_due({}) == ""

    mem = {
        "dream": {"text": "旧梦", "date": "2020-01-01", "delivered": True},
        "last_chat_time": datetime.now().isoformat(),
    }
    assert dream_agent._dream_due(mem) == "有新素材"


# ============================================================
# 失败隔离
# ============================================================

def test_llm_failure_does_not_raise(mc, monkeypatch):
    """LLM 挂了只跳过，**不能抛** —— 这是后台任务"""
    _seed_chats(mc, 3, last_chat=datetime.now().isoformat())

    def _boom(*a, **k):
        raise RuntimeError("DeepSeek 挂了")

    monkeypatch.setattr(dream_agent, "generate_dream", _boom)
    assert dream_agent.ensure_dream_pending(mc, USER, CHAR, CHARACTER) is None


def test_empty_llm_output_is_ignored(mc, monkeypatch):
    """LLM 返回空串 → 当失败处理，不落盘空梦"""
    _seed_chats(mc, 3, last_chat=datetime.now().isoformat())
    _fake_llm(monkeypatch, text="")

    assert dream_agent.ensure_dream_pending(mc, USER, CHAR, CHARACTER) is None
    assert not (mc.load_memory(USER, CHAR).get("dream") or {}).get("text")


# ============================================================
# 不变量：梦不能被吃掉
# ============================================================

def test_trigger_does_not_clear_the_dream(mc):
    """**核心**：`detect_trigger` 只读不清 —— 后面还有决策/冷却两道关，
    就地清 flag 会让梦在被拦下后凭空消失。"""
    mem = mc.load_memory(USER, CHAR)
    mem["dream"] = {"text": "一场梦", "date": "2026-10-14", "delivered": False}
    mc.save_memory(USER, CHAR, mem)
    data = mc.load_memory(USER, CHAR)

    trigger = proactive_trigger.detect_trigger(data)

    assert trigger is not None and trigger["trigger"] == "dream"
    assert data["dream"]["delivered"] is False, "detect_trigger 把梦清掉了"


def test_trigger_skips_already_delivered_dream(mc):
    """已投递的梦不该再触发"""
    mem = mc.load_memory(USER, CHAR)
    mem["dream"] = {"text": "一场梦", "date": "2026-10-14", "delivered": True}
    mc.save_memory(USER, CHAR, mem)

    assert proactive_trigger.detect_trigger(mc.load_memory(USER, CHAR)) is None


def test_mark_delivered_is_idempotent(mc):
    """标记已投递可重复调用（幂等）"""
    mem = mc.load_memory(USER, CHAR)
    mem["dream"] = {"text": "一场梦", "date": "2026-10-14", "delivered": False}
    mc.save_memory(USER, CHAR, mem)

    dream_agent.mark_delivered(mc, USER, CHAR)
    dream_agent.mark_delivered(mc, USER, CHAR)

    assert mc.load_memory(USER, CHAR)["dream"]["delivered"] is True


def test_mark_delivered_no_dream_is_noop(mc):
    """没有梦时调用不该抛"""
    dream_agent.mark_delivered(mc, USER, CHAR)


# ============================================================
# 历史
# ============================================================

def test_dream_history_is_capped(mc, monkeypatch):
    """历史最多 20 条（否则 JSON 无限涨）"""
    _fake_llm(monkeypatch)

    for i in range(25):
        mem = mc.load_memory(USER, CHAR)
        mem["last_chat_time"] = datetime.now().isoformat()
        mc.save_memory(USER, CHAR, mem)
        # 每轮都造一条新摘要，保证有新素材
        _seed_chats(mc, 1, last_chat=datetime.now().isoformat())
        # 上一场必须已投递，否则会被"不叠加"拦住
        cur = mc.load_memory(USER, CHAR)
        cur["dream"] = {"text": f"旧{i}", "date": "2020-01-01", "delivered": True}
        mc.save_memory(USER, CHAR, cur)
        dream_agent.ensure_dream_pending(mc, USER, CHAR, CHARACTER)

    assert len(mc.load_memory(USER, CHAR)["dreams"]) == dream_agent.MAX_DREAM_HISTORY


# ============================================================
# 回归测试（2026-10-14 资深开发评审后补）
# ============================================================

def test_cross_day_does_not_consume_today_budget():
    """**回归**：`count_date` 不等于今天 → 当天预算按 0 算。

    原 bug：`today_count` 终身累计，第 5 条之后主动消息**永久静默**。
    """
    from funcation.proactive.proactive_decision import should_send

    mem = {
        "proactive": {
            "today_count": 99,                       # 攒了一大堆
            "count_date": "2020-01-01",              # 但是很久以前
        },
        "character_state": {"energy": 80},
    }
    assert should_send(mem) is True, "跨天还把旧计数算进去"


def test_same_day_budget_still_blocks():
    """同日超额仍然要拦住（别把上面那条修成"永远放行"）"""
    from funcation.proactive.proactive_decision import should_send

    from datetime import datetime

    today = datetime.now().strftime("%Y-%m-%d")
    mem = {
        "proactive": {"today_count": 5, "count_date": today},
        "character_state": {"energy": 80},
    }
    assert should_send(mem) is False


def test_record_dream_does_not_clobber_concurrent_writes(mc, monkeypatch):
    """**回归**：落盘只 merge `dream`/`dreams`，不能整包回写旧快照。

    原 bug：`ensure_dream_pending` 开头 load 一份快照，中间隔一次 LLM 调用，
    再用那份旧快照 `save_memory` —— 期间别人写的字段全被覆盖（lost update）。
    """
    _seed_chats(mc, 3, last_chat=datetime.now().isoformat())
    _fake_llm(monkeypatch, "一场梦")

    # 模拟"并发的另一个写者"：生成前先把某个字段改成新值
    mem = mc.load_memory(USER, CHAR)
    mem["character_state"]["mood"] = "别人后来改的"
    mem["concurrent_marker"] = "别动我"
    mc.save_memory(USER, CHAR, mem)

    dream_agent.ensure_dream_pending(mc, USER, CHAR, CHARACTER)

    after = mc.load_memory(USER, CHAR)
    assert after["character_state"]["mood"] == "别人后来改的", "并发写被覆盖了"
    assert after["concurrent_marker"] == "别动我", "并发写被覆盖了"
    assert after["dream"]["text"] == "一场梦"      # 自己的字段还是写进去了


def test_oversized_dream_is_rejected(mc, monkeypatch):
    """**回归**：模型失控输出超长文本要丢弃，不能撑大主 JSON"""
    _seed_chats(mc, 3, last_chat=datetime.now().isoformat())
    _fake_llm(monkeypatch, "梦" * (dream_agent.MAX_DREAM_CHARS + 100))

    assert dream_agent.ensure_dream_pending(mc, USER, CHAR, CHARACTER) is None
    assert not (mc.load_memory(USER, CHAR).get("dream") or {}).get("text")


def test_dream_due_uses_date_parsing_not_string_slice():
    """**回归**：用 date 比较而不是 `last_chat_time[:10]` 字符串切片。

    后者靠隐式格式契约，换成带时区的 ISO 字符串就静默失效。
    """
    from datetime import datetime, timedelta

    now = datetime.now()
    # 带时区后缀的 ISO 字符串（`[:10]` 切片对它是错的）
    with_tz = (now - timedelta(days=1)).isoformat() + "+08:00"

    mem = {"dream": {"text": "旧梦", "date": "2020-01-01", "delivered": True},
           "last_chat_time": with_tz}
    assert dream_agent._dream_due(mem) == "有新素材", "带时区的 ISO 日期比较失败了"


def test_dream_due_handles_garbage_last_chat_time():
    """`last_chat_time` 是垃圾 → 视为"没有素材"，不抛"""
    mem = {"dream": {"text": "旧梦", "date": "2020-01-01", "delivered": True},
           "last_chat_time": "根本不是日期"}
    assert dream_agent._dream_due(mem) == ""
