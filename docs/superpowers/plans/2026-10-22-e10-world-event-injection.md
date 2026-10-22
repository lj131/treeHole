# E10 世界事件手动注入 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用户手动加一个事件（"下周有校园祭"），**看 NPC 怎么反应**。

## Task 0: 现状（**已查证，含两次对我自己判断的纠正**）

| 事实 | 位置 |
|---|---|
| 事件结构完整：`id/title/description/importance(int)/status/progress/impact/world_id/created_at/finished_at` | `world_state/campus.json` |
| **`POST /world/event/create` 已实现手动注入**（+ AI 自动生成 + `apply_world_impact_to_user` 影响应用） | `api.py:1919` |
| `GET /world/events` / `POST /world/event/update` / `POST /world/tick` / NPC 互动模拟 | 均已存在 |
| **prompt 链路已通**：`status=="running"` 的事件注入 system prompt | `prompt.py:432` |
| 前端只接了 `/world/interactions`，**事件注入完全没 UI** | `api/world.ts` |

### 纠正 1（对我 10-21 判断的纠正）

我说过"`world_event` 只有 `{title, impact}`、没有 events 数组"——**查错了文件**：
那是 `worlds/campus.json` 的**世界设定**（静态背景）；
**动态事件**在 `world_state/campus.json` 的 `current_events`，结构一直很完整。

### 纠正 2（对我自己刚写的模块的纠正）

我一开始写了 `funcation/world_event_inject.py`（build_event / is_duplicate / prune），
写完发现 **`world_event_agent.create_event()` 已经做了全部这些事情**，
而且我的 `importance` 用字符串档位（low/medium/high）与真实数据（**int，如 6/7**）不一致。

→ **已删除该模块和它的测试**（`git status` 可证）。
E10 因此回归"**纯前端 UI**"，不引入第二套事件语义。

### ⚠️ 一个差点踩进去的坑

`WorldEventCreateRequest.importance` 是 **`int`（默认 5）**，
真实数据里也是 int（6、7）。我第一反应以为是"schema 与数据不一致的 bug"，
实际是**我自己按字符串档位调错了**。

**前端必须传 int**（1-10 这种量级），不是 "low/medium/high"。

## 权限（沿用已有实现，不改成 admin）

我原方案要求 `POST` 走 `require_admin`（怕普通用户污染公共世界）。
**实际已有端点是 `require_approved`**，且 `apply_world_impact_to_user()` 已按 mode
做了 per-user 处理（公共世界用 seen 去重）—— 设计者已经考虑过这件事。

→ **沿用 `require_approved`，不改权限**（改了会破坏现有行为）。

## Task 1: 前端 API 封装

- [ ] `front/src/api/world.ts` 加：
      - `getWorldEvents()` → `GET /world/events`
      - `createWorldEvent({title, description, importance})` → `POST /world/event/create`
      - ⚠️ `importance` 传 **int**（1-10），不是字符串

## Task 2: UI 组件

- [ ] `WorldEventPanel.vue`：
      - 注入表单：标题 / 描述 / 重要性（1-10 滑块或数字输入）
      - 「注入事件」按钮 → 调 create → 刷新列表
      - 进行中事件列表（标题 + 进度 + 重要性）
- [ ] 挂到 `DigestView.vue`（世界日报页 —— 用户已经在看"世界怎么了"）

## Task 3: 端到端验收

- [ ] 前端 type-check / lint / vitest 全绿
- [ ] **端到端实测**：在 DigestView 注入「下周有校园祭」→ 出现在进行中列表
      → **发一条聊天消息，NPC 回复里提到这件事**（prompt 链路真的通）
- [ ] 还原测试注入的数据（`git checkout -- backend/data/world_state/campus.json`）

## Self-Review

**1. Spec coverage**：要"手动加事件 + 看 NPC 反应" → Task 1-2（反应链路已存在）。✅
**2. 不重复造轮子**：删掉自己写的模块，复用 `world_event_agent`。✅
**3. 不破坏现有**：不动后端任何一行（只加前端）。✅
**4. 不过度设计**：不做事件编辑/删除/进度推进/定时失效/模板。✅
**5. 诚实记录**：两次纠正都写进方案，不掩盖"我一开始判断错了"。✅

## Known Issues（预期）

- 注入的事件不会自动结束（要等 tick 归档或手动 update）
- `progress` 恒为 0（没有推进 UI）
- 本面板和世界日报（E1）共用数据源但 UI 独立
