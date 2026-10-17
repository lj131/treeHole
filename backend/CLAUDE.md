# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Run Commands

```bash
# Start the API server (from backend/ directory)
uvicorn api.api:app --reload --host 0.0.0.0 --port 8000

# Quick syntax check on all source files
python -c "
import py_compile
for f in ['api/api.py', 'api/websocket.py', 'funcation/memory_center.py',
          'funcation/prompt.py', 'funcation/memory_agent.py', 'funcation/profile_agent.py',
          'funcation/relationship_agent.py', 'funcation/state_agent.py',
          'funcation/event_agent.py', 'funcation/story_agent.py', 'funcation/memory.py',
          'funcation/utils.py', 'funcation/recall_agent.py', 'funcation/memory_rag.py',
          'funcation/embedding_manager.py', 'funcation/world_event_agent.py',
          'funcation/interaction_agent.py', 'funcation/query_classifier.py',
          'funcation/webrtc_agent.py', 'funcation/voice_service.py',
          'funcation/voice_pack.py', 'funcation/voice_store.py',
          'funcation/system_config.py', 'funcation/edge_tts_compat.py',
          'funcation/voice_clone.py', 'funcation/disk_cleanup.py', 'funcation/dream_agent.py', 'funcation/digest.py', 'funcation/tension.py', 'funcation/group_chat.py', 'funcation/circadian.py', 'funcation/incoming_call.py',
          'backend/vendor/OpenVoice/', 'backend/vendor/MeloTTS/',
          'funcation/conversation_manager.py', 'funcation/character_agent.py',
          'funcation/proactive/proactive_engine.py', 'funcation/proactive/proactive_trigger.py',
          'funcation/proactive/proactive_decision.py', 'funcation/proactive/proactive_message_agent.py',
          'funcation/proactive/proactive_cooldown.py',
          'funcation/memory_center.py']:
    py_compile.compile(f, doraise=True)print('OK')
"

# 运行测试套件（agent 单测 + API 集成测试；DeepSeek/ChromaDB 全 mock，无需真实 key）
# 首次需装测试依赖：pip install -r requirements.txt -r requirements-dev.txt
pytest                       # 全量
pytest tests/test_api_integration.py   # 仅集成测试
pytest -k relationship        # 按名筛选
```

> **磁盘清理**（`funcation/disk_cleanup.py`）：进程启动时会自动跑一次 —— 删掉**超过 30 天**
> 的历史隔离目录、截断只追加的 `data/tmp/clone/worker.log`。想立刻清：
> ```bash
> python scripts/cleanup_disk.py --dry-run   # 先看会删什么
> python scripts/cleanup_disk.py --days 0    # 全清
> ```
> **安全约束**（改之前先读模块 docstring）：只按前缀白名单删、**绝不碰活跃的 `data/chroma`**、
> 按保留期、best-effort、有 dry-run。

### 测试架构 (C5)

- 测试在 `tests/`，入口 `pytest.ini`（`testpaths = tests`）。**400+ 测试，约 55s 跑完**（爬升中；写新功能时按下面的规矩补测试）

> ⚠️ **本机全绿 ≠ CI 会绿：先做「CI 对等验证」。**
> 本机装了克隆引擎的 sidecar venv（`.venv-clone`），**CI 上没有**。
> 任何依赖它的断言在本机会过、到 CI 必红（踩过一次，见下）。
> 推之前跑一遍：
> ```bash
> # 模拟 CI：把 sidecar 指到不存在的路径
> VOICE_CLONE_VENV="/definitely/no/such/venv" pytest -q
> # 再跑一遍真实环境
> pytest -q
> ```
> **写这类测试的铁律**：用**确定存在**的路径（`sys.executable`）去断言"可用"，
> 用确定不存在的路径去断言"不可用"。**绝不要"恢复环境原值"来断言** ——
> CI 上那个"原值"本身就是不存在的路径。
- `tests/conftest.py` 是关键：在**模块导入前**注入假 `DEEPSEEK_API_KEY`、把 `DATABASE_URL` 指向临时 sqlite、`os.chdir` 到会话临时目录（隔离 `funcation.auth._migrate_legacy_to_admin` 的相对路径副作用，避免动到真实 `data/`）、把 `embedding_manager.preload` patch 成 no-op。
- **fake DeepSeek**（`FakeDeepSeek`）：替换所有 agent 模块 + `api.api` 的 `client.chat.completions.create`，按 prompt 关键字路由返回 JSON / 纯文本。测试可改 `fake.handler` 自定义。
- **禁用 RAG**：`disable_rag` fixture 把 `memory_rag` 的读写全 mock 成空/no-op，`recall_agent.detect_memory_scope` 返回 `[]`，绕开 ChromaDB / fastembed。
- **数据隔离**：`tmp_data_dir`（function 级）每测试 chdir 到独立 tmp + 拷内置角色/世界（CI 里 `backend/data` 被 gitignore，源文件缺失时写最小桩兜底）。
- **⚠️ 向量库隔离（踩过 4 次）**：`memory_rag.PERSIST_DIR` 是**绝对路径**（`BASE_DIR/data/chroma`），
  不受 `monkeypatch.chdir` 影响。`_isolate_chroma`（**autouse**）已把所有测试默认指向 tmp；
  新测试文件若需要真实 chromadb，自己再 patch 一次即可（函数级 fixture 会覆盖 autouse）。
  **新增任何会写向量库的公开函数，都要加进 `disable_rag` 的 mock 列表**
  （漏一个就往真实开发库写）。**`_migrate_from_chroma` 会从向量库反向读**——
  所以 patch 索引路径不只是"写隔离"，也是"读隔离"。
- **作用域**：`client` / `fake_deepseek` / `disable_rag` / `admin_token` 是 session 级（整会话一个 TestClient lifespan，避免反复 start/stop lifespan 时 TTS 队列任务残留卡死）；`tmp_data_dir` / `approved_user` 是 function 级。
- 覆盖：纯逻辑单测（query_classifier / relationship_level / memory_defaults / story_migration / self_awareness_tracking / prompt_sections / utils / **model3d**）+ API 集成（health / auth 注册登录审批 / 角色切换 / chat mock LLM / 角色访问隔离逻辑 / **3D 模型上传·配置·删除**）。
- **3D 模型测试**：`tests/test_model3d.py`（纯函数：格式判定 / 大小限制 / 文件名净化 / clamp）+ `tests/test_model3d_api.py`（上传落盘与内容校验、非法扩展名不留残渣、超限拒绝、重复上传清旧文件、配置 clamp 与局部更新、删除清理、外链不误删、权限 403）。注意 `tmp_data_dir` 的 cwd 隔离：模型落盘路径是相对的 `data/models`，断言走 `Path("data/models")`。

#### 经理级要求（2026-10-14 起立，写测试前读）

1. **修 bug 必须带回归测试，且要验证"测试能失败"** —— 把修复临时退回旧行为，确认断言真的红。
   不能失败的测试不是测试。
2. **在旧代码上加功能前，先确认它依赖的判定还在工作**。
   实例：主动消息的 `today_count >= 5` 从来不按天清零（实际含义是"一辈子最多 5 条"），
   第 6 条起静默且不报错 —— 梦境日记功能就曾建在这个坏计数器上。
   见 `tests/test_dream.py` 的"回归测试"小节。
3. **新增会写共享状态的公开函数**，先问三个问题：
   谁会并发调？失败要不要影响主流程？删/改之前要不要 dry-run？
4. **dry-run 必须一路透传到底** —— 漏一层就名不副实（`run_startup_cleanup` 漏传给
   `truncate_worker_log`，导致 dry-run 下日志被真实截断）。

## Architecture

This is a **character-based AI chat system** (AI companion simulator). A FastAPI server receives chat messages, assembles a rich system prompt from multiple data sources, calls DeepSeek, and returns the AI character's reply. It also supports **real-time voice calls** via WebRTC + WebSocket, a **proactive greeting** system, and a **world event** system with NPC interactions.

### Core Data Flow (POST /chat)

```
POST /chat
  → MemoryCenter.load_current_character(user_id)     # data/characters/{id}.json
  → memory.load_memory(char_id)                      # memories/{char_id}_memory.json (chat history)
  → MemoryCenter.load_memory(user_id, char_id)       # data/memories/{user_id}/{char_id}.json (all dynamic state)
  → MemoryCenter.load_current_world(user_id)         # data/worlds/{id}.json
  → world_event_agent.tick()                         # Advance world events, auto-generate if needed
  → story_agent.check_stories()                      # Generate/advance multi-stage story (DeepSeek)
  → interaction_agent.build_social_prompt_for_character()  # Build NPC social context for prompt
  → recall_agent.detect_memory_scope()               # Determine which RAG collections to search (DEPRECATED: /chat/stream 用 peek_cached_scope)
  → memory_rag.retrieve_memories()                   # Semantic search across ChromaDB collections
  → prompt.build_system_prompt()                     # Assemble full system prompt (~10 data sources + RAG results)
  → mc.update_state_unified()                        # AI extracts profile + favorability + state (一次 LLM 调用)
  → _sync_profile_to_rag()                           # Sync profile to ChromaDB
  → _sync_relationship_to_rag()                      # Sync relationship to ChromaDB
  → DeepSeek API (deepseek-chat, temp=0.9)           # Generate reply
  → memory_agent.extract_memory()                    # AI decides add/update/ignore long-term memory
  → mc.add_chat_summary()                            # Append to chat summary
  → memory.save_memory()                             # Save chat history to memories/{char_id}_memory.json
  → Return {reply, favorability}
```

### Key Concept: Two "Memory" Systems

There are **two separate memory concepts** — don't confuse them:

| System | Location | Content | Manager |
|--------|----------|---------|---------|
| **Structured state** | `data/memories/{user_id}/{character_id}.json` | profile, favorability, long_memory, events, chat_summary, relationship, character_state, story, self_awareness, seen_world_event_ids, last_chat_time — all in one JSON | `MemoryCenter` class |
| **Chat history** | `memories/{character_id}_memory.json` | Raw message array `[{role, content}, ...]` | `memory.py` module |

### Third Memory System: RAG Vector Store

`funcation/memory_rag.py` maintains a **ChromaDB** vector database at `data/chroma/` with 6 independent collections per (user, character):

| Collection | Content | Synced by |
|-----------|---------|-----------|
| `u{user_id}_{char_id}_profile` | User profile fields (name, city, job, mood) | `_sync_profile_to_rag()` on each /chat |
| `u{user_id}_{char_id}_long_memory` | Long-term memory facts | `memory_agent` extraction |
| `u{user_id}_{char_id}_story` | Story overview + individual stages | `_sync_story_to_rag()` on each /chat |
| `u{user_id}_{char_id}_events` | World/character events | Event creation/update |
| `u{user_id}_{char_id}_relationship` | Relationship level + favorability + reason | `_sync_relationship_to_rag()` on each /chat |
| `u{user_id}_{char_id}_chat_summary` | Chat summary entries | Chat summary updates |

Embeddings use **FastEmbed** (BGE-small-zh-v1.5, local ONNX, free) by default. Provider is configurable via `EMBEDDING_PROVIDER` env var. The `embedding_manager.py` module lazy-loads a singleton embedding function.

RAG retrieval flow: `recall_agent.detect_memory_scope()` (DeepSeek) determines which collections to query → `memory_rag.retrieve_memories()` performs semantic search → results are injected into the system prompt.

**流式优化**: `/chat/stream` 使用 `recall_agent.peek_cached_scope()` 先查缓存，未命中时后台 fire-and-forget 调用 `detect_memory_scope()` 写缓存，本次用 `FALLBACK_COLLECTIONS = [profile, relationship, story]`。避免阻塞首 token。

#### ⚠️ 真源划分：向量库是**索引**，不是存储（2026-10-14 修）

| 字段 | 真源 | 向量库角色 |
|---|---|---|
| `profile` / `story` / `relationship` | `data/memories/{uid}/{char}.json` | 派生索引（`_sync_*_to_rag`） |
| `long_memory` / `events` / `chat_summary` | **`data/memories/{uid}/{char}.rag.json`** | 派生索引（`MemoryCenter.add_*`） |

**向量库随时可以删掉重建**（`POST /admin/rag/rebuild`）。
在那之前，`long_memory`/`events`/`chat_summary` **只存在于向量库**，
于是向量库一被隔离就等于**静默丢数据**（真实发生过 6 次误隔离）。
`MemoryCenter._migrate_from_chroma()` 会把老数据从向量库捞回 `.rag.json`（幂等）。

**为什么这三个字段另起 `.rag.json` 而不塞进主 JSON**：主 JSON 的 `save_memory()`
是「用调用方手上的快照整体覆盖」的语义，而聊天主流程是
`load_memory → add_chat_summary(×2) → save_memory(早先加载的旧快照)` ——
`add_*` 和 `save_memory` 会争同一个文件。另起文件 = 两个 writer 各写各的，零冲突。

**改这块的铁律**：
- 新增"只靠向量库"的字段 = 重新引入丢数据的风险。**先落 JSON，再建索引**。
- 索引写失败**不能**让数据写入失败（`_index_to_rag` 是 best-effort，只记日志）。
- `_migrate_from_chroma` 读不到向量库时**什么都不做** ——
  绝不能把"读不到"当成"没有"而写出一个空真源。


### MemoryCenter — The Central Hub

`funcation/memory_center.py` is the single entry point for ALL dynamic per-character data. The `MemoryCenter` class manages:

- **Profile** (`profile`): User info extracted by AI — name, city, job, mood, recent_topics
- **Favorability** (`favorability`): 0–100 score, updated by `update_state_unified()` (AI-analyzed delta)
- **Relationship** (`relationship`): level (陌生/普通/朋友/亲近/暧昧) + last_reason, auto-calculated from favorability thresholds
- **Long memory** (`long_memory`): List of facts about the user, extracted by `memory_agent`
- **Events** (`events`): Timestamped life events, auto-generated when relationship level changes
- **Character state** (`character_state`): mood, energy, current_event — managed by `update_state_unified()`
- **Stories** (`stories`): Multi-stage narrative list (主线 + 支线), 见 A3 多剧情系统
- **Story history** (`story_history`): 已完成剧情归档
- **Chat summary** (`chat_summary`): Running summary of conversation turns
- **Self-awareness** (`self_awareness`): 关系演变轨迹、好感峰值/低谷、里程碑，见 A4 角色自我意识
- **Seen world events** (`seen_world_event_ids`): 该角色已感知的世界事件 id 列表（公共世界去重）
- **Proactive message cache** (`proactive_message`, `caring_message`): Cached greeting messages
- **Last chat time** (`last_chat_time`): 用户最近聊天时间 ISO8601 字符串（供 world_tick_scheduler 活跃判定）
- **Character/world selection**: Reads `data/current_character_{user_id}.json` and `data/current_world_{user_id}.json`

#### ⚠️ 真源在哪个文件（动记忆前必读）

| 字段 | 真源文件 |
|---|---|
| profile / story / relationship / character_state / favorability / dream / dreams | `.json`（由 `save_memory` 写） |
| **long_memory / events / chat_summary** | **`.rag.json`**（由 `add_*` / `update_*` 写） |

- `.rag.json` 是**独立文件**，不塞进主 JSON —— 因为 `save_memory()` 是"用调用方快照
  整体覆盖"，而聊天流程是 `load → add_chat_summary(×2) → save_memory(旧快照)`，
  两个 writer 会争同一个文件。
- **向量库只是 `.rag.json` 的派生索引**，可随时删掉重建
  （`POST /admin/rag/rebuild` → `memory_rag.rebuild_collection_from_items()`）。
  2026-10-14 之前这三个字段只存在向量库，隔离一次就等于静默丢数据。
- `_migrate_from_chroma()` 把老数据从向量库捞回 `.rag.json`（幂等）。
  **读不到向量库时什么都不做** —— 绝不能把"读不到"当成"没有"而写出空真源。

#### 请求级记忆缓存 `memory_scope()`

一次 `/chat` 会把同一份记忆文件 load→改→save **8-10 次**。
`memory_scope()`（ContextVar）让请求内所有读写**共享同一个 dict 对象**：

```python
from funcation.memory_center import memory_scope, with_memory_scope

@app.post("/chat")
@with_memory_scope
def chat(...):   # 同步端点：整段在同一个线程，ContextVar 全程可见
    ...
```

三条约束：
1. **写透不延迟**（`save_memory` 仍每次落盘）
2. `run_in_executor` **不继承 ContextVar** → `/chat/stream` 的 `in_executor`
   必须 `loop.run_in_executor(None, contextvars.copy_context().run, fn)`，
   否则"循环走缓存、线程读盘"互相覆盖，**比不用缓存更糟**
3. `load_memory` 缓存命中也要**重新同步三个检索型字段**（`add_*` 独立写它们）

### 梦境日记 (D2) — `funcation/dream_agent.py`

基于 `chat_summary` 生成一场"梦"，次日由主动消息投递给用户。

- `ensure_dream_pending(mc, user_id, char_id, character)` — 三条闸门：
  ① 已有未投递的梦 → **不叠加**（攒一堆会骚扰用户）
  ② 今天已生成过 → **一天一场**
  ③ `last_chat_time` 不晚于上一场梦 → 没新素材
- `_dream_due()` 返回**原因**而不是布尔（后台任务要能解释"梦怎么没来"）
- `mark_delivered()` 由 `proactive_engine` 在 `generate_message` **成功后**调用 ——
  被冷却拦下时梦不能丢
- 挂在 `world_tick_scheduler._tick_one_user` 里（world tick 之后，`run_in_executor`）
- `RUN_BACKGROUND_TICK=0` 时不会自动生成，手动入口就是 `ensure_dream_pending()`

### Agent Modules (All Use DeepSeek)

Every `*_agent.py` module in `funcation/` follows the same pattern: imports OpenAI client, reads `DEEPSEEK_API_KEY` from env, and calls `deepseek-chat` model. Each handles one specific domain:

| Agent | Called in /chat | Purpose | Temperature |
|-------|----------------|---------|-------------|
| `unified_state_agent` | Step 11 | 统一分析画像+好感+状态（一次 LLM 调用） | 0 |
| `world_event_agent` | Step 6 | Tick world events, auto-generate new events, apply character impact | 1 (for generation) |
| `story_agent` | Step 7 | Generate/advance multi-stage story arcs (主线+支线) | 1 |
| `interaction_agent` | Step 8 | Build NPC social context prompt from world state | N/A (prompt builder) |
| `recall_agent` | Step 9 | Determine which RAG collections to search based on user input | 0 |
| `memory_agent` | Step 16 | Classify user msg as add/update/ignore for long-term memory | 0.9 |
| `character_agent` | (on `POST /character/create`) | Generate full character persona (name/description/personality/system_prompt) from a user keyword via DeepSeek | 0.9 |
| `query_classifier` | (utility) | Classify user queries for routing | — |
| `proactive_decision` | (proactive) | Decide whether to send proactive greeting | — |
| `proactive_message_agent` | (proactive) | Generate proactive greeting message | — |
| `proactive_trigger` | (proactive) | Detect triggers for proactive messages | — |
| `proactive_cooldown` | (proactive) | Manage cooldown between proactive messages | — |

**Legacy agents** (已弃用，保留兼容 shim)：
- `profile_agent` — 仅保留 `generate_caring_message()`，主流程已被 unified_state_agent 取代
- `relationship_agent` — 仅保留 `get_relationship_level()`，主流程已被 unified_state_agent 取代
- `state_agent` — 已删除，功能全部合并到 unified_state_agent

### WebSocket / WebRTC Voice Call System

`api/websocket.py` provides two WebSocket endpoints:

- **`/voice/call`**: Main voice call signaling channel. Handles WebRTC offer/answer exchange, ICE candidate relay, conversation start, audio data relay, text messages (from browser speech recognition), and call teardown. Uses `webrtc_agent` for signaling and `conversation_manager` for dialogue processing.
- **`/voice/status`**: Status monitoring endpoint that pushes connection count every second.

`funcation/webrtc_agent.py`: WebRTC signaling server using **aiortc**. Manages `CallSession` objects with `RTCPeerConnection` instances configured with Google STUN servers (symmetric with the frontend). Handles offer/answer/ICE candidate relay between frontend and server. Parses incoming ICE candidate SDP strings into `RTCIceCandidate` via `_parse_candidate_sdp`.

`funcation/conversation_manager.py`: Voice conversation orchestrator. Mirrors the `/chat` endpoint's agent flow but in an async context for real-time voice. Manages `ConversationContext` per call (state machine: IDLE → LISTENING → PROCESSING → SPEAKING), processes text from browser speech recognition, generates AI replies via DeepSeek, and queues TTS synthesis. The `process_tts_queue` background coroutine (started in `api.py` lifespan) consumes the queue, synthesizes audio via `voice_service`, and **sends base64-encoded WAV back to the frontend** via `_send_audio_to_frontend` over the call's WebSocket (`{"type":"tts_audio","audio":...}`).

**Barge-in (interrupt)**: when the user starts speaking while the AI is playing TTS, the frontend sends `{"type":"interrupt","call_id"}`. `conversation_manager.interrupt(call_id)` bumps the call's `tts_epoch`; queue items record their epoch at enqueue, and `process_tts_queue` discards any item whose epoch no longer matches (both before and after synthesis — Edge TTS can't be cancelled mid-synthesis, so the result is dropped instead). A new `text_message` also bumps the epoch, so leftover TTS from the previous turn is auto-discarded.

`funcation/voice_service.py`: TTS service with **pluggable engines**. `ResolvedVoice` 是一次合成最终生效的音色参数，`synthesize()` 按 `voice.engine` 分发：
- `edge`（默认，`edge-tts` 包，免费中文合成）—— rate 是百分比、pitch 是 Hz、volume 是百分比，格式必须 `+0%` / `+0Hz`；
- `clone`（本地音色克隆，**未部署**）—— 吃 `reference_audio`。刻意抛错而不回退：用户配了克隆音色却听到别人的声音，比报错更糟。

**音色解析链**（`voice_pack.resolve_voice_config`）：角色绑定的语音包 → 旧的按角色写死映射（`LEGACY_CHARACTER_VOICES`）→ 环境变量兜底。返回里带 `source`，方便说清"这个声音是哪来的"。

**必须重试**：edge-tts 是云端服务，实测同一段文本同一组参数连打 4 次可能挂 2 次（`NoAudioReceived`）。`_synth_edge` 默认重试 3 次、线性退避；不重试的话语音通话里这句话就直接没声音，用户只看到角色"张了张嘴"。

### ⚠️ edge-tts 上游换主机（2026-10）—— `funcation/edge_tts_compat.py`

**症状**：合成全部失败，`WSServerHandshakeError: 403, message='Invalid response status'`。
**最坑的地方**：旧主机**仍在正常提供音色列表**（`VOICE_LIST` 走 HTTPS），只有合成（WSS）被拒 ——
所以看起来像"HTTPS 通、WSS 403"，极易误判成鉴权/代理/时钟问题（这些都实测排除过）。

**真因**：微软把语音合成后端迁到新主机，**按地区分批切换**（先"许多国家"，2026-10-12 轮到美国）。
edge-tts 7.2.8（当前最新版）仍指向旧主机。上游记录 rany2/edge-tts#490、修复 PR #491。

**修法**（`edge_tts_compat.apply()`，在 `_synth_edge` 里惰性调用）：新主机
`api.msedgeservices.com/tts/cognitiveservices/websocket/v1` **接受同一个 legacy token**，
但要作为 `Ocp-Apim-Subscription-Key` 传。

- **必须改 `edge_tts.communicate.WSS_URL`**，改 `edge_tts.constants.WSS_URL` **不生效** ——
  `communicate` 是 `from .constants import WSS_URL`，改源模块不影响已绑定的名字。
- 顺带修 `DRM.parse_rfc2616_date` 的 locale 依赖：它用 `strptime("%a, %d %b ...")`，
  而 `%a`/`%b` 跟随进程 locale。**实测本机（中文 Windows）切到系统 locale 后返回 `None`**，
  于是"时钟偏移自动校正"失效，真 403 会被 `SkewAdjustmentError` 盖住，排查时看不到真因。
- `EDGE_TTS_LEGACY_HOST=1` 可退回旧主机（万一某些地区旧主机仍可用）。
- **上游发版后本模块可删**：`pip install -U edge-tts` 装到含 #491 的版本即可。
- 惰性调用（不在模块顶层 import edge_tts）：保持启动快，且未安装 edge-tts 时也能起服务。


**音调的坑**：`<prosody pitch=...>` 确实发给了微软，但**部分中文音色会忽略它** —— 实测 +0Hz / +30Hz / -30Hz 输出字节数完全相同（输出是 48kbps CBR，字节数 = 时长的精确代理）。所以界面上要如实说明"听不出变化属正常"，别让用户以为坏了。

### 语音包（Voice Pack）

**管理员维护的全局库**（所有 `/voice/*` 接口都是 `require_admin`）：语音包是全局资源，改动会影响所有角色和所有用户；角色本身也是全局共享的，所以"角色 → 语音包"的绑定同样全局。好处是**运行时合成不需要 user_id**，语音通话链路一行都没改。

- `funcation/voice_pack.py`：纯函数（schema / clamp / 音色名校验 / 参考音频扩展名白名单 / 解析链 / 删包后的绑定清理）。无 IO、无 FastAPI 依赖。
- `funcation/voice_store.py`：落盘 `data/voice_packs.json` + `data/voice_bindings.json` + `data/voice_refs/<pack_id>.<ext>`。读坏文件退回默认值而不是抛异常。
- 接口：`GET /voice/voices`（音色目录 + 引擎可用状态）、`GET/POST /voice/packs`、`PATCH/DELETE /voice/packs/{id}`、`POST/DELETE /voice/packs/{id}/reference`、`POST /voice/preview`（试听，支持已存包或即时参数）、`POST /voice/bindings`（`pack_id=null` 解绑）。
- **改语音包必须清 TTS 缓存**（`voice_service.clear_cache()`），否则改了音色还在放旧音频。缓存键含 `ResolvedVoice.fingerprint()`。
- **单包响应用 `_pack_view()`**：它比 `summarize_pack` 多带 `engine_available`。漏掉的话前端"编辑保存后"拿不到引擎状态，只能靠再刷一次列表自愈（形状不一致是隐患）。
- **`normalize_pack` 的 `pick` vs `base.get`**：`reference_audio` 由上传接口写入，普通更新只保留旧值（走 `base.get`）；`reference_text` 是普通文本字段，必须走 `pick` 读入参。踩过：两个都写成 `base.get`，结果参考文本创建时永远为空、更新时改不动 —— 而克隆引擎恰恰要靠它对齐音色。
- 参考音频上传与 3D 模型同一套写法：`.part` → 校验大小/格式 → 原子改名；换格式重传时清掉旧后缀文件。
- **接克隆引擎时**：新增一个 engine 值 + 一个 `_synth_*` 适配器即可，存储/接口/前端都不用动 —— 参考音频早就存好了。

### Prompt Assembly

`funcation/prompt.py` builds the full system prompt from ~12 data sources. The prompt sections (in order):
1. World context (name + background)
2. Character info (name, description, personality)
3. Relationship status (attitude based on favorability thresholds: <20/50/80)
4. Relationship level + last change reason
5. Current story (title, description, current stage) — 多剧情时取第一条 active main
6. Character state (mood, energy, current event)
7. User profile summary
8. Memory summary (recent chat, long-term memory, key events, chat summaries)
9. Story history (last 5 story items) — 实际取 history + active
10. **RAG retrieved memories** (semantically relevant context from ChromaDB)
11. **NPC social context** (other characters' states and recent interactions)
12. **World events** (active world events affecting the scene)
13. Self-awareness section (A4) — 关系演变轨迹、升温/冷却感知、峰值怀念
14. Mood-driven behavior instructions (开心/低落/疲惫/生气)
15. 8 rules (瘦身后的规则，原 19 条)

**规则详情见 `prompt.py:432-498`**：包括保持人设、2-5 句回复、用你/ta 指代、避免重复、记住用户信息、调用记忆、感知自我意识、对 NPC 表达看法。

### World Event System

`funcation/world_event_agent.py`: Manages a world-level event timeline. Events have title, description, importance, progress (0-100), status (running/finished/paused), and character impacts. The `tick()` function advances world time, progresses events, auto-generates new events via DeepSeek, applies impacts to characters, and can trigger story generation from completed events.

`funcation/interaction_agent.py`: Manages NPC-to-NPC relationships and interactions within a world. Tracks relationship scores between all character pairs, records interaction history, generates gossip, and can simulate multi-character interactions driven by world events.

**World Modes**:
- `public` — 全员共享，`data/world_state/{world_id}.json`
- `private` — 用户私有副本，`data/world_state/{user_id}/{world_id}.json`

### Proactive Greeting System

`funcation/proactive/`: Sub-package for character-initiated messages:
- `proactive_trigger.py`: Detects conditions (idle time, favorability changes, time of day, events)
- `proactive_decision.py`: Decides whether to send a message (DeepSeek, with cooldown)
- `proactive_message_agent.py`: Generates the greeting text (DeepSeek)
- `proactive_cooldown.py`: Prevents message spam
- `proactive_engine.py`: Orchestrates the full flow

Called via `GET /proactive` endpoint. Results are cached in MemoryCenter and also exposed via `GET /proactive-message` and `GET /caring-message`.

### Character Files

Character definitions in `data/characters/{id}.json` are static (read-only after creation). The character ID is the JSON field `"id"`, and the filename always matches the id. Known built-in characters:
- `linwan` (林婉): cold exterior, secretly caring — `linwan.json`
- `maid` (小羽): gentle maid — `maid.json`
- `xiaomei` (小梅): aloof, sometimes sarcastic — `xiaomei.json`

> 例外：`avatar` 与 `model3d` 两个字段在运行时会被写入（`/character/avatar`、`/character/model*`）。`MemoryCenter.load_character_by_id()` 带 mtime 缓存，写盘后首次读取会自动失效。

**Creating characters at runtime**: `POST /character/create` lets the frontend create a new character from a free-text keyword. `character_agent.generate_character(keyword)` calls DeepSeek (temp=0.9, `response_format=json_object`) to produce `name`/`description`/`personality`/`system_prompt`; the caller passes an optional `name` to override. The endpoint generates an ASCII id `char_{uuid4().hex[:8]}` (collides-checked against existing ids) so Chinese names never become filenames on Windows, then `MemoryCenter.save_character()` writes `data/characters/{id}.json`. The per-character memory file `data/memories/{user_id}/{id}.json` is **not** created eagerly — `load_memory()` auto-creates it on the first `/chat` for that character.

**Character ownership**: Each character JSON now has a `created_by` field (integer user ID). Built-in characters (linwan, maid, xiaomei) have no `created_by` and are visible to all users. `GET /characters` filters by owner: admins see all, regular users see built-ins + their own. `_check_character_access()` in `api.py` enforces this on write endpoints (`/character/switch`, `/character/avatar`, `/chat`, `/character/current`).

### 3D 角色模型 (VRM / glTF)

角色可以绑定一个 3D 模型，前端 `CharacterPortrait3D` 会在聊天页 / 语音通话 / 桌面挂件里渲染它；未绑定或加载失败时自动降级为 2D 头像。

**存储**：模型文件落在 `data/models/{character_id}_{hex}.{ext}`，通过 `app.mount("/models", StaticFiles(...))` 静态托管（与 `/avatars` 同一模式）。角色 JSON 里新增 `model3d` 字段：

```json
"model3d": {
  "url": "/models/linwan_b8b12878.vrm",
  "format": "vrm",              // vrm | glb | gltf
  "enabled": true,
  "scale": 1.0,                 // 0.1–5
  "rotation_y": 0.0,            // -180–180
  "position": {"x":0,"y":0,"z":0},
  "camera_distance": 1.4,       // 0.3–5
  "camera_height": 1.3,         // 0–3
  "camera_fov": 30.0,           // 10–90
  "default_expression": "neutral",
  "auto_rotate": false,
  "background": "transparent",
  "updated_at": "2026-09-18T03:10:42+00:00"
}
```

**代码位置**：`funcation/model3d.py` 是纯函数模块（无 IO / 无 FastAPI 依赖，便于单测）——负责扩展名白名单（`.vrm`/`.glb`/`.gltf`）、大小上限、文件名净化、配置归一化与 clamp、列表摘要。API 端点写在 `api/api.py`（`Model3DConfigRequest` + 4 个路由）。

**关键设计**：
- **先落临时文件再校验**：上传先写 `data/models/.upload_<hex>.part`，校验通过才 `os.replace` 成正式文件，非法/超限文件不会留下残渣。
- **大小上限**：默认 64MB，环境变量 `MODEL_MAX_MB` 可覆盖（`model3d.max_model_bytes()`）。
- **旧文件清理**：重新上传时删除上一个由本服务托管的文件；`_delete_managed_model_file()` 只处理 `/models/` 前缀且只取 basename（天然防目录穿越），外链 URL 一律不动。
- **权限**：与头像一致，走 `_load_owned_character()`（`character_id` 可选，缺省用该用户当前角色）→ `_check_character_access()`；读取只需 `require_auth`，上传/改配置/删除需要 `require_approved`。
- **列表摘要**：`get_all_characters()` 返回精简的 `model3d: {url, format, enabled}`（未绑定为 `null`），前端用它在角色卡上显示 3D 标识。
- **前端字段语义**：`scale` 在前端被解释为「取景远近」（`cameraPadding / scale`），因为 `ThreeScene.frameObject()` 会自动把模型框满画面，直接改 `mesh.scale` 会被自动取景抵消。

### World Files

World definitions in `data/worlds/{id}.json` provide setting context. Known worlds:
- `campus` (校园): university daily life
- `cyberpunk` (赛博朋克): neon-lit corporate dystopia 2099

Worlds now have dynamic runtime state per mode:
- Public: `data/world_state/{world_id}.json`
- Private: `data/world_state/{user_id}/{world_id}.json`

## Important Patterns

- **Lazy imports for agents**: `MemoryCenter` methods use `from funcation import X` inside method bodies (not at module top) to avoid circular imports.
- **File I/O per call**: Each `MemoryCenter` method does its own load-modify-save cycle. There's no in-memory caching or batching. For a single-user app this is fine.
- **Layered degradation in `/chat`**: The `/chat` endpoint wraps each step in a `_safe(label, fn, default)` helper. **Critical path** (character/messages/mem load with fallbacks, `build_system_prompt`, DeepSeek main reply via `retry_sync`, save history, `memory_agent` extraction) failures return `{"error": "..."}` with HTTP 200. **Non-critical agents** (`world_event_agent.tick`, `story_agent`, recall+RAG retrieval, `interaction_agent`, `update_profile`, `relationship_agent`, `state_agent`, `_sync_*_to_rag`) failures are caught, logged via `logger.warning("[chat] <label> 降级跳过: ...")`, and skipped — the main reply still goes through. An outer `try/except` catches anything unexpected so the endpoint never returns a bare 500.
- **`response_format={"type": "json_object"}`**: Used by `memory_agent` and `profile_agent` to force structured JSON from DeepSeek. `relationship_agent` and `story_agent` use plain text + manual JSON parsing with `json.loads()`.
- **Directory name**: The package is `funcation` (not `function`). This is intentional — all imports use this spelling.
- **No `__init__.py`**: The `funcation/` directory has no init file. Imports use `from funcation import module_name`. Exception: `funcation/proactive/` has an `__init__.py`.
- **Fallback paths**: `MemoryCenter.load_character_by_id()` and `load_world_by_id()` try `data/` first, then fall back to old root-level directories.
- **RAG sync is eager**: Every `/chat` call syncs profile, story, and relationship to ChromaDB via `_sync_*_to_rag()` helper functions. This keeps vectors fresh but adds latency.
- **ChromaDB auto-recovery（已收紧，2026-10-12）**：`memory_rag._get_client()` / `_get_collection()` 只在**确实损坏**时才隔离重建，规则如下 ——
  - **隔离 = 数据丢失**（`long_memory`/`events`/`chat_summary` 只存向量库）。所以隔离前**必须先过 `is_persist_dir_healthy()`**：能只读打开 + `PRAGMA integrity_check` = ok → **拒绝隔离**，让调用方重试。判不出来（文件被占用/权限）也按健康处理 —— 宁可漏判，也不误删。
  - **异常分类用 `is_corruption_error()`，按异常类型判断，绝不看 `str(exc)`**。网络类（`httpx.HTTPError` / `ConnectionError` / `TimeoutError` / `OSError`）一律不算损坏。踩过的坑：旧代码 `"connect" in msg` 本意是匹配 chroma 的 `Could not connect to tenant`，但也会命中 `httpx.ConnectError`（FastEmbed 访问 huggingface.co 被代理拦成 502），把**健康**的库整个 move 走；而且它看消息文本，英文 locale 命中、中文 locale 不命中，行为随部署环境漂移。
  - **隔离事件必须可见**：`record_quarantine_event()` 记 traceback + 计数，`GET /health` 的 `rag` 段暴露 `quarantine_count` / `rejected_count` / `healthy` / `last_event`。之前只有一行 `logger.warning`，导致 6 次误隔离几个月无人发现。
  - **启动时会尝试从健康的隔离目录恢复**（`try_restore_quarantined_dir()`），而不是直接重建空库。实测那 6 个隔离库全部 `integrity_check=ok` 且能被 chromadb 正常打开（各 12 个集合、15 条记录）—— 它们从来没坏过。
  - 隔离目录 `data/chroma_corrupt_<ts>/` 保留作取证；`_auto_rebuilt` 是进程级标志，防无限重建；`release_client()` 在 lifespan shutdown 调用以释放 sqlite 句柄。
  - 历史行为（仅作背景）：曾被判定为"损坏"并隔离的目录**原样保留**，可用 `is_persist_dir_healthy()` 判定后手工恢复。
- **WebSocket singleton pattern**: `conversation_manager` and `webrtc_agent` are module-level singletons imported directly by `api/websocket.py`.
- **TTS is async-queued and fully wired**: `conversation_manager` puts TTS requests on an `asyncio.Queue`; the `process_tts_queue` background coroutine (started in `api.py` lifespan) synthesizes audio via `voice_service` (Edge TTS) and pushes base64 WAV back to the frontend over the call's WebSocket as `{"type":"tts_audio","audio":...}`. The frontend `playTtsAudio()` decodes and plays it. **The `edge-tts` package must be `pip install`ed** (it is in `requirements.txt` but not auto-installed); if missing, `process_tts_queue` logs `No module named 'edge_tts'` per message and no `tts_audio` ever reaches the frontend — the text reply still works, but the user hears nothing. Same caveat applies to `aiortc` (WebRTC).
- **Environment**: `.env` file must contain `DEEPSEEK_API_KEY`. Optional: `TAVILY_API_KEY`, `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`.

## Backend API Endpoints

### Health & Auth
- `GET /health` — Health check (Docker / load balancer)
- `POST /auth/register` — User registration
- `POST /auth/login` — User login (returns JWT token)
- `GET /auth/me` — Get current user info (requires auth)
- `POST /auth/users/{user_id}/approve` — Admin: approve pending user
- `POST /auth/users/{user_id}/reject` — Admin: reject pending user

### 系统配置（仅管理员）
- `GET /admin/config` — 配置 schema + 当前生效值。**前端按 schema 渲染**，加字段只需改 `system_config.FIELDS`
- `PATCH /admin/config` — 局部更新；值为 `null` 表示恢复默认

**`funcation/system_config.py`**：让管理员在界面上改运行时配置，而不是「改 `.env` → 重启」。

- **优先级：配置文件 > 环境变量 > 代码默认值** —— 所以**什么都不配时行为与改动前完全一致**（有测试钉住）。
- 存储 `data/system_config.json`，**只存被显式改过的键**。全量落盘会把默认值冻结，以后改代码默认值就对老部署失效。
- **schema 驱动**：`ConfigField` 声明类型/范围/默认值/`restart_required`。加字段只改 `FIELDS` 一处。
- **`default` 可以是零参可调用对象**：用于「默认值本来就定义在别处」的情况（如 `model3d.DEFAULT_MAX_MODEL_MB`）。
  这样默认值只有一份真源，测试里 `monkeypatch.setattr(voice_pack, "MAX_PACKS", 2)` 仍然有效。
  **如果在这里复制一个数字，就会盖住模块常量，把老测试全打挂**（本次踩过）。
- **绝不暴露密钥**：`JWT_SECRET_KEY` / `ADMIN_DEFAULT_PASSWORD` / API key 都不进 schema ——
  界面上改密钥有安全风险，也会让现有会话失效。有测试钉住 schema 里不含这些词。
- **`restart_required=True` 要如实标注**：world tick 间隔与嵌入模型是**模块导入时**读的，
  进程内改不了。如实标注比假装能热更新好 —— 否则用户改完没生效会以为坏了。
- **`upload.model_max_mb` 刻意是小数型**：原实现用 `float(os.getenv("MODEL_MAX_MB"))` 解析，
  已有部署可能配了 `0.001` 这类值；改成整数型会**悄悄收窄既有的 env 契约**。
- 改完配置要 `voice_service.clear_cache()`，否则还在放旧音频。
- **消费方接入时都要保留「没配就回退原行为」**：`voice_service.env_defaults()`（TTS 全局默认）、
  `model3d.max_model_bytes()`、`voice_pack.max_ref_bytes()/max_packs()`、
  `world_tick_scheduler` 的三个间隔、`embedding_manager` 的 provider/model。

> ⚠️ 接 `tts.*` 时踩过一个坑：`voice_service.env_defaults()` 当时**从来没有被生产代码调用过**，
> 而 `voice_pack.resolve_voice_config()` 的 default 分支硬编码 `FALLBACK_VOICE` ——
> 也就是说配置改了**不会生效**。现在 `resolve()` 会把 `env_defaults()` 作为 `global_default`
> 传进去（`resolve_voice_config` 保持纯函数，不直接依赖配置模块）。

### 音色克隆引擎（OpenVoice V2）

**跑在独立 sidecar venv `.venv-clone` 里，不在主 venv。**

原因：主 venv 是 numpy 2.x（在跑 RAG），MeloTTS/OpenVoice 要 numpy 1.x + transformers 4.x ——
装进同一个 venv 会把 numpy 降级、把正在用的东西搞挂。
**实测主 venv numpy 保持 2.4.6 未动。**

架构：`voice_service._synth_clone()` → `funcation/voice_clone.py`（asyncio 子进程管理）
→ `backend/voice_clone_worker.py`（常驻进程，JSON Lines over stdin/stdout）

- **常驻**：模型加载 ~18s，每句合成都起进程交互上不可接受；热启动 ~1.6s。
- **不占端口**，不需要额外 supervisor；进程崩了下次请求自动重启重试一次。
- 音频走**临时文件**回传（worker 写 `data/tmp/clone/*.wav`，manager 读后即删）——
  **不要改成 base64 塞 stdout**：几百 KB 的音频会撞 asyncio readline 默认 64KB 上限（踩过）。
- **speaker embedding 按参考音频内容哈希缓存**（`_hash_file`，不是文件名/mtime）。
- **先查 sidecar 装没装，再查参考音频** —— 否则"没装引擎"会被"参考音频不存在"掩盖（踩过）。
- **绝不静默降级到 edge**：选克隆音色却听到默认音色比报错更糟。
- 安装：`pwsh backend/scripts/setup_clone_env.ps1`（约 4GB：torch + ~480MB 权重）；
  `python backend/scripts/fetch_openvoice_ckpt.py` 幂等，可反复跑。

**vendor/ 里有两个第三方源码副本**（`vendor/OpenVoice`、`vendor/MeloTTS`）：
- **不要手改**。唯一例外是 `vendor/OpenVoice/openvoice/api.py` 里一处**上游 bug** 的本地修正
  （`ToneColorConverter.__init__` 把 `enable_watermark` 透传给只接受两个参数的基类 → TypeError），
  已带注释说明。
- `pip install melotts` **装不上**：PyPI 那个 sdist 的 `setup.py` 引用了不存在的
  `requirements.txt`。必须从 vendor 本地装 + `--no-deps`
  （它的 requirements 会拉进 gradio/mecab/unidic 一堆用不到的东西）。

**踩过的坑（按踩的顺序）**：
1. 官方文档里的权重地址（`myshell-public-repo-host.s3.amazonaws.com`）**已 404**；
   权重其实在 HuggingFace 的 `myshell-ai/OpenVoice` + `myshell-ai/MeloTTS-Chinese`。
2. 直连 `huggingface.co` 不通，必须 `HF_ENDPOINT=https://hf-mirror.com`。
3. `github.com` 主站也不通，用 **codeload.github.com** 下 tar 包。
4. `melo/text/japanese.py` 在**模块导入时**就要求 mecab/fugashi（哪怕只用中文）——
   因为 `cleaner.py` 无条件 import 它。
5. MeloTTS 中文默认走 BERT，用 `hps.data.disable_bert = True` 关掉，
   省 ~1.3GB 的 RoBERTa 下载（代价是韵律略差）。
6. NLTK `cmudict`（`g2p_en` 要的）：NLTK 官方源走 raw.githubusercontent.com（被墙），
   用 `gh-proxy.com` 代理拉，解压到 `~/nltk_data/corpora/`。
7. OpenVoice 的 `load_ckpt()` 直接 `print()` 到 **stdout**，会污染协议流 ——
   worker 里用 `contextlib.redirect_stdout(sys.stderr)` 包住，manager 侧也做防御（跳过非 JSON 行）。
8. `_state["base_se"] or tgt_se` 这种写法对 Tensor 会直接 RuntimeError（布尔值歧义）。
9. worker 的 ready 事件一开始写在 stderr，而 manager 在 stdout 上等 → 永远等不到。已改成走 stdout。

### 克隆引擎的 UI 接入（2026-10-14 补完）

上一轮把引擎接进后端后，**前端还用不了** —— 已补齐：

- `engine_available('clone')` 原来**写死 `return False`**（注释写着"接入后改"），
  现在探测 sidecar venv 的 `python.exe`。不启动进程（`/voice/voices` 会频繁调）。
  ⚠️ 测试别写死"clone 不可用" —— 那是**环境依赖**，引擎一接好就全红。要 monkeypatch
  `voice_clone.SIDECAR_PYTHON`。
- **修了一个真 bug**：`/voice/preview` 的即时参数分支构造 `ResolvedVoice` 时漏了
  `reference_audio`，而 `normalize_pack` 又**刻意**只从 base 读它（只有上传接口写它）——
  两者叠加导致**新建克隆包时点试听必然报"没有参考音频"**。
  现在 `VoicePreviewRequest` 收 `reference_audio`，构造时显式覆盖。
- 顺带发现 `test_update_pack_can_switch_engine_and_voice` **被定义了两次**
  （Python 里后者静默覆盖前者，前一个**从来没跑过**）。

### 克隆引擎的两个坑（2026-10-14 修）

**1. `speaker_id` 默认值一直是错的（会出静音）**

ZH 模型配置：`"n_speakers": 256` 但 `"spk2id": {"ZH": 1}` ——
**256 个槽位只有 id=1 训练过**，其余喂进去**产出全静音**（实测 peak=0.0001）。
官方用法是 `tts_to_file(text, spk2id['ZH'], ...)`，跟着 `spk2id` 走。
把默认写死成 0 的后果：合成"成功"返回一个静音 wav。
现在 `_default_speaker_id()` / `_resolve_speaker_id()` 都基于 `spk2id`，
未训练的 id 会**回退到已训练的那个并告警**。
⚠️ **别给 256 个槽位做下拉** —— 用户会选到静音。

**2. 输出响度只有 -43 dBFS**

比 edge-tts 小 20 多 dB（用户会觉得"克隆的声音特别小"）。
`_normalize()` 做 RMS 归一化到约 -20 dBFS，带增益上限（+26dB）和峰值保护。

**3. worker 改成守护进程（跨后端重启保活）**

- worker 绑 127.0.0.1 随机端口，把端口写进 `data/tmp/clone/worker.json`；
  后端**先找活着的 worker，找不到再拉起**。
- **必须用普通 `subprocess.Popen` 启动，不能用 `asyncio.create_subprocess_exec`** ——
  后者的 transport 在**事件循环关闭时会 kill 子进程**，父进程一退出 worker 就死
  （这是本轮最大的坑，加 `CREATE_BREAKAWAY_FROM_JOB` 也救不了，因为根本不是 Job 的问题）。
  守护进程走 socket，不需要 asyncio 的管道管理。
- `stop()` **只断连、不杀 worker**（杀了就白费保活）。真停用
  `scripts/stop_clone_worker.py`；它也会按 `VOICE_CLONE_IDLE_EXIT`（默认 20 分钟）空闲自退。
- ⚠️ **改了 worker 代码必须重启 worker** —— 它是常驻进程，不会自动重载。
- 端点文件指向死进程时会**自愈**（实测 4.6s 拉起新的）。

**验证音频必须量 peak/rms。** 上一轮只验了 `HTTP 200 + RIFF 头 + 164KB`
就当成通过，实际那 164KB 是**全静音**。这个教训比任何单点 bug 都值钱。

**实测耗时**（CPU）：首句 **20.6s**（加载约 480MB 模型），之后 **1.6s**。
之前量到过一次 77s，那是**磁盘缓存冷**的偶发，不是常态。
worker 随后端进程共生（后端重启 = 再冷一次）。**刻意不做启动预热**：
那会让不使用克隆的用户也白占 480MB 内存。

**验证数据**（2026-10-12，CPU）：
- 冷启动 18.0s → 产出 1.83s 音频；**热启动 1.6s**；临时文件无残留；embedding 缓存命中
- **音色克隆客观验证**：参考音频是合成的 129.7Hz 男声，克隆输出 **158.6Hz**
  （MeloTTS 默认 ZH 女声约 200Hz）→ 基频明显向参考靠近，转换确实生效
- 后端 pytest **318 passed**；主 venv numpy 未动
> **加配置项后一定要验证它真的影响运行时，而不是只被存下来。**


### Character
- `GET /characters` — List available characters (filtered by ownership)
- `POST /character/create` — Create character from keyword
- `POST /character/switch` — Switch active character
- `GET /character/current` — Full character definition
- `POST /character/avatar` — Upload character avatar image

### Character 3D Model (VRM / glTF)
- `GET /character/model?character_id=` — Read `model3d` config (null when unbound)
- `POST /character/model?character_id=` — Upload `.vrm` / `.glb` / `.gltf` (multipart `file`)
- `POST /character/model/config?character_id=` — Patch config (scale / camera / expression / external url)
- `DELETE /character/model?character_id=` — Unbind model + delete managed file (falls back to 2D avatar)

### Chat
- `POST /chat` — Send message (non-streaming, fallback only)
- `POST /chat/stream` — Send message (SSE streaming, default)
- `GET /history` — Recent 10 messages
- `POST /chat/tts` — 把一段文本合成为**当前角色音色**的语音（聊天页朗读用）。`require_approved`（**普通用户功能，不是管理员**，别照抄 `/voice/preview` 的管理员门）；不接收音色参数，按 `character_id` 解析角色绑定的语音包 —— 这是语音包在文本聊天场景生效的入口。复用 `voice_service.synthesize_speech()`，自带缓存。文本上限 `voice_pack.MAX_SYNTH_CHARS`（600），超限 400；引擎不可用 503 带原因。

### State & Memory
- `GET /favorability` — Current favorability score
- `GET /profile` / `POST /profile` — User profile
- `GET /relationship` — Relationship level + reason
- `GET /character/state` — Character mood/energy/current event
- `GET /memory/full` — Full memory snapshot
- `GET /memory/search?query=...` — Semantic memory search (RAG)
- `POST /memory/add` / `POST /memory/update` / `POST /memory/delete` — RAG memory CRUD
- `GET /memory/stats` — RAG collection stats

### Story (A3 多剧情)
- `GET /story` — Current stories (多线剧情 + 历史)
- `POST /story/advance` — Advance specific story
- `POST /story/branch` — Create story branch point

### World
- `GET /worlds` — List available worlds
- `GET /world/current` — Current world
- `POST /world/switch` — Switch world (public/private mode)
- `GET /world/events` — World events and state
- `GET /world/interactions` — NPC interaction records
- `POST /world/interaction/simulate` — Trigger NPC interaction

### Proactive
- `GET /proactive` — Proactive greeting message
- `GET /proactive-message` / `GET /caring-message` — Cached messages

### WebSocket
- `WS /voice/call` — Voice call signaling
- `WS /voice/status` — Status monitoring

## 环境变量

| 变量 | 必需 | 默认值 | 说明 |
|------|------|--------|------|
| `DEEPSEEK_API_KEY` | 是 | - | DeepSeek API 密钥 |
| `OPENAI_BASE_URL` | 否 | `https://api.deepseek.com` | OpenAI 兼容 API 地址 |
| `TAVILY_API_KEY` | 否 | - | Tavily 搜索 API（可选） |
| `EMBEDDING_PROVIDER` | 否 | `fastembed` | 嵌入模型提供商 |
| `EMBEDDING_MODEL` | 否 | `BAAI/bge-small-zh-v1.5` | 嵌入模型名称 |
| `TTS_PROVIDER` | 否 | `edge` | TTS 提供商 |
| `VOICE_NAME` | 否 | `zh-CN-XiaoxiaoNeural` | Edge TTS 语音 |
| `RUN_BACKGROUND_TICK` | 否 | `1` | 是否启用后台 world tick |
| `WORLD_TICK_LOOP_SEC` | 否 | `1800` | 后台 tick 间隔（秒） |
| `WORLD_TICK_MIN_INTERVAL_MIN` | 否 | `30` | 单 world 最小 tick 间隔（分钟） |
| `WORLD_TICK_ACTIVE_DAYS` | 否 | `7` | 活跃用户判定窗口（天） |