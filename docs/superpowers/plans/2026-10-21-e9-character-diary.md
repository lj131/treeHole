# E9 角色日记本 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 角色用**第一人称写日记**，用户可以"偷看"。

## Task 0: 现状（**已查证**）

| 事实 | 位置 |
|---|---|
| `dream_agent` 引擎完整：`_dream_due` / `_build_prompt` / `generate_dream` / `ensure_dream_pending` / `_record_dream` / `mark_delivered` | `funcation/dream_agent.py` |
| **但从未接入任何 HTTP 接口**（`grep dream api/api.py` = 0） | 同上 |
| 触发链：`world_tick_scheduler` → `ensure_dream_pending()`；`proactive_engine` → `mark_delivered()` | 已存在 |
| ⚠️ **后台 tick 在这环境是禁用的**（`RUN_BACKGROUND_TICK=0`，启动日志明确打出） | `world_tick_scheduler.py` |
| 真实数据：`dreams: []`、`dream: null` —— **从未生成过任何一场梦** | `data/memories/1/linwan.json` |

## ⚠️ 两个关键设计决策（都源于上面的查证）

### 决策 1：**懒生成**，不依赖后台 tick

后台调度器被禁用（本地默认、CI 也没有）→ 如果只把日记接进 tick，
**本地和 CI 永远看不到一篇日记**。

所以改成：用户打开日记面板时，**如果今天还没写，就当场写一篇**
（同步等 1-3 秒）。这更贴合"偷看"的体验，也不依赖调度器。

### 决策 2：**新写 `diary_agent.py`，不硬复用 dream_agent**

复用引擎看似省事，但**四处都不同**，硬塞 mode 分支会把两个功能耦死：

| | 梦境（已有） | 日记（E9） |
|---|---|---|
| 文体 | 荒诞、跳跃 | 平实、第一人称"今天……" |
| 素材 | 用户聊天摘要 `chat_summary` | **NPC 互动 + 世界事件**（计划原文要求） |
| 触发 | 一天一场 + 投递制（`delivered`） | 一天一篇 + 懒生成 |
| 存储 | `dream` / `dreams` | **`diary` / `diaries`（新字段，不混在一起）** |

**计划原文说"视角与梦境不同"** —— 上面的差异表就是这个要求的落地。

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `backend/funcation/diary_agent.py` | **新增** | 纯决策 + 生成 + 落库（懒生成） |
| `backend/tests/test_diary_agent.py` | **新增** | due 判定 / 素材为空 / 重复调用只写一篇 / 长度上限 |
| `backend/api/api.py` | 修改 | `GET /diary`（懒生成，只读） |
| `front/src/api/diary.ts` | **新增** | 请求 |
| `front/src/components/DiaryModal.vue` | **新增** | 日记面板（"偷看"感） |
| `front/src/views/Chat.vue` | 修改 | 工具栏加「日记」入口 |

## Task 1: `funcation/diary_agent.py`

- [ ] `_diary_due(memory_data) -> bool`：今天还没写（`diary.date != today`）
      - 刻意比 `_dream_due` 简单：**梦境要"投递制"是因为它会被主动消息带出来**，
        日记没有投递环节，用户打开就是读
- [ ] `_build_diary_prompt(character, npc_interactions, world_events)`
      - 第一人称、平实、**从 NPC 互动和世界事件取材**
      - 明确禁止元叙述（"这是一篇日记"）和科幻味的梦语
- [ ] `generate_diary(...) -> str`：调 LLM，剥引号，超长丢弃
- [ ] `ensure_diary(mc, user_id, character_id, character, memory_data) -> dict`
      - **懒生成**：有今天的就直接返回，没有才写
      - **绝不抛**（后台/UI 都不能因为它 500）
      - **落盘前重新 load 再只 merge 自己的字段**（防 lost update，
        照抄 `dream_agent._record_dream` 的成熟做法）
- [ ] 存储：`memory["diary"]`（今天）+ `memory["diaries"]`（历史，保留最近 N 篇）

## Task 2: 后端端点

- [ ] `GET /diary`（`require_approved`）
      - 返回 `{"diary": {...} | null, "history": [...]}`
      - 今天没有 → 懒生成一篇；素材不足 → 返回 null（**不报错**）
      - 历史给最近 7 篇（"偷看"过去的日记）

## Task 3: 前端

- [ ] `DiaryModal.vue`：日期 + 正文 + 最近几篇（左右/上下切换）
      - 视觉做得像"翻日记本"（衬线/手写感），和聊天的即时感区分开
      - **加载态**：懒生成要 1-3 秒，要有明确的"她正在写…"提示
      - 只读（不提供编辑 —— 日记是她写的）
- [ ] Chat.vue 工具栏加「日记」按钮（和群聊/约会并列）

## Task 4: 测试

- [ ] `test_diary_agent.py`：
      - 今天已有 → 不重复生成（**懒生成 must be idempotent**）
      - 今天没有 + 有素材 → 生成并落库（`diary` + `diaries`）
      - **素材为空 → 返回 None 且不调 LLM**
      - 历史超长被截断到上限
      - 落库只 merge 自己的字段（不动 `dream`/`favorability` 等）
      - LLM 抛异常 → 不崩、返回 None
- [ ] **验证"测试能失败"**（用 Edit 不用 cp）：去掉"今天已有就跳过" → 重复生成的断言红

## 最终验收

- [ ] 后端全绿；前端 type-check / lint / vitest 全绿
- [ ] **端到端实测**：打开日记 → 看到真实生成的第一人称日记（截图）
      → 内容取材自 NPC 互动/世界事件（**不是**用户聊天摘要）
- [ ] 再打开一次 → **不重复生成**（幂等）

## Self-Review

**1. Spec coverage**：要"角色写日记，用户可偷看" → Task 1-3 全覆盖。✅
**2. 最大风险 = 依赖被禁用的 tick**：决策 1（懒生成）就是为解决它。✅
**3. 与梦境的区分**：决策 2 的四处差异表，**计划原文"视角不同"的要求落地**。✅
**4. 不过度设计**：不做日记编辑、不做"藏起来不给她看"、不做分享。✅
**5. 幂等**：懒生成必须"今天已有就跳过"，否则用户每开一次面板就烧一次 LLM。✅

## Known Issues（预期）

- 懒生成有几秒延迟（首屏要有 loading 态）
- 素材不足时返回 null（不是编一篇空的）
- 历史只保留最近 N 篇（不做归档/导出）
