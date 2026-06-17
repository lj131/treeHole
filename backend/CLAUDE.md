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
          'funcation/conversation_manager.py', 'funcation/character_agent.py',
          'funcation/proactive/proactive_engine.py', 'funcation/proactive/proactive_trigger.py',
          'funcation/proactive/proactive_decision.py', 'funcation/proactive/proactive_message_agent.py',
          'funcation/proactive/proactive_cooldown.py']:
    py_compile.compile(f, doraise=True)
print('OK')
"

# Integration test via TestClient
python -c "
from fastapi.testclient import TestClient
from api.api import app
client = TestClient(app)
r = client.post('/chat', json={'message': '你好'})
print(r.json())
"
```

No test framework, linter, or type checker is configured. No `setup.py`, `pyproject.toml`, or build system.

## Architecture

This is a **character-based AI chat system** (AI companion simulator). A FastAPI server receives chat messages, assembles a rich system prompt from multiple data sources, calls DeepSeek, and returns the AI character's reply. It also supports **real-time voice calls** via WebRTC + WebSocket, a **proactive greeting** system, and a **world event** system with NPC interactions.

### Core Data Flow (POST /chat)

```
POST /chat
  → MemoryCenter.load_current_character()     # data/characters/{id}.json
  → memory.load_memory(char_id)               # memories/{id}_memory.json (chat history)
  → MemoryCenter.load_memory(char_id)         # data/memories/{id}.json (all dynamic state)
  → MemoryCenter.load_current_world()         # data/worlds/{id}.json
  → world_event_agent.tick()                  # Advance world events, auto-generate if needed
  → story_agent.check_story()                 # Generate/advance multi-stage story (DeepSeek)
  → story_agent.sync_story_to_state()         # Copy current story stage → character_state
  → _sync_story_to_rag()                      # Sync story to ChromaDB vector store
  → interaction_agent.build_social_prompt()   # Build NPC social context for prompt
  → recall_agent.detect_memory_scope()        # Determine which RAG collections to search
  → memory_rag.retrieve_memories()            # Semantic search across ChromaDB collections
  → prompt.build_system_prompt()              # Assemble full system prompt (~10 data sources + RAG results)
  → mc.update_profile()                       # AI extracts user profile fields (DeepSeek)
  → _sync_profile_to_rag()                    # Sync profile to ChromaDB
  → relationship_agent.update_relationship()  # AI determines favorability delta (-10..+10)
  → _sync_relationship_to_rag()               # Sync relationship to ChromaDB
  → state_agent.analyze_state()               # AI evaluates character mood/energy
  → DeepSeek API (deepseek-chat, temp=0.9)    # Generate reply
  → memory_agent.extract_memory()             # AI decides add/update/ignore long-term memory
  → mc.add_chat_summary()                     # Append to chat summary
  → memory.save_memory()                      # Save chat history to memories/{id}_memory.json
  → Return {reply, favorability}
```

### Key Concept: Two "Memory" Systems

There are **two separate memory concepts** — don't confuse them:

| System | Location | Content | Manager |
|--------|----------|---------|---------|
| **Structured state** | `data/memories/{id}.json` | profile, favorability, long_memory, events, chat_summary, relationship, character_state, story, last_chat_time — all in one JSON | `MemoryCenter` class |
| **Chat history** | `memories/{id}_memory.json` | Raw message array `[{role, content}, ...]` | `memory.py` module |

### Third Memory System: RAG Vector Store

`funcation/memory_rag.py` maintains a **ChromaDB** vector database at `data/chroma/` with 6 independent collections per character:

| Collection | Content | Synced by |
|-----------|---------|-----------|
| `profile` | User profile fields (name, city, job, mood) | `_sync_profile_to_rag()` on each /chat |
| `long_memory` | Long-term memory facts | `memory_agent` extraction |
| `story` | Story overview + individual stages | `_sync_story_to_rag()` on each /chat |
| `events` | World/character events | Event creation/update |
| `relationship` | Relationship level + favorability + reason | `_sync_relationship_to_rag()` on each /chat |
| `chat_summary` | Chat summary entries | Chat summary updates |

Embeddings use **FastEmbed** (BGE-small-zh-v1.5, local ONNX, free) by default. Provider is configurable via `EMBEDDING_PROVIDER` env var. The `embedding_manager.py` module lazy-loads a singleton embedding function.

RAG retrieval flow: `recall_agent.detect_memory_scope()` (DeepSeek) determines which collections to query → `memory_rag.retrieve_memories()` performs semantic search → results are injected into the system prompt.

### MemoryCenter — The Central Hub

`funcation/memory_center.py` is the single entry point for ALL dynamic per-character data. The `MemoryCenter` class manages:

- **Profile** (`profile`): User info extracted by AI — name, city, job, mood, recent_topics
- **Favorability** (`favorability`): 0–100 score, updated by `relationship_agent` (AI-analyzed delta)
- **Relationship** (`relationship`): level (陌生/普通/朋友/亲近/暧昧) + last_reason, auto-calculated from favorability thresholds
- **Long memory** (`long_memory`): List of facts about the user, extracted by `memory_agent`
- **Events** (`events`): Timestamped life events, auto-generated when relationship level changes
- **Character state** (`character_state`): mood, energy, current_event — managed by `state_agent`
- **Story** (`story`): Multi-stage narrative with UUID, stages list, progress tracking
- **Chat summary** (`chat_summary`): Running summary of conversation turns
- **Proactive message cache** (`proactive_message`, `caring_message`): Cached greeting messages
- **Character/world selection**: Reads `current_character.json` and `current_world.json`

### Agent Modules (All Use DeepSeek)

Every `*_agent.py` module in `funcation/` follows the same pattern: imports OpenAI client, reads `DEEPSEEK_API_KEY` from env, and calls `deepseek-chat` model. Each handles one specific domain:

| Agent | Called in /chat | Purpose | Temperature |
|-------|----------------|---------|-------------|
| `world_event_agent` | Step 6 | Tick world events, auto-generate new events, apply character impact | 1 (for generation) |
| `story_agent` | Step 7 | Generate/advance multi-stage story arcs (5+ stages) | 1 |
| `interaction_agent` | Step 8 | Build NPC social context prompt from world state | N/A (prompt builder) |
| `recall_agent` | Step 9 | Determine which RAG collections to search based on user input | 0 |
| `profile_agent` | Step 11 | Extract name/city/job/mood from user messages | 0.3 |
| `relationship_agent` | Step 12 | Analyze sentiment → favorability delta (-10..+10) + reason | 0 |
| `state_agent` | Step 13 | Determine character mood + energy (0–100) | 0 |
| `memory_agent` | Step 16 | Classify user msg as add/update/ignore for long-term memory | 0.9 |
| `character_agent` | (on `POST /character/create`) | Generate full character persona (name/description/personality/system_prompt) from a user keyword via DeepSeek | 0.9 |
| `query_classifier` | (utility) | Classify user queries for routing | — |
| `proactive_decision` | (proactive) | Decide whether to send proactive greeting | — |
| `proactive_message_agent` | (proactive) | Generate proactive greeting message | — |
| `proactive_trigger` | (proactive) | Detect triggers for proactive messages | — |
| `proactive_cooldown` | (proactive) | Manage cooldown between proactive messages | — |

### WebSocket / WebRTC Voice Call System

`api/websocket.py` provides two WebSocket endpoints:

- **`/voice/call`**: Main voice call signaling channel. Handles WebRTC offer/answer exchange, ICE candidate relay, conversation start, audio data relay, text messages (from browser speech recognition), and call teardown. Uses `webrtc_agent` for signaling and `conversation_manager` for dialogue processing.
- **`/voice/status`**: Status monitoring endpoint that pushes connection count every second.

`funcation/webrtc_agent.py`: WebRTC signaling server using **aiortc**. Manages `CallSession` objects with `RTCPeerConnection` instances configured with Google STUN servers (symmetric with the frontend). Handles offer/answer/ICE candidate relay between frontend and server. Parses incoming ICE candidate SDP strings into `RTCIceCandidate` via `_parse_candidate_sdp`.

`funcation/conversation_manager.py`: Voice conversation orchestrator. Mirrors the `/chat` endpoint's agent flow but in an async context for real-time voice. Manages `ConversationContext` per call (state machine: IDLE → LISTENING → PROCESSING → SPEAKING), processes text from browser speech recognition, generates AI replies via DeepSeek, and queues TTS synthesis. The `process_tts_queue` background coroutine (started in `api.py` lifespan) consumes the queue, synthesizes audio via `voice_service`, and **sends base64-encoded WAV back to the frontend** via `_send_audio_to_frontend` over the call's WebSocket (`{"type":"tts_audio","audio":...}`).

**Barge-in (interrupt)**: when the user starts speaking while the AI is playing TTS, the frontend sends `{"type":"interrupt","call_id"}`. `conversation_manager.interrupt(call_id)` bumps the call's `tts_epoch`; queue items record their epoch at enqueue, and `process_tts_queue` discards any item whose epoch no longer matches (both before and after synthesis — Edge TTS can't be cancelled mid-synthesis, so the result is dropped instead). A new `text_message` also bumps the epoch, so leftover TTS from the previous turn is auto-discarded.

`funcation/voice_service.py`: TTS service with pluggable providers (Edge TTS default, Coqui optional). Uses `edge-tts` package for free Chinese speech synthesis. Configurable voice, rate, pitch, volume.

### Prompt Assembly

`funcation/prompt.py` builds the full system prompt from ~12 data sources. The prompt sections (in order):
1. World context (name + background)
2. Character info (name, description, personality)
3. Relationship status (attitude based on favorability thresholds: <20/50/80)
4. Relationship level + last change reason
5. Current story (title, description, current stage)
6. Character state (mood, energy, current event)
7. User profile summary
8. Memory summary (recent chat, long-term memory, key events, chat summaries)
9. Story history (last 5 story items)
10. **RAG retrieved memories** (semantically relevant context from ChromaDB)
11. **NPC social context** (other characters' states and recent interactions)
12. **World events** (active world events affecting the scene)
13. Mood-driven behavior instructions (开心/低落/疲惫/生气)
14. 18 rules (stay in character, 2-5 sentences per reply, etc.)

### World Event System

`funcation/world_event_agent.py`: Manages a world-level event timeline. Events have title, description, importance, progress (0-100), status (running/finished/paused), and character impacts. The `tick()` function advances world time, progresses events, auto-generates new events via DeepSeek, applies impacts to characters, and can trigger story generation from completed events.

`funcation/interaction_agent.py`: Manages NPC-to-NPC relationships and interactions within a world. Tracks relationship scores between all character pairs, records interaction history, generates gossip, and can simulate multi-character interactions driven by world events.

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

**Creating characters at runtime**: `POST /character/create` lets the frontend create a new character from a free-text keyword. `character_agent.generate_character(keyword)` calls DeepSeek (temp=0.9, `response_format=json_object`) to produce `name`/`description`/`personality`/`system_prompt`; the caller passes an optional `name` to override. The endpoint generates an ASCII id `char_{uuid4().hex[:8]}` (collides-checked against existing ids) so Chinese names never become filenames on Windows, then `MemoryCenter.save_character()` writes `data/characters/{id}.json`. The per-character memory file `data/memories/{id}.json` is **not** created eagerly — `load_memory()` auto-creates it on the first `/chat` for that character.

### World Files

World definitions in `data/worlds/{id}.json` provide setting context. Known worlds:
- `campus` (校园): university daily life
- `cyberpunk` (赛博朋克): neon-lit corporate dystopia 2099

Worlds now have dynamic runtime state (`data/worlds/{id}_state.json`) tracking current events, history events, and environmental state.

## Important Patterns

- **Lazy imports for agents**: `MemoryCenter` methods use `from funcation import X` inside method bodies (not at module top) to avoid circular imports.
- **File I/O per call**: Each `MemoryCenter` method does its own load-modify-save cycle. There's no in-memory caching or batching. For a single-user app this is fine.
- **Layered degradation in `/chat`**: The `/chat` endpoint wraps each step in a `_safe(label, fn, default)` helper. **Critical path** (character/messages/mem load with fallbacks, `build_system_prompt`, DeepSeek main reply via `retry_sync`, save history, `memory_agent` extraction) failures return `{"error": "..."}` with HTTP 200. **Non-critical agents** (`world_event_agent.tick`, `story_agent`, recall+RAG retrieval, `interaction_agent`, `update_profile`, `relationship_agent`, `state_agent`, `_sync_*_to_rag`) failures are caught, logged via `logger.warning("[chat] <label> 降级跳过: ...")`, and skipped — the main reply still goes through. An outer `try/except` catches anything unexpected so the endpoint never returns a bare 500.
- **`response_format={"type": "json_object"}`**: Used by `memory_agent` and `profile_agent` to force structured JSON from DeepSeek. `relationship_agent` and `story_agent` use plain text + manual JSON parsing with `json.loads()`.
- **Directory name**: The package is `funcation` (not `function`). This is intentional — all imports use this spelling.
- **No `__init__.py`**: The `funcation/` directory has no init file. Imports use `from funcation import module_name`. Exception: `funcation/proactive/` has an `__init__.py`.
- **Fallback paths**: `MemoryCenter.load_character_by_id()` and `load_world_by_id()` try `data/` first, then fall back to old root-level directories.
- **RAG sync is eager**: Every `/chat` call syncs profile, story, and relationship to ChromaDB via `_sync_*_to_rag()` helper functions. This keeps vectors fresh but adds latency.
- **ChromaDB auto-recovery**: `memory_rag._get_client()` / `_get_collection()` detect a corrupted persistent store (e.g. `ValueError: Could not connect to tenant default_tenant`, or `file is not a database`) and **auto-quarantine + rebuild** instead of throwing 500. The corrupt `data/chroma/` is moved to `data/chroma_corrupt_<timestamp>/` (kept for forensics), a fresh empty DB is created, and the request proceeds. Per-process `_auto_rebuilt` flag prevents infinite rebuild loops; profile/story/relationship re-sync from JSON on the next `/chat`, but `long_memory`/`events`/`chat_summary` (vector-only) are lost.
- **WebSocket singleton pattern**: `conversation_manager` and `webrtc_agent` are module-level singletons imported directly by `api/websocket.py`.
- **TTS is async-queued and fully wired**: `conversation_manager` puts TTS requests on an `asyncio.Queue`; the `process_tts_queue` background coroutine (started in `api.py` lifespan) synthesizes audio via `voice_service` (Edge TTS) and pushes base64 WAV back to the frontend over the call's WebSocket as `{"type":"tts_audio","audio":...}`. The frontend `playTtsAudio()` decodes and plays it. **The `edge-tts` package must be `pip install`ed** (it is in `requirements.txt` but not auto-installed); if missing, `process_tts_queue` logs `No module named 'edge_tts'` per message and no `tts_audio` ever reaches the frontend — the text reply still works, but the user hears nothing. Same caveat applies to `aiortc` (WebRTC).
- **Environment**: `.env` file must contain `DEEPSEEK_API_KEY`. Optional: `TAVILY_API_KEY`, `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`.
