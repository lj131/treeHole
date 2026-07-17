# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with this repository.

## Project Overview

Vue 3 + TypeScript frontend for an AI character chat interface. Connects to a Python FastAPI backend at `http://127.0.0.1:8000` (dev) or `/api` (Docker) for AI-powered conversations, and `ws://<host>/voice/call` for real-time voice calls via WebRTC.

## Development Commands

```bash
npm install          # Install dependencies
npm run dev          # Start dev server (hot reload)
npm run build        # Build for production (type-check + build)
npm run build-only   # Build without type-check (for CI)
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

# Electron 桌面挂件 (D3)
npm run electron:dev    # 启动 Vite + Electron 开发
npm run electron:build  # 构建前端 + Electron 主进程
npm run electron:pack   # electron-builder 打包 Windows 安装包
```

## Architecture

### App Structure

```
src/
├── App.vue                    # Root component with nav
├── main.ts                    # Entry point (creates app, pinia, router)
├── router/index.ts            # Vue Router (hash mode: /, /chat, /characters, /memory, /settings, /widget, /admin)
├── stores/
│   ├── authStore.ts           # 认证状态
│   ├── chatStore.ts           # Chat state: messages, favorability, character, events
│   ├── widgetStore.ts         # Electron 挂件状态
│   └── counter.ts             # Example store (unused in production)
├── views/
│   ├── Chat.vue               # Main chat interface (3-column: character, chat, memory)
│   ├── CharactersView.vue     # Character management page (card grid + create-character modal)
│   ├── MemoryView.vue         # Memory center: stats + semantic search + overview + tabbed CRUD
│   ├── StoryView.vue           # 剧情可视化页（/story 路由）
│   ├── SettingsView.vue       # Settings page
│   ├── DesktopWidget.vue      # Electron 桌面挂件 (compact/expanded 模式)
│   ├── AdminView.vue          # Admin management panel
│   ├── HomeView.vue           # Landing page
│   └── AboutView.vue          # "世界与设置" page (world switch, avatar, NPC relations)
├── api/
│   ├── request.ts             # Centralized fetch wrapper (base URL, error handling)
│   ├── chat.ts                # POST /chat/stream (SSE)
│   ├── character.ts           # Character CRUD, avatar upload
│   ├── profile.ts             # User profile endpoints
│   ├── memory.ts              # Memory management endpoints
│   ├── story.ts                # GET /story、POST /story/advance
│   ├── world.ts               # World endpoints (list, switch, interactions)
│   └── index.ts               # Re-exports all API modules
├── services/
│   ├── chatService.ts         # Chat initialization (parallel-fetches state on mount)
│   └── webrtcService.ts       # WebRTC service (peer connection, WebSocket signaling)
├── types/api.ts               # All TypeScript interfaces (Character, World, Story, etc.)
├── utils/character.ts         # Character gradient/avatar helpers
├── utils/notification.ts      # 桌面通知
└── components/
    ├── AuthModal.vue          # 登录/注册模态框
    ├── VoiceCallButton.vue    # Floating voice call button
    ├── VoiceCallModal.vue     # Voice call modal with controls
    ├── StoryTree.vue          # 单剧情树状图组件（主线脊柱+分支侧枝）
    └── icons/                 # SVG 图标
electron/
├── main.ts                    # Electron 主进程
└── preload.ts                 # 暴露 widgetApi 到 renderer
dist-electron/                 # 构建后的 Electron 代码
```

### Key Architecture Patterns

**API layer** (`src/api/request.ts`): All HTTP calls go through a single `request<T>()` function that prepends `import.meta.env.VITE_API_BASE`, sets JSON headers, and handles errors centrally. Each API module returns typed promises using interfaces from `types/api.ts`.`authStore` 自动注入 `Authorization: Bearer {token}`。

**State management**: Pinia stores with Options API style (`chatStore`, `authStore`) and Composition API style (`widgetStore`)。`chatStore` 是主 store：messages, character info, favorability, relationship, character state, events, long memory, available characters。`authStore` 管理登录状态、用户信息、pending 状态。`widgetStore` 管理挂件模式、主动冒泡开关、置顶偏好（localStorage）。

**Initialization flow** (`Chat.vue` onMounted → `chatService.initChatService()`):
1. 并发拉取：history, memory, favorability, character name, character list
2. 并发拉取：current character detail, character state, relationship, long memory, events
3. 填充 `chatStore` 所有状态
4. 发送消息后：并发拉取 character state, relationship, long memory, events。**失败处理**：用户消息保留带 `failed` 标志，显示"点击重试"按钮；`store.error` 驱动全局错误栏；`store.retry()` 重发 `lastFailedMessage`。后端返回 `{error}` (HTTP 200) 时，`send()` 视为失败（不推 assistant 回复）。

**Voice call system**: 两组件架构 — `VoiceCallButton.vue` (悬浮触发器) 和 `VoiceCallModal.vue` (全屏模态框 + 控制器)。使用 `webrtcService.ts` 封装 `RTCPeerConnection` + WebSocket 连接后端 `/voice/call`。信令协议用 JSON：`offer`, `answer`, `ice_candidate`, `start_conversation`, `audio_data`, `text_message`, `end_call`, `ping`, `interrupt`，入站还有 `tts_audio`（后端 base64 WAV，前端 decode + `playTtsAudio()`）。浏览器语音识别（`webkitSpeechRecognition`, zh-CN）转录麦克风并发送为 `text_message`；后端跑完整 `/chat` agent 流并返回回复 + 语音合成。`voiceCallStore.toggleMute()` / `toggleSpeaker()` 完全接入：mute 切换 `localStream` audio-track `enabled`；speaker 控制 `playTtsAudio` 是否播放（播放开始时检查）。`networkQuality` 从 `connectionState` + `audioLevel` 估算（非随机）。

**Barge-in (自动打断)**: `webrtcService` 分析 **localStream** (用户麦克风) 独立于远程流，通过 `setupMicLevelAnalysis` → `onMicLevelChange`。`voiceCallStore.checkInterrupt` 在 `isAiSpeaking` 为 true 且麦克风音量超过阈值 (30) 持续 >300ms 时触发 `webrtcService.interrupt()` — 停止本地播放 (`stopTtsAudio()`) 并向后端发送 `interrupt`。`playTtsAudio` 可中断：追踪当前 `AudioBufferSourceNode`，在新音频或 interrupt 时 stop/replace。`callPhase` getter (`idle/listening/thinking/speaking`) 驱动状态指示器和音频可视化器（listening 跟随 micLevel，speaking 跟随 audioLevel）。

### Electron 桌面挂件 (D3)

**路由**：`/widget` 是挂件专用路由（fullscreen，无导航栏），由 `DesktopWidget.vue` 渲染。

**UI 模式**：
- `compact` — 紧凑气泡模式（头像 + 点击展开）
- `expanded` — 迷你聊天窗（收发消息）

**数据复用**：
- 复用 `authStore`、`chatStore`
- 复用 `/chat/stream` SSE 流
- 复用 `/proactive` 主动问候

**Electron 壳**：
- `electron/main.ts`：透明、无边框、置顶窗口；dev 模式加载 `http://127.0.0.1:5173/#/widget`，prod 模式加载 `dist/index.html#/widget`
- `electron/preload.ts`：通过 `contextBridge` 暴露 `window.widgetApi`（`setSize` / `drag` / `hide` / `toggleAlwaysOnTop`）

**持久化**：`widgetStore` 写入 localStorage（mode, proactiveEnabled, alwaysOnTop）。

**构建**：
- `npm run electron:dev` — Vite dev + Electron 同时启动（入口 `dist-electron/main.cjs`）
- `npm run electron:build` — 构建前端 + esbuild 编译 Electron 主进程
- `npm run electron:pack` — electron-builder 打包 Windows exe

### 前端移动端适配

`Chat.vue` 在 `<900px` 时隐藏左右侧栏，改为底部 Tab 栏：
- 💬 聊天 (/chat)
- 🎭 角色 (切换角色)
- 💖 好感 (好感度展示)
- 🧠 记忆 (记忆查看)

点击 Tab 展开对应抽屉面板（从底部滑入）。切换角色、查看好感度和记忆无需宽屏。

### 类型定义 (`types/api.ts`)

完整的 API 类型定义：
- `Character`, `CharacterBrief`, `CharacterState`
- `User`, `UsageSummary`
- `Story`, `StoryHistoryItem`, `StoryBranchPoint`
- `World`, `WorldInteractionsSnapshot`
- `FullMemory`, `UserProfile`, `EventItem`
- `ChatMessage`, `Relationship`

## Backend Integration

The app communicates with the backend through both HTTP REST and WebSocket:

**HTTP REST endpoints** (all accessed via the api/ layer):
- `POST /chat/stream` — 发送消息（SSE 流式）
- `GET /favorability` — Current favorability score
- `GET /profile` / `POST /profile` — User profile
- `GET /history` — Recent 10 messages
- `GET /memory` / `POST /clear-memory` — User message memory (legacy)
- `GET /characters` — List available characters
- `POST /character/switch` — Switch active character
- `POST /character/create` — Create character from keyword (AI-generated persona); body `{keyword, name?}`, returns `{character}` or `{error}`
- `GET /character/current` — Full character definition
- `POST /character/avatar` — Upload character avatar image
- `GET /character/state` — Character mood/energy/current event
- `GET /relationship` — Relationship level + reason
- `GET /story` — Current story arc info (多剧情)
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

**WebSocket** (`ws://<host>/voice/call`): Used for real-time voice call signaling. Message types handled: `offer`, `answer`, `ice_candidate`, `start_conversation`, `audio_data`, `text_message`, `get_status`, `conversation_status`, `end_call`, `ping`, `interrupt`。

## Configuration

- **Vite**: Vue + Vue JSX plugins, path alias `@` → `./src`, Vue DevTools
- **TypeScript**: Project references, strict mode, separate configs for app/node/vitest
- **Linting**: ESLint (Vue + TS plugins) + Oxlint (fast, used with `--fix`) + Prettier
- **Testing**: Vitest (jsdom) + Playwright (Chromium default)

### 环境变量 (构建时)

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `VITE_API_BASE` | `http://127.0.0.1:8000` | 后端 API 地址（Docker 部署设为 `/api`） |
| `VITE_WS_BASE` | - | WebSocket 地址（留空则用 `VITE_API_BASE` 替换） |

### 路由配置

```typescript
routes: [
  { path: "/", component: HomeView },
  { path: "/chat", component: Chat, meta: { fullscreen: true } },
  { path: "/characters", component: CharactersView },
  { path: "/memory", component: MemoryView },
  { path: "/story", component: StoryView, meta: { title: "剧情" } },
  { path: "/settings", component: SettingsView },
  { path: "/widget", component: DesktopWidget, meta: { fullscreen: true } },
  { path: "/admin", component: AdminView, meta: { adminOnly: true } },
  { path: "/about", component: AboutView }
]
```

使用 **hash history** (`createWebHashHistory`)，保证 Electron file:// 打包后路由可用。

## Known Issues

- E2E 测试仅覆盖 Chromium
- 移动端适配：Chat.vue 在窄屏时隐藏侧栏，改用底部 Tab 栏
- 桌面挂件：首次构建 Electron 可能需要手动下载依赖（electron-builder）