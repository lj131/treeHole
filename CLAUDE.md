# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Working Agreement (read first)

**改完代码就改 CLAUDE.md。** 任何改动只要影响下面任一项，必须在同一次提交里同步本文件（以及对应的 `backend/CLAUDE.md` / `front/CLAUDE.md`）：

- 新增 / 删除 / 改名 API 路由、agent 模块、store、路由页面
- 改 `/chat` 或 `/chat/stream` 的 agent 编排顺序、并发策略、降级策略
- 改 prompt 结构（数据源、规则数、attitude 文本）
- 改鉴权 / 配额 / 隔离规则
- 改 Docker / nginx / CI 配置
- 改环境变量、目录布局、数据文件 schema

文档过时比没有文档更糟 —— 后续 Claude 会照着错的描述改代码。如果一次改动让本文件某节失真却没时间更新，至少在该节加一行 `> ⚠️ STALE: <日期> <原因>` 标记。

## Project Overview

This is a **character-based AI chat system** (AI companion simulator) split across two independent sub-projects:

| Sub-project | Directory | Tech | Port |
|---|---|---|---|
| Backend API | `backend/` | Python FastAPI + DeepSeek | 8000 |
| Frontend SPA | `front/` | Vue 3 + TypeScript + Vite | 5173 (dev) |

Each sub-project has its own `.git` repo and its own `CLAUDE.md` with detailed architecture docs. Read those for deep dives — this file covers the **cross-cutting architecture** not obvious from either side alone.

## Quick Start (Full Stack)

### 本地开发

```bash
# Terminal 1 — Backend
cd backend
source .venv/Scripts/activate
uvicorn api.api:app --reload --host 0.0.0.0 --port 8000

# Terminal 2 — Frontend
cd front
npm install
npm run dev
```

### Docker 部署

```bash
# 1. 准备环境变量（复制 .env.example 并填入真实 key）
cp .env.example .env

# 2. 构建并启动
docker compose build
docker compose up -d

# 3. 验证
curl http://localhost/api/health        # → {"status": "ok"}
curl http://localhost/api/characters    # → 角色列表
# 浏览器打开 http://localhost → 前端 SPA
```

**架构**：nginx 反向代理（`/`→前端SPA，`/api/*`→后端，`/voice/*`→WebSocket）。前端 API 地址通过 `VITE_API_BASE` 构建时环境变量控制（本地 `http://127.0.0.1:8000`，Docker `/api`）。

## Cross-Cutting Architecture

### Data Flow: Chat Message Lifecycle

**前端默认走 SSE 流式 (`POST /chat/stream`)**；非流式 `POST /chat` 仅作兜底，仍然存在但 chatStore 不再调用。

```
[用户在 Chat.vue 输入]
  → chatStore.send(message) → sendChatStream() (front/src/api/chat.ts)
  → POST /chat/stream  (SSE: text/event-stream)
  ─────────────── 后端 (backend/api/api.py:chat_stream) ───────────────
  Phase 1+2 关键路径 — 加载数据 + 构建 Prompt（按依赖图分轮 asyncio.gather 并发）
           轮 1：peek recall 缓存（同步几 ms，未命中 → fire-and-forget 后台
                 warm，本次用 FALLBACK_COLLECTIONS）+ messages | mem | world 并行
           轮 2：world_state | memory_rag.retrieve_memories 并行
           轮 3：interaction_agent.build_social_prompt_for_character
           轮 4：prompt.build_system_prompt
  Phase 3  非关键 agent — asyncio.create_task(_bg_agents()) 后台并发
           ├─ world_event_agent.tick
           ├─ story_agent.check_story + sync + RAG sync
           └─ unified_state_agent (画像+好感度+状态 三合一) + RAG sync
  Phase 4  DeepSeek stream=True 在独立线程跑，token 经 asyncio.Queue +
           loop.call_soon_threadsafe 即时唤醒协程（无 sleep 轮询）
           → 逐 token 推送 SSE: {"token": "你"}
           响应头带 X-Accel-Buffering: no，避免 nginx 缓冲 SSE
  Phase 5  yield {"done": true, "favorability": ...} 后立即关闭 SSE 连接
           保存历史 + memory_agent.extract_memory + record_usage + 等待 _bg_agents
           全部移到 asyncio.create_task(_post_process(...)) 后台跑，不阻塞前端
  ─────────────────────────────────────────────────────────────────
  ← 前端 sendChatStream 用 fetch + ReadableStream 逐行解析
  ← chatStore 推占位 assistant 消息，loading=true 显示 typing 气泡
  ← 首 token 到达 → streaming=true，typing 气泡消失，token 拼进占位气泡
  ← onDone → loading=false / streaming=false，后台拉状态
```

**性能特征（实测）**：首 token 延迟约 900ms（recall 缓存命中）/ 1300ms（首次 + 后台 warm recall）。`_bg_agents` 在主回复同时跑；`_post_process` 在 SSE 关闭后跑，前端 `loading` 立即清掉。

### 流式 vs 非流式：何时用哪个

| 场景 | 接口 | 说明 |
|---|---|---|
| 普通聊天（前端 UI） | `/chat/stream` | 默认。SSE 逐 token，非关键 agent 后台并发 |
| 兜底 / 脚本调用 / 不支持 SSE 的客户端 | `/chat` | 同步串行，返回 `{reply, favorability}`。不要在新前端代码里用 |
| 语音通话 | WebSocket `/voice/call` | 见 `backend/CLAUDE.md` 的 conversation_manager 一节 |

改 `/chat/stream` 时**必须**同步检查 `/chat`（两份编排逻辑结构一样但分开维护），并更新本文件的 Phase 描述。

### 性能优化已落地的点（不要再"优化"它们）

- **三合一 unified_state_agent**（`funcation/unified_state_agent.py`）：原 `profile_agent` + `relationship_agent` + `state_agent` 合并成 1 次 LLM 调用（temp=0，`response_format=json_object`）。`mc.update_state_unified()` 是入口。**改任意一个旧 agent 之前**先确认 `/chat` 和 `/chat/stream` 走的是新还是旧 —— 当前都走 unified。
- **后台 task 并发**：`/chat/stream` 把 world_event / story / unified_state 放进 `asyncio.create_task(_bg_agents())`，5 秒 `asyncio.wait_for` 超时。
- **recall_agent 后台化（首 token 省 1-2s）**：`/chat/stream` 关键路径用 `recall_agent.peek_cached_scope()` 只查缓存（同步几 ms），未命中时用 `FALLBACK_COLLECTIONS = [profile, relationship, story]` 直接跑 RAG，**不阻塞首 token**；同时 `loop.run_in_executor` fire-and-forget 调 `warm_cache_async()` 把 LLM 结果写进 5 分钟缓存供下一轮使用。代价：首次询问相关话题时召回略宽（多查/少查 1-2 个集合），重复或类似话题在缓存窗口内召回精准。**不要回退到同步调 `detect_memory_scope()`**。
- **Phase 1+2 并发结构（asyncio.gather 分轮）**：`/chat/stream` 按依赖图分 4 轮跑（轮 1: messages|mem|world ‖ 轮 2: world_state|RAG ‖ 轮 3: npc_social ‖ 轮 4: prompt）。**实测收益约 50ms**（IO 本来就快，主要瓶颈被 recall 后台化吃掉了），保留这个结构主要是多用户并发更友好，不是首 token 大头。
- **流式 token 即时下发（不轮询）**：`_stream_producer` 在线程里跑 DeepSeek `stream=True`，通过 `loop.call_soon_threadsafe(token_queue.put_nowait, ...)` 把 token 投递到 `asyncio.Queue`；协程 `await queue.get()` 真正阻塞唤醒。**之前用 `queue.Queue + get_nowait + asyncio.sleep(0.01)` 轮询的写法已废弃** —— Windows 上 sleep 分辨率 15.6ms 会让 token 积压成块。
- **SSE 立即关闭**：`yield {"done": true}` 之后用 `asyncio.create_task(_post_process(full_reply))` 把保存历史 / 记忆提取 / 记录用量 / 等 `bg_task` 全部推到后台，`_stream_generator` 立即 return。前端 `loading` 状态在 `onDone` 那一刻就清掉，不会"token 流完了但 typing 气泡还转 1-5s"。
- **前端 streaming 状态分离 loading**：`chatStore.streaming` 在首 token 到达时翻 true，`Chat.vue` 的 typing 三点气泡 `v-if="loading && !streaming"`，避免和正在被填充的 assistant 占位气泡叠加。
- **响应头禁用代理缓冲**：`StreamingResponse` 带 `X-Accel-Buffering: no` + `Cache-Control: no-cache`，否则 nginx / 部分反向代理会攒齐再发 SSE 块。
- **prompt 瘦身**：规则从 19 条 → 8 条；4 段 attitude 大段文字 → `attitude_short`（"冷淡/普通/友好/亲近"）+ `mood_short` 内联到规则 #2。详见 `funcation/prompt.py:432-498`。
- **角色文件 mtime 缓存**：`prompt.py:_load_character()` 和 `memory_center.py:load_character_by_id()` 都加了 dict + mtime 缓存，文件未变时直接返回内存缓存，避免每次请求重复读磁盘。改角色 JSON 文件后首次请求自动失效（mtime 变了）。

### Two Separate "Memory" Systems (Critical Distinction)

The backend has **two independent memory systems** — confusing these causes bugs:

1. **Structured state** (`data/memories/{characterId}.json`): Single JSON per character holding profile, favorability, long_memory, events, chat_summary, relationship, character_state, story. Managed by `MemoryCenter` class.

2. **Chat history** (`memories/{characterId}_memory.json`): Raw message array `[{role, content}]`. Managed by `memory.py` module (plain functions, no class).

### Backend: `funcation/` Directory

The package name is intentionally `funcation` (not `function`). All imports use this spelling. There's no `__init__.py` — imports use `from funcation import module_name`.

Every `*_agent.py` follows the same pattern: initializes its own OpenAI client pointing at DeepSeek, reads `DEEPSEEK_API_KEY` from env, and calls `deepseek-chat`. Most use `response_format={"type": "json_object"}` or manual `json.loads()` to parse structured output.

### Standalone Script: `backend/search.py`

A separate LangChain + Tavily + ChromaDB agent (not wired into the API). Uses `sentence-transformers/all-MiniLM-L6-v2` for embeddings and persists to `./memory_db`. Has its own chat loop, independent of the FastAPI server. Requires `TAVILY_API_KEY` in `.env`.

### API Key Location

All secrets are in `backend/.env`: `DEEPSEEK_API_KEY` and `TAVILY_API_KEY`. Both root `.gitignore` and `backend/.gitignore` ignore `.env`; `.env.example` at the project root is the template (covers backend secrets + Docker build args like `VITE_API_BASE`).

### Known Issues

- `/chat` uses **layered degradation** — see `backend/CLAUDE.md` for the `_safe` helper detail.
- `backend/api接口文档.md` documents endpoints that no longer exist in actual code — see `api.py` for the real list.
- `MemoryCenter` uses lazy imports to avoid circular imports.
- Frontend API URL is **not hardcoded** — it's configured via `VITE_API_BASE` / `VITE_WS_BASE` (default `http://127.0.0.1:8000`). Docker deploys set `VITE_API_BASE=/api` for nginx reverse proxy.
- `.env` is gitignored; use `.env.example` as template.
- **Legacy agents**: `state_agent.py` 已删除。`profile_agent.py` 仅保留 `generate_caring_message()`（被 `/caring-message` API 使用），`relationship_agent.py` 仅保留 `get_relationship_level()`（被 `update_state_unified()` 使用）。两者的 LLM 调用函数已废弃，不要在新代码中引用。

### 前端移动端适配

`Chat.vue` 在 `<900px` 时隐藏左右侧栏，改为底部 Tab 栏（💬聊天 / 🎭角色 / 💖好感 / 🧠记忆）+ 抽屉面板。切换角色、查看好感度和记忆不需要宽屏。修改移动端布局时同步检查 Tab 栏和抽屉的样式。

### 后台 World Tick (P0)

`funcation/world_tick_scheduler.py` 在 FastAPI lifespan 中启动一个 asyncio 后台循环，定时为活跃用户的当前世界跑 `world_event_agent.tick(force=True)`。**角色现在不聊天时也活着** —— 用户下次上线时通过 proactive 看到"刚才发生了什么"。

关键设计：
- 单一 asyncio task，不引入 APScheduler。沿用项目已有的后台任务模式
- 限流：每个 (user, world) 至少间隔 `WORLD_TICK_MIN_INTERVAL_MIN` 分钟（默认 30）；用 world_state 的 `last_bg_tick_time` 字段记录（独立于 `/chat` 触发的 `last_tick_date`）
- 用户过滤：只处理 `last_chat_time` 在 `WORLD_TICK_ACTIVE_DAYS` 天内的用户（默认 7），避免空跑
- 启动延迟 60s 再开始第一轮，避免和 startup 抢资源
- 优雅停止：lifespan shutdown 时 `_stop_event.set()` + 5s 等待，超时则 cancel

环境变量：
- `RUN_BACKGROUND_TICK=0` 完全禁用（本地开发可关）
- `WORLD_TICK_LOOP_SEC` 主循环间隔（默认 1800 = 30 分钟）
- `WORLD_TICK_MIN_INTERVAL_MIN` 单个 world 最小间隔（默认 30）
- `WORLD_TICK_ACTIVE_DAYS` 活跃用户判定窗口（默认 7）

调用链：`_scheduler_loop` → `_tick_one_user` → `world_event_agent.tick(force=True)` → `process_notifications`（apply_character_impact + link_story + mark_proactive_notice）。每用户独立 try/except，一个失败不影响其他。

### 多剧情系统 (A3)

`funcation/story_agent.py` 已从单剧情升级为多剧情（主线 + 支线）支持。

**数据模型**:
- `memory_data["stories"]` — 剧情列表，每条 Story dict: `id, title, type(main|side), status(active|paused|completed), stage, max_stage, stages[], branch_points[], tags[], started_at, last_advance_date, changed`
- `memory_data["story_history"]` — 已完成剧情的归档列表
- 保留 `memory_data["story"]` 兼容字段（取第一条 active main）
- `MemoryCenter._migrate_story_format()` 懒迁移旧格式 → 新格式

**核心函数**:
- `check_stories(mc, user_id, character, world)` — 主入口，推进 active 剧情 + 归档完成 + 生成新主线
- `advance_story(story, memory_data)` — 推进单条 stage+1，好感度阈值/心情变化触发分支存档
- `trigger_side_story(mc, user_id, character, world, event, notification_type)` — world_event 联动生成支线（≤3 条 active side）
- `sync_stories_to_state(memory_data)` — 将激活主线反映到 character_state（不覆盖 world_event）

**兼容**: `check_story()` 和 `sync_story_to_state()` 保留为 shim，内部委托新函数。

**API 变更**:
- `GET /story` → 返回 `{stories, story_history, story}`（story 为兼容字段）
- `POST /story/advance` — 手动推进指定剧情
- `POST /story/branch` — 手动存档分支点

**前端**: MemoryView 剧情 Tab 显示多线卡片（主线/支线标签 + 进度 + 分支点数量）。

### 角色自我意识 (A4)

让角色"记得自己"——关系如何一路演变、好感升温还是冷却、对社交圈 NPC 有自己的看法。**零新增 LLM 调用**：全部基于已有数据做确定性计算 + prompt 注入，不拖慢首 token。

**数据模型** (`memory_center.py`):
- `memory_data["self_awareness"]` — `{first_chat_date, peak_favorability, peak_fav_date, min_favorability, min_fav_date, milestones[], fav_trail[]}`
- `milestones` — 关系等级变化轨迹 `[{date, from, to}]`（最多 8 条）
- `fav_trail` — 每日好感快照 `[{date, value}]`（最多 10 条，同日覆盖），用于感知升温/冷却
- `_ensure_self_awareness(data)` — 懒补字段（旧记忆文件无此字段；用当前好感作峰值/低谷初值），在 `load_memory()` 中调用，幂等

**更新入口**: `update_state_unified()` 在算完好感/关系后调 `_track_self_awareness(mem, old_level, new_level, favorability)`——记里程碑、刷新峰值/低谷、追加好感快照，随 `save_memory` 落盘。**不新增 LLM 调用**。

**Prompt 渲染** (`prompt.py`):
- `_build_self_awareness_section(self_awareness, favorability, relationship_level)` — 渲染"自我觉察"段：关系演变轨迹（`普通 → 朋友 → 亲近`）+ 升温/冷却感知（对比 fav_trail 首尾，差 ≥8 触发）+ 峰值回落怀念（peak − 当前 ≥15 触发）。无数据返回空串
- 模板插入位置：历史经历之后、规则之前
- 新增规则 #9：鼓励角色回顾关系变化、对 NPC 表达看法

**NPC 看法** (`interaction_agent.py`):
- `_npc_attitude(favorability, intimacy)` — 好感分档生成主观措辞（"很合得来" / "看不太顺眼" 等）
- `build_social_prompt_for_character()` 新增「你对ta们的看法」段：挑出好感最高/最低的 NPC 各一条，让角色能主动谈论

### Electron 桌面挂件 (D3)

D3 MVP 将角色做成 Windows 桌面常驻小窗。**后端不新增接口**，复用现有 `/chat/stream`、`/proactive`、`/character/current`、`/relationship` 等接口。

**前端结构**:
- `front/electron/main.ts` — Electron 主进程：透明、无边框、置顶窗口；开发模式加载 `http://127.0.0.1:5173/#/widget`，生产模式加载 `dist/index.html#/widget`
- `front/electron/preload.ts` — 通过 `contextBridge` 暴露最小 `window.widgetApi`（窗口尺寸、拖拽、隐藏、置顶切换）
- `front/src/views/DesktopWidget.vue` — `/widget` 路由 UI：compact 头像气泡 + expanded 迷你聊天窗
- `front/src/stores/widgetStore.ts` — 挂件模式、主动冒泡开关、置顶偏好（localStorage）
- `front/src/router/index.ts` 使用 hash history，保证 Electron file:// 打包后路由可用

**脚本**（在 `front/`）:
- `npm run electron:dev` — 启动 Vite + Electron 桌面挂件（入口 `dist-electron/main.cjs`）
- `npm run electron:build` — 构建前端和 Electron 主进程
- `npm run electron:pack` — electron-builder 打包 Windows 安装包

**依赖**: `electron`, `electron-builder`, `concurrently`, `wait-on`, `esbuild`（devDependencies）。如本机缺 Node/npm，需先安装 Node 20.19+ 或 22.12+。

### Git & CI/CD
- Single root-level repo (backend/front inner `.git` dirs backed up to `.git.backup`).
- GitHub Actions: `.github/workflows/deploy.yml` builds both images, verifies backend starts, deploys via SSH.
- GitHub Actions CI (`.github/workflows/ci.yml`)：push / PR 触发，跑后端 pytest（DeepSeek/ChromaDB 全 mock）+ 前端 vitest + Playwright e2e（仅 chromium）。type-check 因预存类型债暂设 `continue-on-error`。
- Docker Compose: `docker compose up -d` with nginx (80) proxying `/api/*`→backend, `/voice/*`→backend WS, `/`→frontend SPA.

### Auth System
- **JWT-based auth**: SQLite (SQLAlchemy) user store, PyJWT tokens, bcrypt password hashing.
- **Roles**: admin (default: admin/admin123), user (pending→approved).
- **Permissions**: unauthenticated → login/register only; pending → read-only (browse, no chat/create); approved → full access; admin → full + user approval + quota approval.
- Backend: `funcation/auth.py` (User model + JWT + FastAPI Depends), `api/auth.py` (routes). Read endpoints open, write endpoints require `require_approved`.
- Frontend: `authStore` (Pinia), `AuthModal` (login/register popup), `request.ts` auto-attaches Bearer token. Pending users see disabled inputs / hidden action buttons.
- 3rd-party OAuth fields reserved: `oauth_provider`, `oauth_id` on User model.
- **Character isolation**: Each character has a `created_by` field (user ID). Regular users see only built-in characters + their own; admins see all. Enforced by `_check_character_access()` in `api.py` on `/character/switch`, `/character/avatar`, `/chat`, `/character/current`.
- **Memory isolation**: Per-user memory state is also scoped by user ID — different users chatting with the same character do not share favorability, long_memory, profile, or chat history. See `MemoryCenter` for the keying scheme.
- **Admin quota approval**: Beyond role approval (pending→approved), admins also approve per-user resource quotas (e.g. character creation limits). See `api/auth.py` for the approval endpoints.
