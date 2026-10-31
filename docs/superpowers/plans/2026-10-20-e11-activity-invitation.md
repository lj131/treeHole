# E11 AI 主动发起活动 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 她主动约你出去 ——「周末有个摄影展，要不要一起去？」你接受或拒绝，
**并且她记得这个约定**（下次聊天会提起）。

## ⚠️ 计划外项目（已与用户确认）

推进计划里的 E11 是「数据导出」，**不是这一项**。本方案是用户新提的需求，
记录在此以便追溯。做完后在推进计划里单独标注，不覆盖原 E11。

## Task 0: 现状（**已查证**）

| 事实 | 位置 |
|---|---|
| `memory` 里**没有** invitations / activity 任何字段 | `data/memories/1/linwan.json` |
| `funcation/` 下**没有任何**邀请/活动代码 | grep 证实 |
| `proactive_engine.run()` 返回一句主动消息（无状态、无后续） | `proactive_engine.py` |
| E7 已做「主动来电」（即时通话，无后续） | `incoming_call.py` |
| E8 的插嘴就是 `done` 之后追加一次小 LLM 调用 | `api.py:_make_interjection` |

**和已有的区别**：E7 来电是"想听听你的声音"（打完就完），
proactive 是一句问候。**活动邀请有具体内容、有时间、有接受/拒绝、有后续记忆** ——
这是闭环，不是一句话。

## 核心闭环（缺一不可）

1. **发起**：她回复完之后，判断"要不要顺势约你" → 生成邀请
2. **呈现**：聊天里一张**邀请卡片**（活动 + 她说的话 + 接受/拒绝）
3. **回应**：用户点接受/拒绝 → 落库
4. **沉淀**：**接受后 prompt 里带这个约定**，下次聊天她会提起
   （第 4 步是闭环的关键 —— 否则她"忘了"就很假）

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `backend/funcation/activity_invite.py` | **新增** | **纯函数**：该不该约 + 邀请卡数据结构 |
| `backend/tests/test_activity_invite.py` | **新增** | 门槛/冷却/不重复/坏输入 |
| `backend/api/api.py` | 修改 | `done` 后追加邀请 + `POST /activity/invitation/answer` |
| `backend/funcation/prompt.py` | 修改 | **接受后注入约定**（闭环第 4 步） |
| `front/src/api/activity.ts` | **新增** | answer 请求 |
| `front/src/components/ActivityInviteCard.vue` | **新增** | 邀请卡片 |
| `front/src/stores/chatStore.ts` | 修改 | `onInvitation` + 卡片状态 |

## Task 1: 决策（纯函数）

- [ ] `should_invite(memory_data, *, now, seed) -> dict | None`
- [ ] 五条约束（都有理由）：
      1. **不重复**：已有 `pending` 邀请时不再约（用户还没答呢）
      2. **拒绝冷却 3 天**：被拒绝是明确信号，3 天内别再约
      3. **好感度门槛**：`favorability < 30` 不约 —— 不熟就约太突兀
      4. **时段**：复用 `circadian`，深夜不约人
      5. **概率 25%**（seed 用**内容 hash**，同 E8 的教训：分钟粒度会让
         同一分钟内连发的消息共享判定）
- [ ] `build_invitation_record(...)` / `build_answer_record(action, now)`
      —— 只回本次字段，调用方 merge

## Task 2: 后端

- [ ] `/chat/stream` 的 `done` 之后追加邀请（复用 `_make_interjection` 的位置与模式）
      - 邀请 prompt 要短：活动名 + 她的一句话 + 时间
      - **失败只记日志**（不影响主链路）
- [ ] `POST /activity/invitation/answer`：`{"action": "accepted"|"declined"}`
      - 幂等、非法 action → 400
- [ ] **闭环第 4 步**：`prompt.py` 读 `activity_invitation`
      - `status=accepted` → 注入"你们约好了要去 X"（她会提起）
      - `status=pending` → 不注入（用户还没答）

## Task 3: 前端

- [ ] `ActivityInviteCard.vue`：卡片 + 活动名 + 她的话 + 接受/拒绝
      - 已答的卡片置灰显示结果（不再显示按钮）
- [ ] `chatStore.onInvitation` → 挂到当前会话（一张卡片）
- [ ] 接受/拒绝 → POST → 本地状态更新

## Task 4: 测试

- [ ] `test_activity_invite.py`：
      - **pending 时不重复约** / **拒绝后冷却期内不约** / 冷却边界
      - **好感度低于门槛不约**（边界值）/ 无 favorability 字段时的兜底
      - 深夜不约 / 概率生效 / 确定性
      - 坏输入（None / 坏时间戳 / favorability 是字符串）不崩
      - answer 记录只回本次字段 / 非法 action 不写
- [ ] **验证"测试能失败"**（用 Edit 不用 cp）：去掉好感度门槛 → 断言红

## 最终验收

- [ ] 后端全绿；前端 type-check / lint / vitest 全绿
- [ ] **端到端实测 + 截图**：聊到触发邀请 → 卡片出现 → 点接受 →
      **再发一条消息，她的回复里提到这个约定**（闭环第 4 步必须看到）
- [ ] 确认不触发时安静（无卡片）

## Self-Review

**1. Spec coverage**：要"她约你 + 你回应 + 她记得" → Task 1-2 全覆盖。✅
**2. 最大风险 = 约了但不记得（假闭环）**：Task 2 的 prompt 注入是必须的，
   没有它用户接受后发现她再也不提，比不约更糟。✅
**3. 不破坏现状**：邀请是 `done` 后的额外事件，主链路不变。✅
**4. 门槛保守**：好感度 < 30 不约、深夜不约、25% 概率、拒绝冷却 3 天
   —— 宁可不约，不可骚扰。✅
**5. 不过度设计**：不做改时间/多轮协商、不做活动过程模拟、不做日历。✅

## Known Issues

- 邀请是"事后追加"，不是对话中自然带出（用户已在读回复时卡片出现）
- ~~不做活动完成后的结算（加分/奖励）~~ → **2026-10-31 已补**（见下节）
- 一次只有一个 pending 邀请

---

## 补：约定的"过程"（2026-10-31，第三档产品深化）

**原设计的两个真 bug**（不是"没做"，是"做错了"）：

1. `accepted` 是**终态** —— prompt 永远说"你们约好了要一起去"，说了几个月也不去
2. `accepted` **不挡新邀请** —— 下一次邀请会把那条约定**覆盖掉**（静默丢约定）

**状态机**：

```
pending ──接受──→ accepted ──到点(settle)──→ done（落一条长期记忆）
   └─48h 没人回─→ 过期（原来会永久挡住所有后续邀请）
```

**三个关键决定**：

1. **`scheduled_at` 用绝对时间**：生成时 LLM 给 `when_hours`（1-72，和活动描述一致），
   接受时换算。之后判断"到点没有"只看这一个字段 —— **不解析自然语言**。
   老数据没有它 → `answered_at + 20h` 兜底。
2. **懒结算，不挂 tick**：`api._settle_activity_due()` 在每轮聊天开头跑。
   tick 在本地/CI 是关的，挂 tick = 本地永远不发生。
   **没到点时零 IO**（先跑纯函数判断）。
3. **`done` 之后是回忆**：`activity_prompt()` 分四种说法
   （还没到 / 几小时内 / 已过点 / 已去过），已去过的变成"你们前几天一起去了X"。

**验证**：真实 `MemoryCenter` 上跑过一遍 —— `accepted`（约定时间已过 2h）
→ 聊天时自动转 `done`、`.rag.json` 的 `long_memory` 末尾出现
"我们约好一起去傍晚的河堤，后来真的去了。那天过得很舒服。"，
再跑一次 `settle_due()` 返回 None（幂等）。数据已还原。

**测试 +20**（`test_activity_invite.py` 25 → 39，新增 `test_activity_settle.py` 6）：
状态机四态、pending 过期、accepted 不再被覆盖、结算幂等、结算失败不抛、
`when_hours` 非法回退默认值。**验证有牙齿**：去掉 `add_long_memory` → 2 条红；
pending 永不过期 → 1 条红。
