# E1 世界日报 / 时间线 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用户离线一段时间回来，能看到"这段时间世界发生了什么" —— 一条按时间排序的时间线。

**为什么做这个（而不是继续加新功能）:** `world_tick_scheduler` 每 30 分钟演化世界、
NPC 关系在变、剧情在推进、梦境在生成 —— 但用户只看到**零散几条主动消息**，
根本不知道世界一直在动。D2（梦境）/ D3（挂件）/ D4（群聊旁观）是三个"点"，
日报是把它们串成"面"的那个东西。

**Architecture:** **纯聚合，零新增 LLM 调用**。把已经存在但散落各处的数据
读出来、统一时间格式、排序、返回。前端只负责分组渲染。

## Task 0: 摸清数据源（**已完成**）

| 源 | 时间字段 | 格式 | 位置 |
|---|---|---|---|
| NPC 互动 | `time` | `"2026-06-05 17:13"` | `world_state.npc_registry.recent_interactions[]` |
| NPC 八卦 | `time` | 同上 | `.gossip[]` |
| 世界影响 | `time` | 同上 | `.world_impacts[]` |
| 世界事件 | `created_at` / `finished_at` | `"2026-06-17"` | `current_events[]` / `history_events[]` |
| 剧情 | `started_at` / `last_advance_date` | `"2026-10-14"` | `memory.stories[]` |
| 剧情归档 | 同上 | 同上 | `memory.story_history[]` |
| 梦境 | `date` | `"2026-10-14"` | `memory.dreams[]` |
| 主动消息 | `last_time` | **ISO** `"2026-10-15T19:43:55.611966"` | `memory.proactive` |
| 记忆事件 | `time` | 待确认 | `{char}.rag.json` 的 `events[]` |
| 关系里程碑 | `date` | `"2026-10-12"` | `memory.self_awareness.milestones[]` |

**⚠️ 核心难点：三种时间格式混杂**（空格分隔 / 纯日期 / ISO）。
必须先写一个能吃下所有格式的解析器，解析不了的**丢弃但记日志**（不静默）。

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `backend/funcation/digest.py` | **新增** | 纯函数：时间解析 + 条目构建 + 排序。**无 IO**，方便单测 |
| `backend/api/api.py` | 修改 | `GET /world/digest` |
| `backend/tests/test_digest.py` | **新增** | 时间解析边界 + 条目构建 + 排序 + 过滤 |
| `front/src/views/DigestView.vue` | **新增** | 时间线页面 |
| `front/src/api/world.ts` | 修改 | `getWorldDigest()` |
| `front/src/router/index.ts` + `App.vue` | 修改 | `/digest` 路由 + 导航 |
| `front/src/utils/digest.ts` | **新增** | 分组/格式化纯函数（可单测） |

## Task 1: 时间解析（最容易出错，先做）

- [ ] `parse_digest_time(raw) -> datetime | None`
      - `"2026-06-05 17:13"` → 把空格换成 `T`
      - `"2026-06-17"` → 补 `T00:00:00`
      - ISO 带微秒 → 直接用
      - 空串 / 非法 / `None` → `None` + debug 日志
- [ ] **所有解析失败都不能抛** —— 一条坏数据不该让整个日报 500

## Task 2: 条目构建

- [ ] `build_entries(world_state, memories, *, now, days) -> list[Entry]`
      - `world_state` 取一份（世界事件 / NPC 互动 / 八卦 / 世界影响）
      - `memories` 遍历**该用户的所有角色**（梦境 / 剧情 / 主动消息 / 里程碑 / 记忆事件）
      - 每条形如 `{at, kind, title, detail, actors, character_id?}`
      - **时间窗过滤**：`at >= now - days`
      - **倒序排列**（最新在前）
- [ ] `kind` 取值：`world_event` / `npc_interaction` / `gossip` / `world_impact` /
      `story` / `dream` / `proactive` / `milestone` / `memory_event`
- [ ] `summarize(entries) -> dict` 给前端做"一句话概览"

## Task 3: API

- [ ] `GET /world/digest?days=3`（默认 3 天，覆盖一个周末）
      - 需登录（`require_approved`）—— 数据是 per-user 的
      - 返回 `{generated_at, range, entries, counts, summary}`
- [ ] **空数据也要 200 + 空数组**（前端渲染空态，不是错误）

## Task 4: 前端

- [ ] `views/DigestView.vue`：
      - 顶部：时间范围切换（1 / 3 / 7 天）
      - 按**天分组**（今天 / 昨天 / 具体日期），组内倒序
      - 每种 kind 有自己的图标 + 配色（世界事件 🌍 / NPC 互动 👥 / 梦境 🌙 / 剧情 📖 / 主动消息 💬 / 里程碑 ✨）
      - 空态："这段时间世界很安静" + 提示可以切更长范围
- [ ] 路由 `/digest` + 导航入口「📰 世界日报」
- [ ] 加载失败 / 未登录都要有兜底，不白屏

## Task 5: 测试

- [ ] `test_digest.py`：
      - **三种时间格式都能解析**（这是最容易回归的地方）
      - 非法/空值返回 None 且不抛
      - 时间窗过滤正确（边界：正好等于 `now - days`）
      - 排序倒序
      - 空输入 → 空列表（不崩）
      - 缺字段的坏数据被跳过而不是让整体失败
- [ ] `digest.spec.ts`（前端）：
      - 按天分组
      - 空列表 → 空态
      - 同一天的多条按时间倒序
- [ ] **验证"测试能失败"**：故意改坏解析（比如不处理空格格式），确认测试红

## 最终验收

- [ ] 后端 type/pytest 全绿；前端 type-check / lint / vitest 全绿
- [ ] **端到端实测 + 截图**：真实数据下渲染出时间线
- [ ] 两种环境跑（本机 + `VOICE_CLONE_VENV=<不存在>` 模拟 CI）

## Self-Review

**1. Spec coverage**：E1 要"用户看到世界发生了什么"，Task 1-5 覆盖。✅
**2. 最大风险 = 时间解析**：三种格式混杂，且有坏数据。→ Task 1 单独做 + 专门测边界，
   解析失败**丢弃而非崩溃**。✅
**3. 零 LLM**：纯聚合，不拖慢任何东西，也不产生新成本。✅
**4. 不重复造**：复用 `world_state` / `memory` 已有字段，不加新存储。✅
**5. 不过度设计**：不做"日报推送"、不做导出、不做全文搜索。✅

## Known Issues（预期）

- 时间格式靠 `strptime` 系列硬解析，未来若新增第四种格式会静默丢弃（有日志）
- 世界事件只有日期粒度（`"2026-06-17"`），当天内无法排序 → 同日事件按录入顺序
- 不做分页（`days` 上限 30，条目量可控）
