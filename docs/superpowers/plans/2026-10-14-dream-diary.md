# D2 梦境日记 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 角色在**用户的聊天内容**基础上做一个"睡前总结"变成**梦境**，
次日主动发消息说"我昨晚梦到…"（P3 里 ROI 最高的一项）。

**Architecture:** 复用两块已有的东西，**不新造机制**：
① `chat_summary`（真源刚在 P0 §1-7 统一到 `.rag.json`）当素材；
② `funcation/proactive/` 的触发→决策→冷却→生成 四段式 当投递通道。
新增一个 `funcation/dream_agent.py` 负责"生成"，并在后台 tick 里挂一次。

```
[后台 tick]  dream_agent.ensure_dream_pending()   ← 新素材 → LLM 生成 → memory["dream"] = pending
   ↓ 次日用户打开
[GET /proactive]
   trigger.detect_trigger()      ← 新加 dream 分支（不清 flag，交给引擎）
   decision.should_send()        ← 不改
   cooldown.check()              ← 不改
   message_agent.generate_message() ← 新加 dream 分支的 prompt
   engine 标记 dream.delivered = True   ← 改成"投递成功才清"
```

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `backend/funcation/dream_agent.py` | **新增** | 生成梦境 + 触发时机判定 |
| `backend/funcation/proactive/proactive_trigger.py` | 修改 | 加 `dream` 分支 |
| `backend/funcation/proactive/proactive_engine.py` | 修改 | 投递成功后标记 `delivered` |
| `backend/funcation/proactive/proactive_message_agent.py` | 修改 | 加 dream 的 prompt |
| `backend/funcation/world_tick_scheduler.py` | 修改 | tick 后调 `ensure_dream_pending` |
| `backend/tests/test_dream.py` | **新增** | 生成/去重/不打扰/投递标记 |

---

## Task 1: 生成模块 `dream_agent.py`

- [x] **Step 1**: 存储格式
      ```python
      memory["dream"] = {"text": str, "date": "2026-10-14", "delivered": False}
      memory["dreams"] = [{"date": ..., "text": ...}]   # 历史，最多留 20 条
      ```
      放**主 JSON**（小状态，和 `proactive` 并列）—— 它是"一条待投递的短消息"，不是检索对象。
- [x] **Step 2**: `generate_dream(mc, user_id, character_id, character) -> str`
      素材取 `mc.get_chat_summary()`（**真源现在在 `.rag.json`，不碰向量库**）+ profile/story，
      LLM 温度略高，要求 2-3 句、角色第一人称、"梦"的意象。
- [x] **Step 3**: `ensure_dream_pending(...) -> bool`，四条闸门：
      1. 已有 `delivered=False` 的梦 → **不叠加**（否则攒一堆排队骚扰用户）
      2. 今天已经生成过 → 跳过（一天一场）
      3. `last_chat_time[:10] <= dream.date` → **那天之后没聊过天，没素材**，跳过
      4. `chat_summary` 为空 → 跳过
      LLM 失败**只记日志返回 False**，绝不影响后台 tick。
- [x] **Step 4**: `_record_dream()` 落盘：追加到 `dreams`（裁剪到 20）+ 设 `dream` pending（带 `summary_date`）

## Task 2: 接进主动消息四段式

- [x] **Step 1**: `detect_trigger` 加 dream 分支：
      ```python
      dream = memory_data.get("dream") or {}
      if dream.get("text") and not dream.get("delivered"):
          return {"trigger": "dream", "reason": "想分享昨晚的梦", "dream": dream}
      ```
      ⚠️ **不在这里清 flag** —— 后面还可能被冷却拦下，清了梦就丢了。
      这和现有分支（就地清 `changed = False`）不同，是刻意的。
- [x] **Step 2**: `proactive_engine.run()` 在 `generate_message` **成功后**清：
      `memory_data["dream"]["delivered"] = True`
- [x] **Step 3**: `generate_message` 加 dream 分支的 prompt：把梦境原文给 LLM，
      要求"转述成角色自己说出来的一句话"，2-3 句、不打招呼、不说"在吗"。

## Task 3: 挂到后台 tick

- [x] **Step 1**: `_tick_one_user` 里 world event tick **之后**调
      `dream_agent.ensure_dream_pending(...)`（走 `run_in_executor`，别阻塞）
- [x] **Step 2**: 后台 tick 本来就有的 `RUN_BACKGROUND_TICK=0` 开关要照样生效
      （关掉时只是不生成梦，主动消息本身还能手动触发）
- [x] **Step 3**: 文档说明：**没有后台调度器时梦不会自动生成**，
      需要的话可以手动调 `dream_agent.ensure_dream_pending()`

## Task 4: 测试

- [x] 有素材（`last_chat_time` 在梦之后）→ 生成，`dream.pending` 落盘
- [x] `delivered=False` 已存在 → **不叠加**（不打扰）
- [x] 梦之后没聊过 → 跳过
- [x] 今天已生成 → 跳过
- [x] `chat_summary` 为空 → 跳过
- [x] LLM 抛异常 → 不抛，后台 tick 不受影响
- [x] `detect_trigger` 在冷却拦下的情况下**不清 flag**
      （否则梦被吃掉却没人收到）
- [x] 引擎在 `generate_message` 成功后才标记 `delivered`
- [x] 历史 `dreams` 裁剪到 20

## Self-Review

**1. Spec coverage**：P3-D2 要"凌晨 LLM 睡前总结 → 次日主动说"，Task 1-4 完整覆盖。✅
**2. 最大风险 = "骚扰用户"**：一天多场梦、攒着不发、重复内容 ——
   三条闸门（不叠加 / 一天一场 / 有新素材才生成）+ 投递成功才清。✅
**3. 复用而非新造**：素材走 `chat_summary`（真源刚统一），投递走既有四段式。
   新增的只有"生成"这一个环节。✅
**4. 失败隔离**：LLM 挂了不能影响后台 tick，也不能影响主流程。✅
**5. 不过度设计**：没做"梦境检索"（不入向量库）、没做 UI 日记时间线
   （只留 20 条历史，先把主动消息这条链路跑通）。都记进 Known Issues。✅

## Known Issues

- **后台 tick 才有自动生成**：CI / `RUN_BACKGROUND_TICK=0` 下梦不会自动出现。
  手动入口在 `dream_agent.ensure_dream_pending()`。
- **一天一场**是刻意的。想改成"一场梦含多天"要重新设计闸门。
- **没有 UI 日记线**：历史只存在 `memory["dreams"]` 里（最多 20 条），
  前端看不到。要做的话是 P3-D2 的下一截。

---

## 执行结果（2026-10-14）

4 个 Task 全部完成，13 条测试全过，端到端 6 步验证通过。

### 设计如约落地

```
[后台 tick]  dream_agent.ensure_dream_pending()   ← 有新素材 → LLM 生成 → pending
[GET /proactive]
   detect_trigger()        ← 新加 dream 分支（**只读不清**）
   decision / cooldown     ← 不改
   generate_message()      ← 新加 dream 的 prompt
   mark_delivered()        ← 投递成功才清
```

**三条闸门**（别骚扰用户）：
1. 已有未投递的梦 → **不叠加**（否则攒一堆排队）
2. 今天已生成 → 一天一场
3. `last_chat_time` 不晚于上一场梦 → 没新素材，跳过

`_dream_due()` 刻意返回**原因**而不是布尔 —— 后台任务要能解释"梦怎么没来"。

### "梦不能被吃掉"这条单独验了

现有分支（world_event / story / relation / state）都是**在 `detect_trigger` 里就地清 flag**
的历史写法 —— 清了就找不回来。梦沿用它会"被冷却拦下后凭空消失"。
所以：
- `detect_trigger` **只读**
- 由 `proactive_engine` 在 `generate_message` **成功后**调 `mark_delivered()`

端到端专门验了：冷却拦下 → 消息没发出去 → **梦仍 pending**（没有被标记成已投递）。

### 端到端（真机 6 步）

① 生成 → pending 落盘 ✅
② `detect_trigger` 返回 dream ✅
③ **冷却拦下 → 梦不丢** ✅
④ 冷却解除 → 投递成功 → `delivered=True` ✅
⑤ 投递后不再触发 ✅（触发的是既有的 `state` 分支，不是梦 —— 正确）
⑥ 历史记录 1 条 ✅

### ⚠️ 又踩了一次"测试污染真实库"

`tests/test_dream.py` 初版**没 monkeypatch `memory_rag.PERSIST_DIR`**，
于是 `_index_to_rag` / `_migrate_from_chroma` 读写**真实开发库** ——
跑一轮把 `u1_linwan_chat_summary` 写进 10 条垃圾，还被 `_migrate_from_chroma`
**反向读回来**（所以测试看到"凭空出现"的聊天摘要，一度以为是逻辑 bug）。

这已经是 `PERSIST_DIR` 绝对路径这个坑的**第三次**。
修法：fixture 里 patch `PERSIST_DIR` + `_chroma_persist_dir` + `release_client()`。
**已清理**：`u1_linwan_chat_summary` 10 条垃圾清掉，回到 **12 集合 / 22 记录**。

有意思的是：**真源文件一个字节都没被污染**（`chat_summary = []`）——
脏的只有索引。这恰好是 P0 §1-7 那个设计在起作用。

**给下一个碰记忆测试的人的信号**：`_migrate_from_chroma` 会**从向量库反向读**，
所以 patch 索引路径不只是"写隔离"，也是"读隔离"。

### 其他

- 接进 `world_tick_scheduler._tick_one_user`：world tick **之后**跑，
  走 `run_in_executor` 不阻塞；`RUN_BACKGROUND_TICK=0` 时照样生效（只是不启动调度器）
- `generate_message` 的 dream prompt 单独一份要求（"我昨晚梦到……"开头、画面要具体）

### 验证

- 后端 **380 passed**（367 → +13），**本机 + 模拟 CI 都过**
- 前端零改动全绿
- **开发库无污染**（12 集合 / 22 记录）
- 端到端 6 步全过

### 仍未做（记在 Known Issues）

- CI / `RUN_BACKGROUND_TICK=0` 下**梦不会自动生成**。手动入口在
  `dream_agent.ensure_dream_pending()`
- **没有 UI 日记线** —— 历史只在 `memory["dreams"]`（最多 20 条），前端看不到。
  那是 D2 的下一截
- 一天一场是刻意的；要做"一场梦含多天"得重新设计闸门
