# E7 主动来电 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** **她主动打过来** —— 不是你点按钮，而是手机响，她来找你。

**为什么做:** 实测查证：语音通话底层**已经全通了** ——
后端 `WS /voice/call`（mic → DeepSeek → Edge TTS → base64 WAV 回传）、
前端 `voiceCallStore` + `VoiceCallButton` + `VoiceCallModal`（完整通话 UI）。
但**只有用户主动发起**这一条路。"她打过来"是陪伴感最强的一件事，
而它缺的只是一个"来电"入口。

## Task 0: 现状（**已查证**）

| 已有 | 位置 |
|---|---|
| `WS /voice/call` 纯 WebSocket 语音通话 | `backend/api/websocket.py:25` |
| `VoiceCallModal.vue` / `VoiceCallButton.vue` / `voiceCallStore` | 前端 |
| `voiceCallStore.startCall(charId)` / `endCall()` | 接听后直接复用 |
| `/proactive` 端点返回 `{message: str \| None}` | `api.py:1829` |

**缺的**：来电判定 + 来电 UI + 接听/拒绝 + 冷却。

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `backend/funcation/incoming_call.py` | **新增** | **纯函数**：要不要打 + 反馈落库结构 |
| `backend/tests/test_incoming_call.py` | **新增** | 决策边界 / 冷却 / 时段 / 非法输入 |
| `backend/api/api.py` | 修改 | `GET /voice/incoming` + `POST /voice/incoming/answer` |
| `front/src/components/IncomingCallModal.vue` | **新增** | 来电 UI（响铃/接听/拒绝） |
| `front/src/stores/incomingCallStore.ts` | **新增** | 轮询 + 状态 |
| `front/src/views/Chat.vue` | 修改 | 挂载 `IncomingCallModal` |

## Task 1: 决策（纯函数，**无状态**）

- [ ] `should_call(memory_data, *, now, answered_at, declined_at, seed) -> dict | None`
      - 返回 `{"reason": ..., "greeting_hint": ...}` 或 `None`（不该打）
- [ ] 四条约束（都有理由）：
      1. **时段**：只在她"醒着"的时段打（复用 `circadian`，凌晨 3 点不响）
      2. **冷却**：`declined_at` 后 **2 小时内不再打**（被拒绝还打 = 骚扰）
      3. **间隔**：距 `answered_at` 太近也不打（刚接完又打 = 烦）
      4. **概率**：可用 `seed` 注入做确定性伪随机（可测）
- [ ] `build_answer_record(action, now) -> dict` —— 落库结构（`answered`/`declined` + 时间）

**为什么决策是纯函数**：频率可控 + 可单测（不用等真时间、不依赖 LLM）。

## Task 2: 后端端点

- [ ] `GET /voice/incoming`（`require_approved`）：返回
      `{"incoming": bool, "character_id": ..., "reason": ...}`
      - `incoming=false` 时前端什么都不做（**不弹**）
- [ ] `POST /voice/incoming/answer`：body `{"action": "answered"|"declined"}`
      - 写进 `memory_data["incoming_call"]`（记录 + 冷却用）
      - **幂等**：重复 POST 不崩、不重复记

## Task 3: 前端来电 UI

- [ ] `IncomingCallModal.vue`：
      - 角色头像 + 名字 + "**给你打电话**" + 拒绝/接听两个大按钮
      - 响铃：**WebAudio 生成**（不引音频文件，参考 E2 自绘思路）
      - **接听** → 复用 `voiceCallStore.startCall(charId)`（弹已有 `VoiceCallModal`）
      - **拒绝** → POST declined + 关闭
      - **15 秒无操作自动挂断**（真的手机也是这样，且避免一直响）
- [ ] `incomingCallStore`：轮询（60s 间隔，**页面可见时才轮**）
      - 发现 incoming → 弹窗 → **立即 POST answer**（否则别的页面/刷新会重复弹）
- [ ] `Chat.vue` 挂载组件

## Task 4: 测试

- [ ] `test_incoming_call.py`：
      - 深夜不响（复用 circadian 的 late_night）
      - **被拒绝后 2 小时内不响** / 超时恢复
      - 刚接完不久不响
      - 首次（无任何记录）可以响
      - 确定性（同 seed 同结果）
      - 非法输入（None/坏时间戳）不崩
- [ ] **验证"测试能失败"**（用 Edit 不用 cp）：去掉冷却 → 断言红

## 最终验收

- [ ] 后端全绿；前端 type-check / lint / vitest 全绿
- [ ] **端到端实测 + 截图**：构造"该来电"的状态 → 弹出来电界面 → 点接听进入通话
- [ ] 确认**不弹时**前端安静（无铃声、无 UI）

## Self-Review

**1. Spec coverage**：要"她打过来" → Task 1-3 全覆盖。✅
**2. 最大风险 = 太频繁/不合时宜**：凌晨 3 点响铃、被拒绝后反复打。
→ 时段约束 + 双冷却 + 概率，全部可测。✅
**3. 复用优先**：接听直接复用 `startCall`，不新建通话链路。✅
**4. 不过度设计**：不做铃声文件（WebAudio 生成）、不做通话记录页、
不做未接来电徽章推送。✅
**5. 幂等**：轮询发现来电后立即 POST answer，防止刷新/多页面重复弹。✅

## Known Issues（预期）

- 轮询有 60s 延迟（WS 推送是更好的方案，但要多改一条连接）
- WebAudio 响铃在浏览器自动播放策略下可能被拦（需用户先有交互）
- 不做"通话中挂断后的未接提示"（那是 E8 的范围）
