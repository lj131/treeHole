<template>
  <div v-if="incomingCall.incoming" class="call-overlay">
    <div class="call-card">
      <div class="call-top">
        <span class="call-label">{{ incomingCall.ringing ? '来电' : '正在接通' }}</span>
      </div>

      <div class="avatar-ring" :class="{ ringing: incomingCall.ringing }">
        <img
          v-if="avatar"
          :src="avatar"
          :alt="incomingCall.incoming.character_name"
          class="avatar"
        />
        <div v-else class="avatar avatar-fallback">
          {{ incomingCall.incoming.character_name?.charAt(0) || '她' }}
        </div>
      </div>

      <h2 class="call-name">{{ incomingCall.incoming.character_name }}</h2>
      <p class="call-reason">想打电话给你</p>
      <p v-if="incomingCall.incoming.reason" class="call-hint">
        {{ incomingCall.incoming.reason }}
      </p>

      <div class="call-actions">
        <button class="call-btn decline" :disabled="busy" @click="onDecline">
          <span class="call-btn-icon">✕</span>
          <span>拒绝</span>
        </button>
        <button class="call-btn accept" :disabled="busy" @click="onAccept">
          <span class="call-btn-icon">📞</span>
          <span>接听</span>
        </button>
      </div>

      <p class="call-timeout">不操作将在 {{ secondsLeft }} 秒后自动挂断</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useIncomingCallStore } from '@/stores/incomingCallStore'
import { useVoiceCallStore } from '@/stores/voiceCallStore'
import { useChatStore } from '@/stores/chatStore'
import { getCharacterAvatarUrl } from '@/utils/character'

const incomingCall = useIncomingCallStore()
const voiceCall = useVoiceCallStore()
const chat = useChatStore()

const busy = ref(false)
const secondsLeft = ref(20)

/** 头像：和聊天页同一个来源（`utils/character` 的 URL 解析） */
const avatar = computed(() => getCharacterAvatarUrl(chat.character?.avatar))

// ── 响铃：WebAudio 生成（不引音频文件，避免多一个静态资源）────────
let audioCtx: AudioContext | null = null
let ringOsc: OscillatorNode | null = null
let ringGain: GainNode | null = null
let ringTimer: number | null = null

function startRinging() {
  if (typeof window === 'undefined') return
  // 浏览器自动播放策略：没交互过时 AudioContext 是 suspended，
  // 这时**不能** resume（会抛），安静跳过即可（视觉照常）
  try {
    audioCtx = audioCtx || new AudioContext()
    if (audioCtx.state === 'suspended') return

    ringGain = audioCtx.createGain()
    ringGain.gain.value = 0.0001
    ringGain.connect(audioCtx.destination)

    ringOsc = audioCtx.createOscillator()
    ringOsc.type = 'sine'
    ringOsc.frequency.value = 520
    ringOsc.connect(ringGain)
    ringOsc.start()

    // 经典的"叮—咚"节奏
    let on = true
    ringTimer = window.setInterval(() => {
      if (!ringGain || !ringOsc) return
      on = !on
      ringGain.gain.setTargetAtTime(on ? 0.05 : 0.0001, audioCtx!.currentTime, 0.02)
      ringOsc.frequency.setValueAtTime(on ? 520 : 660, audioCtx!.currentTime)
    }, 380)
  } catch {
    /* 音频不可用时不阻塞来电界面 */
  }
}

function stopRinging() {
  if (ringTimer !== null) {
    clearInterval(ringTimer)
    ringTimer = null
  }
  try {
    ringOsc?.stop()
  } catch {
    /* 已经停了 */
  }
  ringOsc = null
  ringGain = null
}

watch(
  () => incomingCall.ringing,
  (on) => (on ? startRinging() : stopRinging()),
  { immediate: true },
)

// 倒计时（和后端/ store 的自动挂断同一个时长，视觉同步）
watch(
  () => incomingCall.incoming,
  (v) => {
    if (!v) return
    secondsLeft.value = 20
    const t = window.setInterval(() => {
      secondsLeft.value = Math.max(0, secondsLeft.value - 1)
      if (secondsLeft.value === 0) clearInterval(t)
    }, 1000)
  },
)

// ── 接听 / 拒绝 ────────────────────────────────────────────
async function onAccept() {
  const charId = incomingCall.incoming?.character_id
  await incomingCall.answer('answered')
  if (!charId) return
  // 复用已有的通话链路（VoiceCallButton 走的是同一条）
  busy.value = true
  try {
    await voiceCall.startCall(charId)
  } catch {
    /* 建立失败时通话界面自己会显示错误 */
  } finally {
    busy.value = false
  }
}

async function onDecline() {
  busy.value = true
  try {
    await incomingCall.answer('declined')
  } finally {
    busy.value = false
  }
}

onMounted(() => incomingCall.startPolling())
onUnmounted(() => {
  incomingCall.stopPolling()
  stopRinging()
})
</script>

<style scoped>
.call-overlay {
  position: fixed;
  inset: 0;
  z-index: 1200;
  display: grid;
  place-items: center;
  background: rgba(0, 0, 0, 0.72);
  backdrop-filter: blur(6px);
}

.call-card {
  width: min(340px, 86vw);
  padding: 28px 22px 22px;
  border-radius: 20px;
  text-align: center;
  background: var(--bg-secondary, #1f2430);
  border: 1px solid var(--border-color, rgba(255, 255, 255, 0.12));
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.45);
}

.call-label {
  font-size: 12px;
  letter-spacing: 2px;
  color: var(--text-secondary);
}

.avatar-ring {
  width: 108px;
  height: 108px;
  margin: 16px auto 14px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: rgba(99, 102, 241, 0.14);
  border: 2px solid rgba(129, 140, 248, 0.5);
}

.avatar-ring.ringing {
  animation: pulse 1.4s ease-out infinite;
}

@keyframes pulse {
  0% { box-shadow: 0 0 0 0 rgba(129, 140, 248, 0.45); }
  100% { box-shadow: 0 0 0 22px rgba(129, 140, 248, 0); }
}

.avatar {
  width: 92px;
  height: 92px;
  border-radius: 50%;
  object-fit: cover;
}

.avatar-fallback {
  display: grid;
  place-items: center;
  font-size: 34px;
  color: var(--text-primary);
  background: rgba(99, 102, 241, 0.3);
}

.call-name {
  margin: 0;
  font-size: 20px;
  color: var(--text-primary);
}

.call-reason {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--text-secondary);
}

.call-hint {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--text-secondary);
  opacity: 0.8;
}

.call-actions {
  display: flex;
  justify-content: space-between;
  gap: 18px;
  margin: 24px 8px 10px;
}

.call-btn {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 14px 0;
  border: none;
  border-radius: 16px;
  font-size: 13px;
  color: #fff;
  cursor: pointer;
  transition: transform 0.12s ease, opacity 0.12s ease;
}

.call-btn:active { transform: scale(0.96); }
.call-btn:disabled { opacity: 0.55; cursor: default; }

.call-btn-icon { font-size: 20px; }

.call-btn.decline { background: #ef4444; }
.call-btn.accept { background: #22c55e; }

.call-timeout {
  margin: 8px 0 0;
  font-size: 11px;
  color: var(--text-secondary);
  opacity: 0.7;
}
</style>
