"""活动约定"到点结算"的落地部分（api 层粘合）。

`settle_due()` 是纯函数（在 `test_activity_invite.py` 里测），这里测**它被用起来**：

- 到点 → `status=done` 落库 + **落一条长期记忆**（"活动后留下记忆"就是这一步）
- 没到点 → **一次 IO 都不做**（挂在每轮聊天开头，不能白读盘）
- 幂等 → 重复调用不会重复写记忆
- **任何失败都不抛**（挂聊天主链路，结算失败不能让用户发不出消息）
"""
import copy
from datetime import datetime, timedelta

import pytest

from api import api as api_module


NOW = datetime(2026, 10, 20, 15, 30)


class FakeMC:
    """只实现 `_settle_activity_due` 用到的三个方法。"""

    def __init__(self, mem, *, save_raises=False, long_memory_raises=False):
        self.mem = copy.deepcopy(mem)
        self.saves = 0
        self.long_memories = []
        self.save_raises = save_raises
        self.long_memory_raises = long_memory_raises

    def load_memory(self, user_id, char_id):
        return copy.deepcopy(self.mem)

    def save_memory(self, user_id, char_id, data):
        if self.save_raises:
            raise OSError("disk full")
        self.saves += 1
        self.mem = copy.deepcopy(data)

    def add_long_memory(self, user_id, char_id, text):
        if self.long_memory_raises:
            raise RuntimeError("index down")
        if text not in self.long_memories:
            self.long_memories.append(text)


def accepted_mem(hours_from_now: float, activity: str = "摄影展"):
    return {
        "favorability": 80,
        "activity_invitation": {
            "status": "accepted",
            "activity": activity,
            "answered_at": NOW.isoformat(),
            "scheduled_at": (NOW + timedelta(hours=hours_from_now)).isoformat(),
        },
    }


@pytest.fixture(autouse=True)
def _freeze_now(monkeypatch):
    """`settle_due()` 默认取 `datetime.now()` —— 钉住它，测试才不会随日期漂。"""

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW

    monkeypatch.setattr("funcation.activity_invite.datetime", _FrozenDatetime)


def test_not_due_does_no_io():
    """**没到点就零 IO** —— 这段每轮聊天都跑，不能白读盘"""
    mc = FakeMC(accepted_mem(hours_from_now=5))
    out = api_module._settle_activity_due(mc, 1, "linwan", mc.mem)
    assert mc.saves == 0
    assert mc.long_memories == []
    assert out["activity_invitation"]["status"] == "accepted"


def test_due_marks_done_and_writes_memory():
    """到点 → done + 一条长期记忆（"活动后留下记忆"）"""
    mc = FakeMC(accepted_mem(hours_from_now=-1))
    out = api_module._settle_activity_due(mc, 1, "linwan", mc.mem)

    assert out["activity_invitation"]["status"] == "done"
    assert out["activity_invitation"]["done_at"]
    assert mc.saves == 1
    assert len(mc.long_memories) == 1
    assert "摄影展" in mc.long_memories[0]
    # 其他字段不能丢
    assert out["activity_invitation"]["activity"] == "摄影展"
    assert out["favorability"] == 80


def test_settle_is_idempotent():
    """重复调用不会重复写记忆（否则聊十句就有十条一样的）"""
    mc = FakeMC(accepted_mem(hours_from_now=-1))
    api_module._settle_activity_due(mc, 1, "linwan", mc.mem)
    api_module._settle_activity_due(mc, 1, "linwan", mc.mem)

    assert mc.saves == 1
    assert len(mc.long_memories) == 1


def test_save_failure_does_not_raise():
    """落库失败 → 返回原样、**不抛**（挂聊天主链路）"""
    mc = FakeMC(accepted_mem(hours_from_now=-1), save_raises=True)
    out = api_module._settle_activity_due(mc, 1, "linwan", mc.mem)
    assert out is mc.mem
    assert out["activity_invitation"]["status"] == "accepted"   # 没改成 done


def test_long_memory_failure_does_not_lose_status():
    """记忆写失败不影响状态落库（下次聊天看到 done 就不会再结算）"""
    mc = FakeMC(accepted_mem(hours_from_now=-1), long_memory_raises=True)
    api_module._settle_activity_due(mc, 1, "linwan", mc.mem)
    assert mc.mem["activity_invitation"]["status"] == "done"
    assert mc.long_memories == []


def test_empty_memory_is_safe():
    """空记忆 / 没有 activity_invitation → 什么都不做"""
    mc = FakeMC({})
    out = api_module._settle_activity_due(mc, 1, "linwan", {})
    assert mc.saves == 0
    assert out == {}
