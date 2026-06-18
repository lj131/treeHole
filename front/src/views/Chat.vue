<template>
  <div class="chat-page">
    <!-- 背景装饰 -->
    <div class="bg-orbs">
      <div class="orb orb-1"></div>
      <div class="orb orb-2"></div>
      <div class="orb orb-3"></div>
    </div>

    <div class="chat-layout">
      <!-- 左侧：角色卡 -->
      <aside class="panel left-panel">
        <div class="glass-card character-card">
          <div
            class="portrait"
            :style="{ background: characterAvatar ? 'transparent' : characterGradient }"
          >
            <img
              v-if="characterAvatar"
              :src="characterAvatar"
              class="portrait-img"
              alt="角色头像"
            />
            <span v-else class="portrait-initial">{{ characterInitial }}</span>
            <div class="portrait-glow"></div>
          </div>

          <div class="char-info">
            <h2 class="char-name">{{ store.characterName }}</h2>
            <p class="char-personality">
              <span class="personality-badge">{{ store.character?.personality || '神秘' }}</span>
            </p>
            <p class="char-desc">{{ store.character?.description || '等待与你相遇...' }}</p>
          </div>

          <!-- 角色状态 -->
          <div class="status-grid">
            <div class="status-item">
              <span class="status-label">心情</span>
              <span class="status-value">
                {{ getMoodEmoji(store.mood) }} {{ store.mood }}
              </span>
            </div>
            <div class="status-item">
              <span class="status-label">精力</span>
              <div class="energy-bar">
                <div
                  class="energy-fill"
                  :style="{
                    width: store.energy + '%',
                    background: getEnergyColor(store.energy),
                  }"
                ></div>
              </div>
              <span class="energy-num">{{ store.energy }}%</span>
            </div>
            <div v-if="store.characterState.current_event" class="status-item full">
              <span class="status-label">当前事件</span>
              <span class="status-value event">{{ store.characterState.current_event }}</span>
            </div>
          </div>
        </div>

        <!-- 角色切换 -->
        <div class="glass-card switch-card">
          <h3 class="section-title">
            <span class="title-icon">🎭</span> 切换角色
          </h3>
          <div class="char-list">
            <button
              v-for="char in store.availableCharacters"
              :key="char.id"
              class="char-btn"
              :class="{ active: store.currentCharacterId === char.id }"
              :disabled="store.switching"
              @click="handleSwitch(char.id)"
            >
              <span
                class="char-avatar-mini"
                :style="{ background: char.avatar ? 'transparent' : getCharacterGradient(char.id) }"
              >
                <img v-if="char.avatar" :src="getCharacterAvatarUrl(char.avatar)" class="avatar-img" alt="" />
                <span v-else>{{ getCharacterInitial(char.name) }}</span>
              </span>
              <div class="char-btn-info">
                <span class="char-btn-name">{{ char.name }}</span>
                <span class="char-btn-desc">{{ char.description }}</span>
              </div>
            </button>
          </div>
          <div v-if="store.switching" class="switching-hint">切换中...</div>
        </div>

        <router-link to="/about" class="settings-link glass-card">
          <span>⚙️</span> 高级设置
        </router-link>
      </aside>

      <!-- 中间：聊天区 -->
      <main class="panel chat-panel">
        <header class="chat-header glass-card">
          <div class="header-left">
            <span
              class="header-avatar"
              :style="{ background: characterAvatar ? 'transparent' : characterGradient }"
            >
              <img v-if="characterAvatar" :src="characterAvatar" class="avatar-img" alt="" />
              <span v-else>{{ characterInitial }}</span>
            </span>
            <div>
              <h1>{{ store.characterName }}</h1>
              <p class="header-sub">
                {{ headerSub }}
              </p>
            </div>
          </div>
          <div class="header-right">
            <span class="online-pulse"></span>
            <VoiceCallButton />
          </div>
        </header>

        <section class="message-area" :class="{ 'mobile-hidden': mobileTab !== 'chat' }" ref="messageAreaRef">
          <div v-if="store.error" class="chat-error-bar">
            <span class="error-text">{{ store.error }}</span>
            <button
              v-if="store.lastFailedMessage"
              class="error-retry"
              :disabled="store.loading"
              @click="store.retry()"
            >重试</button>
            <button class="error-close" @click="store.clearError()">×</button>
          </div>

          <div v-if="store.displayMessages.length === 0" class="empty-chat">
            <div class="empty-icon">💬</div>
            <p>开始与 {{ store.characterName }} 对话吧</p>
            <p class="empty-hint">她会记住你说的每一句话</p>
          </div>

          <div
            v-for="(msg, i) in store.displayMessages"
            :key="i"
            v-show="msg.role === 'user' || msg.content || !store.loading"
            class="msg-row"
            :class="msg.role"
          >
            <span
              v-if="msg.role === 'assistant'"
              class="msg-avatar"
              :style="{ background: characterAvatar ? 'transparent' : characterGradient }"
            >
              <img v-if="characterAvatar" :src="characterAvatar" class="avatar-img" alt="" />
              <span v-else>{{ characterInitial }}</span>
            </span>

            <div class="bubble-wrap">
              <div class="bubble" :class="{ 'bubble-failed': msg.failed }">{{ msg.content }}</div>
              <span class="bubble-time">{{ msg.role === 'user' ? '你' : store.characterName }}</span>
              <button
                v-if="msg.failed"
                class="retry-btn"
                :disabled="store.loading"
                @click="store.retry()"
              >
                ⚠ 发送失败 · 点击重试
              </button>
            </div>

            <span
              v-if="msg.role === 'user'"
              class="msg-avatar user-avatar"
            >我</span>
          </div>

          <div v-if="store.loading && !store.streaming" class="msg-row assistant">
            <span
              class="msg-avatar"
              :style="{ background: characterAvatar ? 'transparent' : characterGradient }"
            >
              <img v-if="characterAvatar" :src="characterAvatar" class="avatar-img" alt="" />
              <span v-else>{{ characterInitial }}</span>
            </span>
            <div class="bubble typing-bubble">
              <span class="dot"></span>
              <span class="dot"></span>
              <span class="dot"></span>
            </div>
          </div>

          <div ref="scrollAnchor" class="scroll-anchor"></div>
        </section>

        <!-- 移动端抽屉面板（角色 / 好感 / 记忆） -->
        <section v-if="mobileTab === 'character'" class="mobile-drawer">
          <div class="mobile-drawer-inner">
            <div class="mobile-char-portrait"
              :style="{ background: characterAvatar ? 'transparent' : characterGradient }">
              <img v-if="characterAvatar" :src="characterAvatar" class="portrait-img" alt="" />
              <span v-else class="portrait-initial">{{ characterInitial }}</span>
            </div>
            <h3 class="mobile-char-name">{{ store.characterName }}</h3>
            <p class="mobile-char-desc">{{ store.character?.description || '' }}</p>
            <div class="mobile-char-list">
              <button
                v-for="char in store.availableCharacters"
                :key="char.id"
                class="char-btn"
                :class="{ active: store.currentCharacterId === char.id }"
                :disabled="store.switching"
                @click="handleSwitch(char.id)"
              >
                <span class="char-avatar-mini"
                  :style="{ background: char.avatar ? 'transparent' : getCharacterGradient(char.id) }">
                  <img v-if="char.avatar" :src="getCharacterAvatarUrl(char.avatar)" class="avatar-img" alt="" />
                  <span v-else>{{ getCharacterInitial(char.name) }}</span>
                </span>
                <div class="char-btn-info">
                  <span class="char-btn-name">{{ char.name }}</span>
                  <span class="char-btn-desc">{{ char.description }}</span>
                </div>
              </button>
            </div>
          </div>
        </section>

        <section v-if="mobileTab === 'favor'" class="mobile-drawer">
          <div class="mobile-drawer-inner mobile-favor">
            <div class="favor-ring-wrap">
              <svg class="favor-ring" viewBox="0 0 120 120">
                <circle cx="60" cy="60" r="52" class="ring-bg" />
                <circle cx="60" cy="60" r="52" class="ring-fill"
                  :style="{ strokeDashoffset: ringOffset }" />
              </svg>
              <div class="favor-center">
                <span class="favor-num">{{ store.favorability }}</span>
                <span class="favor-unit">/ 100</span>
              </div>
            </div>
            <div class="favor-level">{{ store.favorLevel }}</div>
            <div class="rel-info">
              <span class="rel-label">关系</span>
              <span class="rel-value">{{ store.relationship.level || '未知' }}</span>
            </div>
            <p v-if="store.relationship.last_reason" class="rel-reason">
              {{ store.relationship.last_reason }}
            </p>
          </div>
        </section>

        <section v-if="mobileTab === 'memory'" class="mobile-drawer">
          <div class="mobile-drawer-inner">
            <h3 class="mobile-section-title">🧠 她记得你</h3>
            <div class="mobile-memory-list">
              <div v-for="(item, idx) in store.longMemory" :key="idx" class="memory-item">
                <span class="memory-dot"></span>{{ item }}
              </div>
              <div v-if="store.longMemory.length === 0" class="memory-empty">
                还没有形成长期记忆
              </div>
            </div>
            <h3 class="mobile-section-title" style="margin-top:20px">📅 近期事件</h3>
            <div class="mobile-memory-list">
              <div v-for="(evt, idx) in recentEvents" :key="idx" class="event-item">
                <span class="event-time">{{ evt.time }}</span>
                <span class="event-text">{{ evt.event }}</span>
              </div>
              <div v-if="recentEvents.length === 0" class="memory-empty">
                暂无事件记录
              </div>
            </div>
          </div>
        </section>

        <footer class="input-area glass-card" :class="{ 'mobile-hidden': mobileTab !== 'chat' }">
          <template v-if="auth.isPending">
            <p class="pending-notice">⏳ 您的账号正在等待管理员审批，审批通过后即可对话</p>
          </template>
          <template v-else>
            <textarea
              v-model="input"
              placeholder="输入消息... (Enter 发送, Shift+Enter 换行)"
              rows="1"
              :disabled="store.loading"
              @keydown="onKeydown"
            />
            <button
              class="send-btn"
              :disabled="!input.trim() || store.loading"
              @click="send"
            >
              <span v-if="store.loading" class="send-loading"></span>
              <span v-else>发送</span>
            </button>
          </template>
        </footer>

        <!-- 移动端底部 Tab 栏 -->
        <nav class="mobile-tab-bar">
          <button
            v-for="tab in mobileTabs"
            :key="tab.key"
            class="mobile-tab"
            :class="{ active: mobileTab === tab.key }"
            @click="mobileTab = tab.key"
          >
            <span class="tab-icon">{{ tab.icon }}</span>
            <span class="tab-label">{{ tab.label }}</span>
          </button>
        </nav>
      </main>

      <!-- 右侧：记忆与好感度 -->
      <aside class="panel right-panel">
        <!-- 好感度 -->
        <div class="glass-card favor-card">
          <h3 class="section-title">
            <span class="title-icon">💖</span> 好感度
          </h3>
          <div class="favor-ring-wrap">
            <svg class="favor-ring" viewBox="0 0 120 120">
              <circle cx="60" cy="60" r="52" class="ring-bg" />
              <circle
                cx="60"
                cy="60"
                r="52"
                class="ring-fill"
                :style="{ strokeDashoffset: ringOffset }"
              />
            </svg>
            <div class="favor-center">
              <span class="favor-num">{{ store.favorability }}</span>
              <span class="favor-unit">/ 100</span>
            </div>
          </div>
          <div class="favor-level">{{ store.favorLevel }}</div>
          <div class="rel-info">
            <span class="rel-label">关系</span>
            <span class="rel-value">{{ store.relationship.level || '未知' }}</span>
          </div>
          <p v-if="store.relationship.last_reason" class="rel-reason">
            {{ store.relationship.last_reason }}
          </p>
        </div>

        <!-- 长期记忆 -->
        <div class="glass-card memory-card">
          <h3 class="section-title">
            <span class="title-icon">🧠</span> 她记得你
            <router-link to="/memory" class="view-all-link">查看全部 →</router-link>
          </h3>
          <div class="memory-list">
            <div
              v-for="(item, idx) in store.longMemory"
              :key="idx"
              class="memory-item"
            >
              <span class="memory-dot"></span>
              {{ item }}
            </div>
            <div v-if="store.longMemory.length === 0" class="memory-empty">
              还没有形成长期记忆
            </div>
          </div>
        </div>

        <!-- 近期事件 -->
        <div class="glass-card events-card">
          <h3 class="section-title">
            <span class="title-icon">📅</span> 近期事件
            <router-link to="/memory" class="view-all-link">查看全部 →</router-link>
          </h3>
          <div class="events-list">
            <div
              v-for="(evt, idx) in recentEvents"
              :key="idx"
              class="event-item"
            >
              <span class="event-time">{{ evt.time }}</span>
              <span class="event-text">{{ evt.event }}</span>
            </div>
            <div v-if="recentEvents.length === 0" class="memory-empty">
              暂无事件记录
            </div>
          </div>
        </div>
      </aside>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useAuthStore } from '@/stores/authStore'
import { useChatStore } from '@/stores/chatStore'
import {
  initChatService,
  startProactivePolling,
  stopProactivePolling,
} from '@/services/chatService'
import {
  getCharacterGradient,
  getCharacterInitial,
  getCharacterAvatarUrl,
  getMoodEmoji,
  getEnergyColor,
} from '@/utils/character'
import VoiceCallButton from '@/components/VoiceCallButton.vue'

const store = useChatStore()
const auth = useAuthStore()
const input = ref('')
const messageAreaRef = ref<HTMLElement | null>(null)
const scrollAnchor = ref<HTMLElement | null>(null)

// 移动端 Tab 切换
const mobileTab = ref<'chat' | 'character' | 'favor' | 'memory'>('chat')
const mobileTabs = [
  { key: 'chat' as const, icon: '💬', label: '聊天' },
  { key: 'character' as const, icon: '🎭', label: '角色' },
  { key: 'favor' as const, icon: '💖', label: '好感' },
  { key: 'memory' as const, icon: '🧠', label: '记忆' },
]

const characterGradient = computed(() =>
  getCharacterGradient(store.currentCharacterId || 'default'),
)
const characterInitial = computed(() =>
  getCharacterInitial(store.characterName),
)
const characterAvatar = computed(() =>
  getCharacterAvatarUrl(store.character?.avatar),
)
const ringOffset = computed(() => {
  const circumference = 2 * Math.PI * 52
  return circumference - (store.favorability / 100) * circumference
})
const recentEvents = computed(() => store.events.slice(-5).reverse())

const headerSub = computed(() => {
  if (store.streaming) return '正在输入...'
  if (store.loading) return '思考中...'
  return '在线 · ' + (store.relationship.level || '陌生')
})

const scrollToBottom = async () => {
  await nextTick()
  scrollAnchor.value?.scrollIntoView({ behavior: 'smooth', block: 'end' })
}

watch(
  () => [store.displayMessages.length, store.loading],
  () => scrollToBottom(),
)

onMounted(async () => {
  await initChatService()
  startProactivePolling()
  scrollToBottom()
})

onUnmounted(() => {
  stopProactivePolling()
})

const send = async () => {
  const msg = input.value.trim()
  if (!msg || store.loading) return
  input.value = ''
  await store.send(msg)
}

const handleSwitch = async (id: string) => {
  await store.switchCharacter(id)
}

const onKeydown = (e: KeyboardEvent) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    send()
  }
}
</script>

<style scoped>
.chat-page {
  position: relative;
  height: 100vh;
  overflow: hidden;
  background: #0a0a14;
  color: #e8e8f0;
  font-family: 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
}

.bg-orbs {
  position: absolute;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
  z-index: 0;
}

.orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);
  opacity: 0.35;
}

.orb-1 {
  width: 400px;
  height: 400px;
  background: #7b5cff;
  top: -100px;
  left: -100px;
  animation: float 12s ease-in-out infinite;
}

.orb-2 {
  width: 350px;
  height: 350px;
  background: #ff6b9d;
  bottom: -80px;
  right: 20%;
  animation: float 15s ease-in-out infinite reverse;
}

.orb-3 {
  width: 300px;
  height: 300px;
  background: #4facfe;
  top: 40%;
  right: -80px;
  animation: float 10s ease-in-out infinite;
}

@keyframes float {
  0%, 100% { transform: translate(0, 0); }
  50% { transform: translate(20px, -20px); }
}

.chat-layout {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: minmax(240px, 300px) minmax(360px, 1fr) minmax(240px, 320px);
  width: 100%;
  height: 100vh;
  gap: 0;
}

.panel {
  height: 100vh;
  overflow: hidden;
}

/* 玻璃卡片 */
.glass-card {
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 20px;
  backdrop-filter: blur(24px);
  -webkit-backdrop-filter: blur(24px);
}

/* ========== 左栏 ========== */
.left-panel {
  padding: 20px 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  border-right: 1px solid rgba(255, 255, 255, 0.06);
  overflow-y: auto;
}

.character-card {
  padding: 24px 20px;
  text-align: center;
}

.portrait {
  position: relative;
  width: 140px;
  height: 180px;
  margin: 0 auto 20px;
  border-radius: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  box-shadow: 0 8px 32px rgba(123, 92, 255, 0.3);
}

.portrait-initial {
  font-size: 64px;
  font-weight: 800;
  color: rgba(255, 255, 255, 0.9);
  text-shadow: 0 2px 12px rgba(0, 0, 0, 0.3);
  z-index: 1;
}

.portrait-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  z-index: 1;
}

.avatar-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  border-radius: inherit;
}

.portrait-glow {
  position: absolute;
  inset: 0;
  background: linear-gradient(180deg, transparent 60%, rgba(0, 0, 0, 0.4));
}

.char-name {
  font-size: 28px;
  font-weight: 700;
  margin-bottom: 8px;
  background: linear-gradient(135deg, #fff, #c8b6ff);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.personality-badge {
  display: inline-block;
  padding: 4px 14px;
  border-radius: 999px;
  background: rgba(123, 92, 255, 0.2);
  color: #c8b6ff;
  font-size: 13px;
  border: 1px solid rgba(123, 92, 255, 0.3);
}

.char-desc {
  margin-top: 12px;
  font-size: 13px;
  color: #8888aa;
  line-height: 1.6;
}

.status-grid {
  margin-top: 20px;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  text-align: left;
}

.status-item {
  background: rgba(255, 255, 255, 0.03);
  border-radius: 14px;
  padding: 12px;
}

.status-item.full {
  grid-column: 1 / -1;
}

.status-label {
  display: block;
  font-size: 11px;
  color: #666680;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 6px;
}

.status-value {
  font-size: 14px;
  font-weight: 500;
}

.status-value.event {
  font-size: 13px;
  color: #aaaacc;
}

.energy-bar {
  height: 6px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.08);
  overflow: hidden;
  margin: 4px 0;
}

.energy-fill {
  height: 100%;
  border-radius: 999px;
  transition: width 0.6s ease;
}

.energy-num {
  font-size: 12px;
  color: #8888aa;
}

.switch-card {
  padding: 16px;
  flex-shrink: 0;
}

.section-title {
  font-size: 14px;
  font-weight: 600;
  color: #aaaacc;
  margin-bottom: 14px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.view-all-link {
  margin-left: auto;
  font-size: 12px;
  font-weight: 400;
  color: #7b5cff;
  text-decoration: none;
  transition: color 0.2s ease;
}

.view-all-link:hover {
  color: #a78bfa;
}

.title-icon {
  font-size: 16px;
}

.char-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.char-btn {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 14px;
  border: 1px solid transparent;
  background: rgba(255, 255, 255, 0.03);
  color: #ccc;
  cursor: pointer;
  transition: all 0.25s ease;
  text-align: left;
  width: 100%;
}

.char-btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.07);
  border-color: rgba(255, 255, 255, 0.1);
}

.char-btn.active {
  background: rgba(123, 92, 255, 0.15);
  border-color: rgba(123, 92, 255, 0.4);
  color: #fff;
}

.char-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.char-avatar-mini {
  width: 36px;
  height: 36px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 14px;
  color: #fff;
  flex-shrink: 0;
}

.char-btn-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.char-btn-name {
  font-size: 14px;
  font-weight: 600;
}

.char-btn-desc {
  font-size: 11px;
  color: #666680;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.switching-hint {
  text-align: center;
  font-size: 12px;
  color: #8888aa;
  margin-top: 8px;
}

.settings-link {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 12px;
  text-decoration: none;
  color: #8888aa;
  font-size: 13px;
  transition: all 0.2s;
  margin-top: auto;
}

.settings-link:hover {
  color: #c8b6ff;
  background: rgba(123, 92, 255, 0.08);
}

/* ========== 中栏 ========== */
.chat-panel {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.chat-header {
  margin: 16px 16px 0;
  padding: 16px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 14px;
}

.header-avatar {
  width: 44px;
  height: 44px;
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 18px;
  color: #fff;
}

.chat-header h1 {
  font-size: 18px;
  font-weight: 600;
}

.header-sub {
  font-size: 12px;
  color: #666680;
  margin-top: 2px;
}

.online-pulse {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #57ff93;
  box-shadow: 0 0 12px #57ff93;
  animation: pulse 2s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.message-area {
  flex: 1;
  overflow-y: auto;
  padding: 20px 24px;
  scroll-behavior: smooth;
}

.empty-chat {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #555570;
}

.empty-icon {
  font-size: 48px;
  margin-bottom: 16px;
  opacity: 0.5;
}

.empty-hint {
  font-size: 13px;
  margin-top: 8px;
  color: #444460;
}

.msg-row {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  margin-bottom: 20px;
}

.msg-row.user {
  flex-direction: row-reverse;
}

.msg-avatar {
  width: 36px;
  height: 36px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 700;
  color: #fff;
  flex-shrink: 0;
}

.user-avatar {
  background: linear-gradient(135deg, #667eea, #764ba2);
  font-size: 12px;
}

.bubble-wrap {
  max-width: 65%;
  display: flex;
  flex-direction: column;
}

.msg-row.user .bubble-wrap {
  align-items: flex-end;
}

.bubble {
  padding: 14px 18px;
  border-radius: 20px;
  line-height: 1.7;
  font-size: 15px;
  white-space: pre-wrap;
  word-break: break-word;
}

.msg-row.assistant .bubble {
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-bottom-left-radius: 6px;
}

.msg-row.user .bubble {
  background: linear-gradient(135deg, #7b5cff, #b06cff);
  border-bottom-right-radius: 6px;
  box-shadow: 0 4px 16px rgba(123, 92, 255, 0.25);
}

.bubble-time {
  font-size: 11px;
  color: #555570;
  margin-top: 4px;
  padding: 0 4px;
}

.bubble-failed {
  opacity: 0.6;
  border: 1px dashed rgba(248, 113, 113, 0.5);
}

.retry-btn {
  margin-top: 4px;
  padding: 4px 12px;
  border-radius: 10px;
  border: 1px solid rgba(248, 113, 113, 0.4);
  background: rgba(248, 113, 113, 0.12);
  color: #fca5a5;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.retry-btn:hover:not(:disabled) {
  background: rgba(248, 113, 113, 0.2);
}

.retry-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.chat-error-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  padding: 10px 14px;
  border-radius: 12px;
  background: rgba(248, 113, 113, 0.12);
  border: 1px solid rgba(248, 113, 113, 0.3);
  color: #fca5a5;
  font-size: 13px;
}

.error-text {
  flex: 1;
}

.error-retry {
  padding: 3px 12px;
  border-radius: 8px;
  border: 1px solid rgba(252, 165, 165, 0.5);
  background: transparent;
  color: #fca5a5;
  font-size: 12px;
  cursor: pointer;
}

.error-retry:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.error-close {
  border: none;
  background: transparent;
  color: #fca5a5;
  font-size: 18px;
  cursor: pointer;
  line-height: 1;
  padding: 0 4px;
}

.typing-bubble {
  display: flex;
  gap: 5px;
  padding: 16px 20px;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 20px;
  border-bottom-left-radius: 6px;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #8888aa;
  animation: bounce 1.4s ease-in-out infinite;
}

.dot:nth-child(2) { animation-delay: 0.2s; }
.dot:nth-child(3) { animation-delay: 0.4s; }

@keyframes bounce {
  0%, 60%, 100% { transform: translateY(0); }
  30% { transform: translateY(-6px); }
}

.scroll-anchor {
  height: 1px;
}

.input-area {
  margin: 0 16px 16px;
  padding: 12px 12px 12px 20px;
  display: flex;
  align-items: flex-end;
  gap: 12px;
  flex-shrink: 0;
}

.input-area textarea {
  flex: 1;
  min-height: 44px;
  max-height: 120px;
  resize: none;
  border: none;
  outline: none;
  background: transparent;
  color: #e8e8f0;
  font-size: 15px;
  line-height: 1.5;
  font-family: inherit;
}

.input-area textarea::placeholder {
  color: #555570;
}

.pending-notice {
  margin: 0;
  padding: 12px 0;
  text-align: center;
  color: #fdba74;
  font-size: 0.9rem;
  width: 100%;
}

.send-btn {
  width: 80px;
  height: 44px;
  border: none;
  border-radius: 14px;
  background: linear-gradient(135deg, #7b5cff, #b06cff);
  color: #fff;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}

.send-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 16px rgba(123, 92, 255, 0.4);
}

.send-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.send-loading {
  width: 18px;
  height: 18px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* ========== 右栏 ========== */
.right-panel {
  padding: 20px 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  border-left: 1px solid rgba(255, 255, 255, 0.06);
  overflow-y: auto;
}

.favor-card {
  padding: 20px;
  text-align: center;
  flex-shrink: 0;
}

.favor-ring-wrap {
  position: relative;
  width: 120px;
  height: 120px;
  margin: 0 auto 12px;
}

.favor-ring {
  width: 100%;
  height: 100%;
  transform: rotate(-90deg);
}

.ring-bg {
  fill: none;
  stroke: rgba(255, 255, 255, 0.06);
  stroke-width: 8;
}

.ring-fill {
  fill: none;
  stroke: url(#favorGrad);
  stroke-width: 8;
  stroke-linecap: round;
  stroke-dasharray: 326.73;
  transition: stroke-dashoffset 0.8s ease;
  stroke: #ff6b9d;
}

.favor-center {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}

.favor-num {
  font-size: 32px;
  font-weight: 800;
  background: linear-gradient(135deg, #ff6b9d, #c8b6ff);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  line-height: 1;
}

.favor-unit {
  font-size: 11px;
  color: #666680;
}

.favor-level {
  font-size: 16px;
  font-weight: 600;
  color: #ff6b9d;
  margin-bottom: 12px;
}

.rel-info {
  display: flex;
  justify-content: center;
  gap: 8px;
  font-size: 13px;
  margin-bottom: 8px;
}

.rel-label {
  color: #666680;
}

.rel-value {
  color: #c8b6ff;
  font-weight: 500;
}

.rel-reason {
  font-size: 12px;
  color: #555570;
  line-height: 1.5;
  padding: 0 8px;
}

.memory-card,
.events-card {
  padding: 16px;
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.memory-list,
.events-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.memory-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 12px;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 12px;
  font-size: 13px;
  line-height: 1.5;
  color: #aaaacc;
}

.memory-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #7b5cff;
  margin-top: 7px;
  flex-shrink: 0;
}

.memory-empty {
  text-align: center;
  color: #444460;
  font-size: 13px;
  padding: 20px 0;
}

.event-item {
  padding: 10px 12px;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 12px;
}

.event-time {
  display: block;
  font-size: 11px;
  color: #555570;
  margin-bottom: 4px;
}

.event-text {
  font-size: 13px;
  color: #aaaacc;
  line-height: 1.5;
}

/* 滚动条 */
::-webkit-scrollbar {
  width: 5px;
}

::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.1);
  border-radius: 999px;
}

::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.18);
}

/* ========== 移动端 Tab 栏 + 抽屉 ========== */

.mobile-tab-bar {
  display: none;
}

.mobile-drawer {
  display: none;
}

.mobile-hidden {
  /* desktop: no-op */
}

/* 响应式：窄屏仅保留中间聊天区 */
@media (max-width: 1100px) {
  .chat-layout {
    grid-template-columns: minmax(220px, 260px) minmax(280px, 1fr) minmax(220px, 280px);
  }
}

@media (max-width: 900px) {
  .chat-layout {
    grid-template-columns: 1fr;
  }

  .left-panel,
  .right-panel {
    display: none;
  }

  /* 移动端 Tab 栏 */
  .mobile-tab-bar {
    display: flex;
    flex-shrink: 0;
    margin-top: auto;
    border-top: 1px solid rgba(255, 255, 255, 0.06);
    background: rgba(10, 10, 20, 0.95);
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
    padding: 6px 8px env(safe-area-inset-bottom, 8px);
    gap: 4px;
  }

  .mobile-tab {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 2px;
    padding: 8px 4px;
    border: none;
    border-radius: 12px;
    background: transparent;
    color: #666680;
    cursor: pointer;
    transition: all 0.2s ease;
  }

  .mobile-tab.active {
    background: rgba(123, 92, 255, 0.15);
    color: #c8b6ff;
  }

  .mobile-tab:active {
    transform: scale(0.95);
  }

  .tab-icon {
    font-size: 18px;
  }

  .tab-label {
    font-size: 10px;
    font-weight: 500;
  }

  /* 移动端隐藏消息区（非聊天 tab 时） */
  .mobile-hidden {
    display: none !important;
  }

  /* 移动端隐藏输入区（非聊天 tab 时）配合 sibling 选择器不现实，
     用 v-show 绑定更可靠 —— 但当前结构输入区在 tab 栏外面。
     这里用 CSS 无法直接控制，改为：当 mobileTab !== 'chat' 时隐藏输入区。
     实际上 tab 栏在输入区之后，用 CSS ~ 选择器不行。
     所以给 input-area 也加一个 class。 */

  /* 移动端抽屉面板 */
  .mobile-drawer {
    display: flex;
    flex: 1;
    overflow-y: auto;
    padding: 16px;
  }

  .mobile-drawer-inner {
    width: 100%;
  }

  .mobile-char-portrait {
    width: 100px;
    height: 130px;
    margin: 0 auto 16px;
    border-radius: 20px;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
    box-shadow: 0 8px 32px rgba(123, 92, 255, 0.3);
  }

  .mobile-char-portrait .portrait-img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }

  .mobile-char-portrait .portrait-initial {
    font-size: 48px;
    font-weight: 800;
    color: rgba(255, 255, 255, 0.9);
  }

  .mobile-char-name {
    text-align: center;
    font-size: 22px;
    font-weight: 700;
    margin-bottom: 8px;
    background: linear-gradient(135deg, #fff, #c8b6ff);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
  }

  .mobile-char-desc {
    text-align: center;
    font-size: 13px;
    color: #8888aa;
    margin-bottom: 20px;
    line-height: 1.6;
  }

  .mobile-char-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .mobile-favor {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding-top: 24px;
  }

  .mobile-section-title {
    font-size: 15px;
    font-weight: 600;
    color: #aaaacc;
    margin-bottom: 14px;
  }

  .mobile-memory-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  /* 移动端输入区也要适配 */
  .input-area {
    margin-bottom: 8px;
  }
}
</style>
