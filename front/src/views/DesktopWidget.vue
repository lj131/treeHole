<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { useAuthStore } from '@/stores/authStore'
import { useChatStore } from '@/stores/chatStore'
import { useWidgetStore } from '@/stores/widgetStore'
import { getCharacterAvatarUrl, getCharacterGradient, getCharacterInitial } from '@/utils/character'
import { getProactive } from '@/api'

const PROACTIVE_POLL_INTERVAL_MS = 120_000

const auth = useAuthStore()
const chat = useChatStore()
const widget = useWidgetStore()

const inputText = ref('')
const initializing = ref(false)
const localError = ref<string | null>(null)
const messageListEl = ref<HTMLElement | null>(null)
let proactiveTimer: ReturnType<typeof setInterval> | null = null
let dragging = false

const isExpanded = computed(() => widget.mode === 'expanded')
const character = computed(() => chat.character)
const characterName = computed(() => chat.characterName)
const mood = computed(() => chat.mood)
const energy = computed(() => chat.energy)
const characterGradient = computed(() => getCharacterGradient(character.value?.id || 'widget'))
const visibleMessages = computed(() => chat.displayMessages.slice(-20))
const canChat = computed(() => auth.isLoggedIn && auth.isApproved)

async function initializeWidget() {
  initializing.value = true
  localError.value = null
  try {
    await auth.fetchMe()
    if (auth.isLoggedIn) {
      await chat.refreshAll()
      if (!widget.lastBubble) {
        widget.setBubble(`${characterName.value} 正在这里陪着你。`)
      }
    }
  } catch (e: any) {
    localError.value = e?.message || '挂件初始化失败'
  } finally {
    initializing.value = false
  }
}

function startProactivePolling() {
  stopProactivePolling()
  proactiveTimer = setInterval(() => {
    void pollProactive()
  }, PROACTIVE_POLL_INTERVAL_MS)
  void pollProactive()
}

function stopProactivePolling() {
  if (proactiveTimer) {
    clearInterval(proactiveTimer)
    proactiveTimer = null
  }
}

async function pollProactive() {
  if (!widget.proactiveEnabled || !auth.isLoggedIn || chat.loading) return
  try {
    const res = await getProactive()
    const message = res.message?.trim()
    if (!message) return

    const last = chat.messages[chat.messages.length - 1]
    if (last?.role === 'assistant' && last.content === message) return

    widget.setBubble(message)
    chat.messages.push({ role: 'assistant', content: message })
  } catch {
    // 主动消息失败时静默忽略，避免桌面挂件频繁打扰
  }
}

function toggleMode() {
  widget.toggleMode()
  if (widget.mode === 'expanded') {
    widget.clearBubble()
    void nextTick(scrollToBottom)
  }
}

async function send() {
  const text = inputText.value.trim()
  if (!text || chat.loading || !canChat.value) return
  inputText.value = ''
  widget.clearBubble()
  await chat.send(text)
  await nextTick(scrollToBottom)
}

function scrollToBottom() {
  const el = messageListEl.value
  if (el) el.scrollTop = el.scrollHeight
}

function openAuth() {
  auth.openAuth()
}

function toggleProactive() {
  widget.setProactiveEnabled(!widget.proactiveEnabled)
}

function hideWidget() {
  window.widgetApi?.hide()
}

function onDragStart() {
  dragging = true
  window.widgetApi?.dragStart()
  window.addEventListener('mousemove', onDragMove)
  window.addEventListener('mouseup', onDragEnd)
}

function onDragMove() {
  if (!dragging) return
  window.widgetApi?.dragMove()
}

function onDragEnd() {
  dragging = false
  window.widgetApi?.dragEnd()
  window.removeEventListener('mousemove', onDragMove)
  window.removeEventListener('mouseup', onDragEnd)
}

onMounted(async () => {
  widget.setMode('compact')
  await initializeWidget()
  startProactivePolling()
})

onUnmounted(() => {
  stopProactivePolling()
  onDragEnd()
})
</script>

<template>
  <div class="desktop-widget" :class="{ expanded: isExpanded }">
    <div class="drag-strip" @mousedown.prevent="onDragStart">
      <span class="drag-dots">⋮⋮</span>
      <span class="drag-title">桌面陪伴</span>
      <button class="icon-btn" title="置顶切换" @click.stop="widget.toggleAlwaysOnTop">
        {{ widget.alwaysOnTop ? '📌' : '📍' }}
      </button>
      <button class="icon-btn" title="隐藏" @click.stop="hideWidget">—</button>
    </div>

    <section v-if="!isExpanded" class="compact-card" @click="toggleMode">
      <div class="avatar" :style="{ background: character?.avatar ? 'transparent' : characterGradient }">
        <img v-if="character?.avatar" :src="getCharacterAvatarUrl(character.avatar)" alt="角色头像" />
        <span v-else>{{ getCharacterInitial(character?.name || characterName) }}</span>
        <span class="status-pulse" :class="{ active: canChat }"></span>
      </div>

      <div class="compact-info">
        <div class="name-line">
          <span class="char-name">{{ characterName }}</span>
          <span class="mood-chip">{{ mood }}</span>
        </div>
        <p v-if="initializing" class="bubble muted">正在醒来...</p>
        <p v-else-if="!auth.isLoggedIn" class="bubble">登录后我就能在桌面陪你。</p>
        <p v-else-if="auth.isPending" class="bubble">账号还在审批中，暂时只能看看我。</p>
        <p v-else class="bubble">{{ widget.lastBubble || '点我展开，随时聊两句。' }}</p>
      </div>
    </section>

    <section v-else class="expanded-card">
      <header class="widget-header">
        <div class="avatar small" :style="{ background: character?.avatar ? 'transparent' : characterGradient }">
          <img v-if="character?.avatar" :src="getCharacterAvatarUrl(character.avatar)" alt="角色头像" />
          <span v-else>{{ getCharacterInitial(character?.name || characterName) }}</span>
        </div>
        <div class="header-text">
          <strong>{{ characterName }}</strong>
          <span>{{ mood }} · 精力 {{ energy }}/100</span>
        </div>
        <button class="collapse-btn" @click="toggleMode">收起</button>
      </header>

      <div v-if="!auth.isLoggedIn" class="empty-state">
        <p>登录后启用桌面挂件。</p>
        <button class="primary-btn" @click="openAuth">登录 / 注册</button>
      </div>
      <div v-else-if="!auth.isApproved" class="empty-state">
        <p>账号仍在审批中，暂时不能聊天。</p>
      </div>
      <template v-else>
        <div ref="messageListEl" class="mini-messages">
          <div v-if="visibleMessages.length === 0" class="empty-hint">还没有聊天记录，先打个招呼吧。</div>
          <div
            v-for="(msg, index) in visibleMessages"
            :key="msg.id ?? index"
            class="mini-msg"
            :class="msg.role"
          >
            <span>{{ msg.content || (msg.role === 'assistant' && chat.loading ? '...' : '') }}</span>
          </div>
          <div v-if="chat.loading && !chat.streaming" class="typing">{{ characterName }} 正在想...</div>
        </div>

        <div v-if="chat.error || localError" class="error-line" @click="chat.clearError()">
          {{ chat.error || localError }}
        </div>

        <div class="input-row">
          <input
            v-model="inputText"
            type="text"
            placeholder="和她说点什么..."
            :disabled="chat.loading"
            @keydown.enter.prevent="send"
          />
          <button :disabled="chat.loading || !inputText.trim()" @click="send">
            {{ chat.loading ? '...' : '发送' }}
          </button>
        </div>

        <footer class="widget-footer">
          <button class="text-btn" @click="toggleProactive">
            主动冒泡：{{ widget.proactiveEnabled ? '开' : '关' }}
          </button>
          <button v-if="chat.lastFailedMessage" class="text-btn retry" @click="chat.retry">重试</button>
        </footer>
      </template>
    </section>
  </div>
</template>

<style scoped>
.desktop-widget {
  width: 100vw;
  height: 100vh;
  overflow: hidden;
  color: var(--text-primary);
  user-select: none;
}

.drag-strip {
  height: 28px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 10px;
  border-radius: 16px 16px 0 0;
  background: rgba(15, 15, 35, 0.72);
  border: 1px solid var(--border-color);
  border-bottom: none;
  cursor: move;
  backdrop-filter: blur(16px);
}

.drag-dots {
  letter-spacing: -3px;
  color: var(--text-secondary);
}

.drag-title {
  flex: 1;
  font-size: 12px;
  color: var(--text-secondary);
}

.icon-btn,
.collapse-btn,
.primary-btn,
.text-btn,
.input-row button {
  border: none;
  color: var(--text-primary);
  cursor: pointer;
}

.icon-btn {
  width: 24px;
  height: 22px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.08);
}

.compact-card,
.expanded-card {
  height: calc(100vh - 28px);
  border: 1px solid var(--border-color);
  border-top: none;
  background: rgba(26, 26, 46, 0.86);
  box-shadow: 0 18px 45px rgba(0, 0, 0, 0.35);
  backdrop-filter: blur(22px);
}

.compact-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px;
  border-radius: 0 0 20px 20px;
  cursor: pointer;
}

.avatar {
  position: relative;
  width: 74px;
  height: 74px;
  border-radius: 24px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  font-size: 30px;
  font-weight: 700;
  overflow: hidden;
  box-shadow: 0 10px 28px rgba(102, 126, 234, 0.28);
}

.avatar.small {
  width: 42px;
  height: 42px;
  border-radius: 14px;
  font-size: 18px;
}

.avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.status-pulse {
  position: absolute;
  right: 6px;
  bottom: 6px;
  width: 13px;
  height: 13px;
  border-radius: 50%;
  background: #f59e0b;
  border: 2px solid rgba(26, 26, 46, 0.9);
}

.status-pulse.active {
  background: #10b981;
  box-shadow: 0 0 0 5px rgba(16, 185, 129, 0.18);
}

.compact-info {
  min-width: 0;
  flex: 1;
}

.name-line {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.char-name {
  font-weight: 800;
}

.mood-chip {
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(102, 126, 234, 0.18);
  color: #c7d2fe;
  font-size: 12px;
}

.bubble {
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  line-height: 1.45;
  color: var(--text-secondary);
}

.bubble.muted {
  opacity: 0.75;
}

.expanded-card {
  display: flex;
  flex-direction: column;
  border-radius: 0 0 18px 18px;
}

.widget-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px;
  border-bottom: 1px solid var(--border-color);
}

.header-text {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.header-text span {
  font-size: 12px;
  color: var(--text-secondary);
}

.collapse-btn,
.primary-btn,
.input-row button {
  padding: 8px 12px;
  border-radius: 12px;
  background: linear-gradient(135deg, var(--accent-primary), var(--accent-secondary));
}

.empty-state {
  flex: 1;
  display: grid;
  place-content: center;
  gap: 14px;
  text-align: center;
  color: var(--text-secondary);
}

.mini-messages {
  flex: 1;
  overflow-y: auto;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.empty-hint,
.typing {
  color: var(--text-secondary);
  text-align: center;
  font-size: 13px;
}

.mini-msg {
  max-width: 82%;
  padding: 9px 12px;
  border-radius: 14px;
  line-height: 1.45;
  font-size: 14px;
  user-select: text;
}

.mini-msg.user {
  align-self: flex-end;
  background: linear-gradient(135deg, var(--accent-primary), var(--accent-secondary));
}

.mini-msg.assistant {
  align-self: flex-start;
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid var(--border-color);
}

.error-line {
  margin: 0 12px;
  padding: 8px 10px;
  border-radius: 10px;
  color: #fecaca;
  background: rgba(239, 68, 68, 0.16);
  font-size: 12px;
  cursor: pointer;
}

.input-row {
  display: flex;
  gap: 8px;
  padding: 12px;
  border-top: 1px solid var(--border-color);
}

.input-row input {
  flex: 1;
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-primary);
  outline: none;
}

.input-row button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.widget-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 12px 12px;
}

.text-btn {
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
}

.text-btn.retry {
  color: #fbbf24;
}
</style>
