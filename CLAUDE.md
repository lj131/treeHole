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

两个子项目共用**仓库根的一个 git repo**（早期是各自独立的 repo，已合并，
`backend/.git` / `front/.git` 都不存在了）。每个子目录有自己的 `CLAUDE.md`，
深挖某个方向去读对应的那份；本文件覆盖的是**两边单看都看不出来的跨切面**。

**项目状态与推进方向**: `PROJECT_ANALYSIS.md` 是 **2026-07-17 的快照，已过时**（当时还有 P0/P1 技术债，现已全部清偿）。真正在维护中的是 [docs/superpowers/plans/2026-09-18-system-advancement-plan.md](./docs/superpowers/plans/2026-09-18-system-advancement-plan.md) —— 按优先级分 P0-P3，每完成一项会在表里标注；单个功能的执行计划放在同目录 `YYYY-MM-DD-slug.md`。

## 功能索引（2026-10-15）

按"我想改 X"查对应的章节，不用通读全文：

| 想改什么 | 看哪节 |
|---|---|
| 记忆 / 好感度 / 画像 / 剧情 | [记忆真源划分](#记忆真源划分向量库是索引不是存储p0-1-72026-10-14-根治) + `backend/CLAUDE.md` 的 MemoryCenter |
| 主动消息 / 世界 tick | [后台 World Tick](#后台-world-tick-p0) + 多剧情系统 |
| 聊天主流程 / 首 token 延迟 | [Data Flow: Chat Message Lifecycle](#data-flow-chat-message-lifecycle) |
| 3D 模型 / 立绘 | [3D 角色模型](#3d-角色模型-vrm-gltf) |
| 声音 / 音色 | [语音包](#语音包-voice-pack) |
| 桌面挂件 / 托盘 / 开机自启 | [Electron 桌面挂件](#electron-桌面挂件-d3) |
| 梦境日记 | [梦境日记 (D2)](#梦境日记-d2-2026-10-14) |
| NPC 群聊旁观 | [NPC 群聊旁观 (D4)](#npc-群聊旁观-d4-2026-10-15) |
| 磁盘 / 体积 / 数据目录 | [磁盘清理策略](#磁盘清理策略-p2-322026-10-14) |

**踩坑速查**（来自实测，别重复踩）：见文末 [Known Issues](#known-issues)，
重点是**测试会污染真实向量库**和**本机 `http_proxy` 拦 `127.0.0.1`** 这两条。

## Quick Start (Full Stack)

### 本地开发

```bash
# ── venv 在仓库根 treeHole/.venv，**不在 backend/.venv** ──

# 方式一：一键脚本（起后端 + 前端，Ctrl-C 全停）
cd D:/mmmy/treeHole
./scripts/dev.sh                    # Git Bash / WSL

# 方式二：手动（两个终端，**后端务必 cd 进 backend/**）
# Terminal 1 — Backend
cd D:/mmmy/treeHole/backend
../.venv/Scripts/python.exe -m uvicorn api.api:app --reload --port 8000

# Terminal 2 — Frontend
cd front
npm install
npm run dev
```

**跑后端必须在 `backend/` 目录**。`data/` 是**相对 cwd** 的
（`MEMORIES_DIR = "data/memories"`、`data/users.db`、`data/world_state/`…全一样）：
在仓库根起后端 → 整套数据会建到**根目录 `data/`**，和 `backend/data/` **分裂成两份**
（2026-10-15 踩过：用 `--app-dir backend` 从根目录起，根目录多出一份 users.db，
真数据在 `backend/data/` 里，白忙一场）。**不要图省事用 `--app-dir`。**

反过来，`memory_rag.PERSIST_DIR` 是**绝对路径**（`BASE_DIR/data/chroma`），不受 cwd 影响 ——
这一点在测试隔离时很重要（见 `backend/CLAUDE.md` 的测试架构）。

**验证起来了**：
```bash
curl -s --noproxy '*' http://127.0.0.1:8000/health
# → {"status":"ok","rag":{"persist_dir":"D:\\...\\backend\\data\\chroma", ...,"healthy":true}}
```
> 本机有 `http_proxy`，**不加 `--noproxy '*'` 可能拿到 502**（代理拦了 127.0.0.1）。
> 换 `http://localhost:8000` 通常也能通。

### 测试

```bash
# 后端（全 mock DeepSeek / ChromaDB，不需要真实 key）
cd backend
../.venv/Scripts/python.exe -m pytest                 # 全量
../.venv/Scripts/python.exe -m pytest tests/test_api_integration.py
../.venv/Scripts/python.exe -m pytest -k relationship

# 模拟 CI（本机有 voice-clone sidecar 而 CI 没有时用）
cd backend && VOICE_CLONE_VENV=/definitely/no/such/venv ../.venv/Scripts/python.exe -m pytest -q

# 前端
cd front
npm run type-check      # vue-tsc --build
npm run lint:ci         # oxlint + eslint，**不带 --fix**（见 front/CLAUDE.md）
npm run test            # vitest
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

> ⚠️ **本机 `http_proxy` 会拦 `127.0.0.1`**：`curl http://127.0.0.1:5173` 可能返回 **502**，
> 换 `http://localhost:5173` 才通；node `fetch` 同样被拦。
> 本机自测 curl 一律加 `--noproxy '*'`。

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

### 记忆真源划分：向量库是**索引**，不是存储（P0 §1-7，2026-10-14 根治）

**这是本项目最容易踩坑的地方，动记忆相关代码前必读。**

| 字段 | 真源 | 向量库角色 |
|---|---|---|
| `profile` / `story` / `relationship` | `data/memories/{uid}/{char}.json` | 派生索引（`_sync_*_to_rag`） |
| `long_memory` / `events` / `chat_summary` | **`data/memories/{uid}/{char}.rag.json`** | 派生索引（`MemoryCenter.add_*`） |

**向量库随时可以删掉重建**（`POST /admin/rag/rebuild`）。
2026-10-14 之前后三个字段**只存在于向量库**，于是向量库一被隔离就等于**静默丢数据**
（真实发生过 6 次误隔离）。

- **这是把历史上一处反向迁移改回来**：`_migrate_to_chroma()` 当年刻意
  `data.pop("long_memory")` 把字段搬进向量库。现在是 `_migrate_from_chroma()`（幂等）。
- **为什么另起 `.rag.json` 不塞进主 JSON**：主 JSON 的 `save_memory()` 是「用调用方快照
  整体覆盖」，而聊天流程是 `load → add_chat_summary(×2) → save_memory(旧快照)` ——
  `add_*` 和 `save_memory` 会争同一个文件。另起文件 = 两个 writer 各写各的，零冲突。
- **改这块的铁律**：
  1. 新增"只靠向量库"的字段 = 重新引入丢数据风险 → **先落 JSON，再建索引**
  2. 索引写失败**不能**让数据写入失败（`_index_to_rag` 是 best-effort，只记日志）
  3. 反向迁移**读不到向量库时什么都不做** —— 绝不能把"读不到"当成"没有"而写出空真源

### 请求级记忆缓存 (§3.4，2026-10-15)

一次 `/chat` 会把同一份记忆文件 `load → 改 → save` **8-10 次**。
`funcation/memory_center.py:memory_scope()`（ContextVar）让请求内所有记忆读写
**共享同一个 dict 对象**：

- **性能**：8 次读盘 → 1 次
- **正确性（更重要）**：请求内所有写者拿到同一个对象，
  "A 用旧快照覆盖 B 刚写的字段"这类 lost update 被**结构性消灭**

三个关键约束（改动前必读）：
1. **写透不延迟**：`save_memory` 仍每次落盘，进程中途挂掉只丢正在写的那一笔
2. **`/chat`（同步端点）直接启用**；`/chat/stream`（async + `run_in_executor`）
   的 `in_executor` **必须**用 `contextvars.copy_context().run` 包一层 ——
   `run_in_executor` **不继承** ContextVar，否则"事件循环走缓存、线程池读盘"
   会互相覆盖，**比不用缓存更糟**
3. `load_memory` 缓存命中也要**重新同步三个检索型字段**（`add_*` 独立写它们）

### 磁盘清理策略 (P2 §3.2，2026-10-14)

`funcation/disk_cleanup.py`，进程启动时由 lifespan 在**后台线程**跑一次（不阻塞启动）：
- 删掉**超过 30 天保留期**的历史隔离目录（`chroma_corrupt_*` / `chroma_new`）
- 截断只追加的 `data/tmp/clone/worker.log`（超 1MB 只留尾部 200KB）
- 手动清理：`backend/scripts/cleanup_disk.py`（`--dry-run` / `--days`）

**安全约束**：前缀白名单（绝不做模糊匹配）+ 显式排除活跃 `chroma`（双保险）、
保留期、best-effort、有 dry-run。**长驻追加的日志只能原地 `os.truncate`，
不能 tmp + replace**（POSIX 下写方 fd 会指向已 unlink 的旧 inode，日志写进黑洞）。

### 梦境日记 (D2, 2026-10-14)

角色基于**用户的聊天摘要**（`chat_summary`）生成一场"梦"，次日由主动消息投递。
- `funcation/dream_agent.py` — `ensure_dream_pending()`（三条闸门：不叠加 / 一天一场 /
  有新素材才生成）+ `mark_delivered()`
- 接在 `world_tick_scheduler._tick_one_user` 里跑（world tick 之后）
- 数据在 `memory["dream"]`（待投递）+ `memory["dreams"]`（历史，最多 20 条）
- `/memory/full` 带出 `dreams` / `dream`；前端 `MemoryView` 的「🌙 梦境日记」卡片
- **`detect_trigger` 对 dream 分支只读不清 flag**，由引擎在 `generate_message`
  **成功后**才标记已投递 —— 否则被冷却拦下时梦会凭空消失

### NPC 群聊旁观 (D4, 2026-10-15)

用户旁观 NPC 之间的群聊。**后端 100% 已有**，只补了前端出口：
- `interaction_agent.apply_interaction_result` 早就在往 `world_state` 写
  `npc_registry.recent_interactions`（含 `dialogues`）
- `GET /world/interactions` / `POST /world/interaction/simulate` 早就存在
- 前端 `views/NpcGroupChatView.vue` + 路由 `/npc` + 导航「👥 群聊旁观」：
  对话气泡（彩色头像：同名字恒同色）、关系三条数值条、八卦、世界影响
- 社交数据已从 `AboutView`（它是"系统设置"页）搬走，只留入口卡片

### Two Separate "Memory" Systems (Critical Distinction)

The backend has **two independent memory systems** — confusing these causes bugs:

1. **Structured state** (`data/memories/{user_id}/{characterId}.json`): Single JSON per (user, character) holding profile, favorability, long_memory, events, chat_summary, relationship, character_state, story, self_awareness. Managed by `MemoryCenter` class.

2. **Chat history** (`data/memories/{characterId}_memory.json`): Raw message array `[{role, content}]`. Managed by `memory.py` module (plain functions, no class).

### Backend: `funcation/` Directory

The package name is intentionally `funcation` (not `function`). All imports use this spelling. There's no `__init__.py` — imports use `from funcation import module_name`.

Every `*_agent.py` follows the same pattern: initializes its own OpenAI client pointing at DeepSeek, reads `DEEPSEEK_API_KEY` from env, and calls `deepseek-chat`. Most use `response_format={"type": "json_object"}` or manual `json.loads()` to parse structured output.

### Standalone Script: `backend/search.py`

A separate LangChain + Tavily + ChromaDB agent (not wired into the API). Uses `sentence-transformers/all-MiniLM-L6-v2` for embeddings and persists to `./memory_db`. Has its own chat loop, independent of the FastAPI server. Requires `TAVILY_API_KEY` in `.env`.

### API Key Location

All secrets are in `backend/.env`: `DEEPSEEK_API_KEY` and `TAVILY_API_KEY`. Both root `.gitignore` and `backend/.gitignore` ignore `.env`; `.env.example` at the project root is the template (covers backend secrets + Docker build args like `VITE_API_BASE`).

### Known Issues

- `/chat` uses **layered degradation** — see `backend/CLAUDE.md` for the `_safe` helper detail.
- `MemoryCenter` uses lazy imports to avoid circular imports.
- Frontend API URL is **not hardcoded** — it's configured via `VITE_API_BASE` / `VITE_WS_BASE` (default `http://127.0.0.1:8000`). Docker deploys set `VITE_API_BASE=/api` for nginx reverse proxy.
- `.env` is gitignored; use `.env.example` as template.
- **Legacy agents**: `state_agent.py` 已删除。`profile_agent.py` 仅保留 `generate_caring_message()`（被 `/caring-message` API 使用），`relationship_agent.py` 仅保留 `get_relationship_level()`（被 `update_state_unified()` 使用）。两者的 LLM 调用函数已废弃，不要在新代码中引用。
- **测试会污染真实向量库**（踩过 **4 次**）：`memory_rag.PERSIST_DIR` 是**绝对路径**，不受 `monkeypatch.chdir` 隔离影响。`tests/conftest.py` 已有 `_isolate_chroma` autouse 兜底；新测试文件若需要真实 chromadb，自己再 patch 一次即可（函数级 fixture 会覆盖 autouse）。**注意 `_migrate_from_chroma` 会从向量库反向读**，所以 patch 索引路径不只是"写隔离"，也是"读隔离"。
- **环境层的坑**：本环境 CLI shim 会拦 Python 的 `os.remove`（删大文件触发批量删除保护，抛 `SystemExit`，`except Exception` 接不住）→ 清理逻辑一律 best-effort（`except (Exception, SystemExit)`）。`rm "$TEMP/..."` 会报 `embedded drive prefix is not allowed` → 用 `cd` 到具体目录或用 msys 路径。Git Bash 的 `/tmp` 与 Windows Python 的临时目录**不是同一个地方**，备份别放 `/tmp`。
- **`data/` 是相对 cwd 的**：在仓库根起后端会把整套数据建到根目录，跟 `backend/data/` 分裂成两份。**永远 `cd backend` 再起**；根 `.gitignore` 已加 `/data/users.db` 等兜底。
- **两个 linter 有偶发误报**：`npm run lint:ci` 的 oxlint + eslint 并行跑，偶尔报一批错，单文件/整轮重跑就 0 错。看到"突然一片红"先复跑再查。

### 前端导航与页面

底部导航：首页 / 角色聊天 / 角色 / 记忆 / **群聊旁观** / 剧情 / 设置。
`<900px` 时 Chat.vue 隐藏左右侧栏，改为底部 Tab（💬聊天 / 🎭角色 / 💖好感 / 🧠记忆）+ 抽屉面板。
`AdminView`（`/admin`）仅管理员可见，由路由守卫拦。`/widget` 是 Electron 挂件专用全屏页。
`/poc-3d` 是独立的 3D 验证页。修改导航时同步检查 `App.vue` 的 `RouterLink` 与 `router/index.ts` 的 `meta.title`。

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
- `front/electron/main.ts` — Electron 主进程：透明、无边框、置顶窗口；开发模式加载 `http://127.0.0.1:5173/#/widget`，生产模式加载 `dist/index.html#/widget`。源码是 `.ts`，靠 `esbuild` 打成 `dist-electron/main.cjs`
- `front/electron/preload.ts` — 通过 `contextBridge` 暴露 `window.widgetApi`
- `front/src/views/DesktopWidget.vue` — `/widget` 路由 UI：compact 头像气泡 + expanded 迷你聊天窗
- `front/src/stores/widgetStore.ts` — 挂件模式、主动冒泡开关、置顶/自启偏好
- `front/src/router/index.ts` 使用 hash history，保证 Electron file:// 打包后路由可用

**脚本**（在 `front/`）:
- `npm run electron:dev` — 启动 Vite + Electron 桌面挂件
- `npm run electron:build` — 构建前端和 Electron 主进程
- `npm run electron:pack` — electron-builder 打包 Windows 安装包

**⚠️ `window.widgetApi` 的类型必须在 `front/src/types/api.ts`**（一个确实被全项目 import 的 module）。
历史上放在 `types/electron.d.ts` 里，**没有任何文件 import 它**，tsc 不求值其中
的 `declare global` → `window.widgetApi` 报 "Property does not exist on type 'Window'"，
而且只在真正用到该字段的文件里报错，极难定位（2026-10-15 修掉）。

**已实现的能力**（2026-10-15 D3 增强）：
- **系统托盘**：`Tray` + 菜单（显示/隐藏、置顶勾选态、退出）；左键点击切换显隐
- **点窗口 × 不退出**，只是隐藏（`quitting` 标志 + `close` 事件 `preventDefault`）——
  否则"托盘"没有意义
- **开机自启**：`app.setLoginItemSettings({ openAtLogin })`（**不引 `auto-launch` 包**）
  - IPC resolve 的是**系统里的实际结果**（被组策略否决时上层能看到事实）
  - store `syncAutoLaunch()` 以系统状态为权威；localStorage 只是"上次的期望"
- **3D 立绘与聊天页同源**：两边都用 `character?.model3d`。
  以前挂件有 `hasCustomModel()` 闸门，导致用内置 demo 模型时
  **聊天页是 3D、挂件里是静态头像**（2026-10-15 修）。省资源靠低配渲染
  （`enableControls:false` + `enableBodyFollow:false`），不是"不渲染"

**依赖**: `electron`, `electron-builder`, `concurrently`, `wait-on`, `esbuild`（devDependencies）。如本机缺 Node/npm，需先安装 Node 20.19+ 或 22.12+。

### 3D 角色模型 (VRM / glTF)

角色可绑定 3D 模型，聊天页 / 语音通话 / 桌面挂件统一走 `CharacterPortrait3D` 渲染；未绑定、WebGL 不可用或加载失败时**自动降级为 2D 头像**（永不白屏）。

**数据流**：

```
前端 CharactersView 弹窗上传 .vrm/.glb
  → POST /character/model（multipart）→ data/models/{char_id}_{hex}.vrm
  → 角色 JSON 写入 model3d{url, format, scale, rotation_y, camera_*, default_expression, auto_rotate}
  → GET /character/current、/characters（摘要）把 model3d 带给前端
  → utils/avatar3d.ts:resolveModelRender() 归一化成渲染参数
  → CharacterPortrait3D → VRMAvatar（Three.js + @pixiv/three-vrm）
```

- **后端**：`funcation/model3d.py`（纯函数：白名单 / 大小限制 / clamp / 摘要）+ `api/api.py` 4 个路由；静态托管 `/models`（同 `/avatars`）。详见 `backend/CLAUDE.md`。
- **前端**：`utils/avatar3d.ts` + `components/3d/*` + `CharactersView` 配置弹窗。详见 `front/CLAUDE.md`。
- **降级顺序**：`model3d.url`（`enabled!==false`）→ 旧字段 `vrm_model` → 内置 demo `/models/rpm_demo.vrm`；WebGL 缺失或模型加载失败 → 静态头像。
- **上限**：单文件默认 64MB（`MODEL_MAX_MB` 可覆盖）。
- **3D 场景背景**：非透明模式用 `components/3d/sceneBackground.ts` 程序化生成的柔和夜色（低饱和渐变 + 极淡星点 + 细噪点防 banding）；透明模式交给页面。HDRI **只喂 `scene.environment`**，不当背景 —— 写实天空照配二次元人物很出戏。
- **无框浮出**：`CharacterPortrait3D` 的 `popOut`（默认 `true`）会去掉深色底/圆角裁切，把画布放大到槽位的 1.34 倍并底部锚定，让人物探出卡片顶边。**只在容器有足够上边距时开** —— 当前开在聊天页左栏角色卡（人物探出卡片）和语音通话弹窗（面板内大立绘，受拖动条占位限制不探出）；移动端抽屉 / 桌面挂件 / 角色页预览都显式传 `:pop-out="false"`（容器太矮或会裁切）。尺寸参数集中在 `utils/avatar3d.ts` 的 `POP_OUT_SCALE` / `POP_OUT_FRAMING_SCALE` / `POP_OUT_BOTTOM_OFFSET`，有单测钉住"头顶不能被窗口裁掉"这条约束；改槽位尺寸或卡片内边距时必须重新核对。

### 语音包 (Voice Pack)

**每个角色可以配自己的声音**，语音包由**管理员**在 `/settings` 的「🔊 语音包」区块统一维护（所有 `/voice/*` 接口都是 `require_admin` —— 语音包是全局资源，改动会影响所有角色和所有用户）。

- **包里同时装两样东西**：音色参数（`engine` / `voice_name` / 语速 / 音调 / 音量）+ 参考音频。现在只有 `edge` 引擎（`edge-tts` 云端、音色是固定名字）真正能合成；参考音频先存下来，**接克隆引擎时只要新增一个 engine 值 + 一个适配器**，存储/接口/前端都不用动。
- **编辑已有语音包必须保住参考音频**：`PATCH` 走的是局部更新，`reference_audio` 由上传接口单独管理（更新时只保留旧值）。踩过的坑：把 `reference_text` 也按这个规则写成"只读旧值"，结果创建时永远为空、更新时改不动 —— 文本字段要读**入参**，音频字段才只保留旧值。
- **引擎可插拔但不静默降级**：选了 `clone` 而引擎没部署 → 明确报错（试听返 503 带原因），不会偷偷用别的音色顶替。UI 会按 `engine_available` 给包打「引擎未部署」标记。
- **音色解析链**：角色绑定的语音包 → 旧的按角色写死映射 → 环境变量兜底；返回带 `source` 说明"这个声音是哪来的"。
- **存储全局单份**（`data/voice_packs.json` + `data/voice_bindings.json` + `data/voice_refs/`），所以运行时合成**不需要 user_id**，语音通话链路一行没改。改包必须清 TTS 缓存。
- **两个实测坑**：edge-tts 云端会偶发失败（同一段文本连打 4 次可能挂 2 次）→ 已加重试；`pitch` 对部分中文音色**无效**（+0/+30/-30Hz 输出字节数完全相同）→ 界面上如实说明。

详见 `backend/CLAUDE.md`（模块与接口）与 `front/CLAUDE.md`（设置页与 API 客户端）。

### Git & CI/CD

- **单一根级 repo**（`treeHole/.git`）。早期 `backend/`、`front/` 各自有独立 repo，已合并，现在**没有** `backend/.git` / `front/.git`。
- GitHub Actions CI (`.github/workflows/ci.yml`)：push / PR 触发，跑后端 pytest（DeepSeek/ChromaDB 全 mock）+ 前端 vitest + Playwright e2e（仅 chromium，**没有后端进程** → 新 E2E 用例必须能在无后端时优雅 skip）。
- GitHub Actions deploy (`.github/workflows/deploy.yml`)：构建两个镜像，验证后端起得来，SSH 部署。
- Docker Compose: `docker compose up -d`，nginx (80) 代理 `/api/*`→后端，`/voice/*`→后端 WS，`/`→前端 SPA。
- **推之前先在两种环境跑一遍**：本机 + `VOICE_CLONE_VENV=<不存在路径>` 模拟 CI（本机有 voice-clone sidecar，CI 没有，只在一种环境下绿过不代表 CI 也绿）。

### Auth System
- **JWT-based auth**: SQLite (SQLAlchemy) user store, PyJWT tokens, bcrypt password hashing.
- Roles: admin (default: admin/admin123), user (pending→approved).
- Permissions: unauthenticated → login/register only; pending → read-only (browse, no chat/create); approved → full access; admin → full + user approval + quota approval.
- Backend: `funcation/auth.py` (User model + JWT + FastAPI Depends), `api/auth.py` (routes). Read endpoints open, write endpoints require `require_approved`.
- Frontend: `authStore` (Pinia), `AuthModal` (login/register popup), `request.ts` auto-attaches Bearer token. Pending users see disabled inputs / hidden action buttons.
- 3rd-party OAuth fields reserved: `oauth_provider`, `oauth_id` on User model.
- **Character isolation**: Each character has a `created_by` field (user ID). Regular users see only built-in characters + their own; admins see all. Enforced by `_check_character_access()` in `api.py` on `/character/switch`, `/character/avatar`, `/chat`, `/character/current`.
- **Memory isolation**: Per-user memory state is also scoped by user ID — different users chatting with the same character do not share favorability, long_memory, profile, or chat history. See `MemoryCenter` for the keying scheme.
- **Admin quota approval**: Beyond role approval (pending→approved), admins also approve per-user resource quotas (e.g. character creation limits). See `api/auth.py` for the approval endpoints.

### World Modes (public/private)
- `public` — 全员共享，事件同步，所有用户看到相同的世界状态
- `private` — 用户私有副本，独立演化
- 切换：`POST /world/switch` 传入 `mode: "public" | "private"`，数据隔离在 `data/world_state/{user_id}/{world_id}.json`
- `world_tick_scheduler` 对 private world 同样生效，每用户独立 tick