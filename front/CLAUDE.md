# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Vue 3 + TypeScript frontend for an AI character chat interface. Connects to a Python FastAPI backend at `http://127.0.0.1:8000` for AI-powered conversations, and `ws://<host>/voice/call` for real-time voice calls via WebRTC.

## Development Commands

```bash
npm install          # Install dependencies
npm run dev          # Start dev server (hot reload)
npm run build        # Build for production (type-check + build)
npm run preview      # Preview production build
npm run type-check   # Type check with vue-tsc

# Linting & formatting
npm run lint         # Run all linters (oxlint + eslint)
npm run format       # Format code with Prettier

# Testing
npm run test:unit    # Run unit tests with Vitest
npm run test:e2e     # Run E2E tests with Playwright
npm run test:e2e -- --project=chromium  # Single browser
npm run test:e2e -- tests/example.spec.ts  # Single test file
npm run test:e2e -- --debug  # Debug mode
```

## Architecture

### App Structure

```
src/
├── App.vue                    # Root component with nav
├── main.ts                    # Entry point (creates app, pinia, router)
├── router/index.ts            # Vue Router (history mode: /, /chat, /characters, /memory, /about)
├── stores/
│   ├── chatStore.ts           # Chat state: messages, favorability, character, events
│   ├── voiceCallStore.ts      # Voice call state: WebRTC connection, audio levels
│   └── counter.ts             # Example store (unused in production)
├── views/
│   ├── Chat.vue               # Main chat interface (3-column: character, chat, memory)
│   ├── CharactersView.vue     # Character management page (card grid + create-character modal)
│   ├── MemoryView.vue         # Memory center: stats + semantic search + overview + tabbed CRUD
│   ├── HomeView.vue           # Landing page
│   └── AboutView.vue          # "世界与设置" page (world switch, avatar, NPC relations, system tools). NOTE: profile/story/memory/events/chat-summary management moved to MemoryView — AboutView no longer duplicates them.
├── api/
│   ├── request.ts             # Centralized fetch wrapper (base URL, error handling)
│   ├── chat.ts                # POST /chat
│   ├── character.ts           # Character CRUD, avatar upload
│   ├── profile.ts             # User profile endpoints
│   ├── memory.ts              # Memory management endpoints
│   ├── world.ts               # World endpoints (list, switch, interactions)
│   └── index.ts               # Re-exports all API modules
├── services/
│   ├── chatService.ts         # Chat initialization (parallel-fetches state on mount)
│   └── webrtcService.ts       # WebRTC service (peer connection, WebSocket signaling)
├── types/api.ts               # All TypeScript interfaces (Character, World, Story, etc.)
├── utils/character.ts         # Character gradient/avatar helpers
└── components/
    ├── VoiceCallButton.vue    # Floating voice call button
    ├── VoiceCallModal.vue     # Voice call modal with controls
    └── __tests__/             # Component unit tests
```

### Key Architecture Patterns

**API layer** (`src/api/request.ts`): All HTTP calls go through a single `request<T>()` function that prepends `http://127.0.0.1:8000`, sets JSON headers, and handles errors centrally. Each API module returns typed promises using interfaces from `types/api.ts`.

**State management**: Pinia stores with Options API style (`chatStore`) and Composition API style (`voiceCallStore`). The `chatStore` is the primary store — it holds messages, character info, favorability, relationship, character state, events, long memory, and available characters. The `voiceCallStore` manages WebRTC connection state, audio levels, mute/speaker toggles, and call duration tracking.

**Initialization flow** (`Chat.vue` onMounted → `chatService.initChatService()`):
1. Parallel-fetches: history, memory, favorability, character name, character list
2. Parallel-fetches: current character detail, character state, relationship, long memory, events
3. Populates `chatStore` with all fetched data
4. After sending a message: re-fetches character state, relationship, long memory, events. **On failure**: the user message stays in the list with a `failed` flag and a "点击重试" button below it; `store.error` drives a global error bar; `store.retry()` re-sends `lastFailedMessage`. The backend returns `{error}` (HTTP 200) on critical-path failure, which `send()` treats as failure (no assistant reply pushed).

**Voice call system**: Two-component architecture — `VoiceCallButton.vue` (floating trigger) and `VoiceCallModal.vue` (full modal with controls). Uses `webrtcService.ts` which wraps `RTCPeerConnection` + `WebSocket` to the backend's `/voice/call` endpoint. The signaling protocol uses JSON messages with types: `offer`, `answer`, `ice_candidate`, `start_conversation`, `audio_data`, `text_message`, `end_call`, `ping`, `interrupt`, plus inbound `tts_audio` (base64 WAV from the backend, decoded + played by `playTtsAudio()`). Browser-side speech recognition (`webkitSpeechRecognition`, zh-CN) transcribes the mic and sends results as `text_message`; the backend runs the full `/chat` agent flow and returns the reply + synthesized speech. `voiceCallStore.toggleMute()` / `toggleSpeaker()` are fully wired: mute toggles `localStream` audio-track `enabled`; speaker controls whether `playTtsAudio` plays (checked at playback start). `networkQuality` is estimated from `connectionState` + `audioLevel` (not random).

**Barge-in (auto interrupt)**: `webrtcService` analyzes the **localStream** (user mic) separately from the remote stream via `setupMicLevelAnalysis` → `onMicLevelChange`. `voiceCallStore.checkInterrupt` fires `webrtcService.interrupt()` when mic level exceeds threshold (30) for >300ms **while `isAiSpeaking` is true** — this stops local playback (`stopTtsAudio()`) and sends `interrupt` to the backend. `playTtsAudio` is interruptible: it tracks the current `AudioBufferSourceNode` and stops/replace it on new audio or interrupt. `callPhase` getter (`idle/listening/thinking/speaking`) drives the status indicator and the audio visualizer (follows micLevel while listening, audioLevel while speaking).

#- **`/widget`** — Electron 桌面挂件专用路由（fullscreen，无导航）。由 `DesktopWidget.vue` 渲染 compact/expanded 小窗，复用 `authStore`、`chatStore`、`sendChatStream()` 和 `/proactive`。
- Electron 壳位于 `electron/main.ts` / `electron/preload.ts`：创建透明、无边框、置顶窗口，开发模式加载 `http://127.0.0.1:5173/#/widget`，生产模式加载 `dist/index.html#/widget`。preload 只暴露 `window.widgetApi`（setSize / drag / hide / toggleAlwaysOnTop）。
- 相关脚本：`npm run electron:dev`（Vite + Electron 开发，入口 `dist-electron/main.cjs`）、`npm run electron:build`（构建前端 + 主进程）、`npm run electron:pack`（electron-builder 打包）。需要 devDependencies: `electron`, `electron-builder`, `concurrently`, `wait-on`, `esbuild`。
- `widgetStore.ts` 保存挂件模式、主动冒泡开关、置顶偏好；偏好写入 localStorage。

## Backend Integration

The app communicates with the backend through both HTTP REST and WebSocket:

**HTTP REST endpoints** (all accessed via the api/ layer):
- `POST /chat` — Send message, returns reply + favorability
- `GET /favorability` — Current favorability score
- `GET /profile` / `POST /profile` — User profile
- `GET /history` — Recent 10 messages
- `GET /memory` / `POST /clear-memory` — User message memory
- `GET /characters` — List available characters
- `POST /character/switch` — Switch active character
- `POST /character/create` — Create character from keyword (AI-generated persona); body `{keyword, name?}`, returns `{character}` or `{error}`
- `GET /character/current` — Full character definition
- `POST /character/avatar` — Upload character avatar image
- `GET /character/state` — Character mood/energy/current event
- `GET /relationship` — Relationship level + reason
- `GET /story` — Current story arc info
- `GET /long-memory` — Long-term memory items
- `GET /events` / `POST /events` — Character events
- `GET /worlds` / `POST /world/switch` / `GET /world/current` — World management
- `GET /world` / `GET /world/events` — World events and state
- `GET /world/interactions` — NPC interaction records
- `POST /world/interaction/simulate` — Trigger NPC interaction
- `GET /proactive` — Proactive greeting message
- `GET /proactive-message` / `GET /caring-message` — Cached proactive/caring messages
- `GET /chat-summary` — Chat summary list
- `GET /memory/full` — Full memory data (all dynamic state)
- `GET /memory/search?query=...` — Semantic memory search (RAG)
- `POST /memory/add` / `POST /memory/update` / `POST /memory/delete` — RAG memory CRUD
- `GET /memory/stats` — RAG collection stats
- `GET /memory/full` — Full memory snapshot (profile/favorability/relationship/character_state/story/long_memory/events/chat_summary); drives the `MemoryView` overview + tabs

**WebSocket** (`ws://<host>/voice/call`): Used for real-time voice call signaling. Message types handled: `offer`, `answer`, `ice_candidate`, `start_conversation`, `audio_data`, `text_message`, `get_status`, `conversation_status`, `end_call`, `ping`.

## Configuration

- **Vite**: Vue + Vue JSX plugins, path alias `@` → `./src`, Vue DevTools
- **TypeScript**: Project references, strict mode, separate configs for app/node/vitest
- **Linting**: ESLint (Vue + TS plugins) + Oxlint (fast, used with `--fix`) + Prettier
- **Testing**: Vitest (jsdom) + Playwright (Chromium default)
