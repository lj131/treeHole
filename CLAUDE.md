# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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

```
[User types message in Vue Chat.vue]
  → chatStore.send(message)
  → POST /chat {message: "..."}
  → api.py orchestrates ~6 AI agent calls (all DeepSeek):
      1. event_agent: Generate daily event (temp=1)
      2. story_agent: Generate/advance story arc (temp=1)
      3. profile_agent: Extract user profile info (temp=0.3)
      4. relationship_agent: Analyze sentiment → favorability delta (temp=0)
      5. state_agent: Character mood/energy assessment (temp=0)
      6. DeepSeek chat completion (temp=0.9) → AI reply
      7. memory_agent: Extract long-term memory from user msg (temp=0.9)
  → Returns {reply, favorability}
  → Frontend updates chatStore, re-fetches state/relationship/memory
```

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

All secrets are in `backend/.env`: `DEEPSEEK_API_KEY` and `TAVILY_API_KEY`. The file is NOT gitignored (currently present in the working tree). Do not commit secrets to either repo.

### Known Issues

- `/chat` uses **layered degradation** — see `backend/CLAUDE.md` for the `_safe` helper detail.
- `backend/api接口文档.md` documents endpoints that no longer exist in actual code — see `api.py` for the real list.
- `MemoryCenter` uses lazy imports to avoid circular imports.
- Frontend API URL is **not hardcoded** — it's configured via `VITE_API_BASE` / `VITE_WS_BASE` (default `http://127.0.0.1:8000`). Docker deploys set `VITE_API_BASE=/api` for nginx reverse proxy.
- `.env` is gitignored; use `.env.example` as template.

### Git & CI/CD
- Single root-level repo (backend/front inner `.git` dirs backed up to `.git.backup`).
- GitHub Actions: `.github/workflows/deploy.yml` builds both images, verifies backend starts, deploys via SSH.
- Docker Compose: `docker compose up -d` with nginx (80) proxying `/api/*`→backend, `/voice/*`→backend WS, `/`→frontend SPA.

### Auth System
- **JWT-based auth**: SQLite (SQLAlchemy) user store, PyJWT tokens, bcrypt password hashing.
- **Roles**: admin (default: admin/admin123), user (pending→approved).
- **Permissions**: unauthenticated → login/register only; pending → read-only (browse, no chat/create); approved → full access; admin → full + user approval.
- Backend: `funcation/auth.py` (User model + JWT + FastAPI Depends), `api/auth.py` (routes). Read endpoints open, write endpoints require `require_approved`.
- Frontend: `authStore` (Pinia), `AuthModal` (login/register popup), `request.ts` auto-attaches Bearer token. Pending users see disabled inputs / hidden action buttons.
- 3rd-party OAuth fields reserved: `oauth_provider`, `oauth_id` on User model.
