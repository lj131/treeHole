<template>
  <Teleport to="body">
    <div class="modal-overlay" @click.self="close">
      <div
        class="voice-modal"
        :class="{ dragging: dragState.dragging }"
        :style="{ transform: 'translate(' + dragState.offsetX + 'px, ' + dragState.offsetY + 'px)' }"
      >
        <!-- 拖动条 -->
        <div class="drag-handle" @mousedown.prevent="onDragStart">
          <span class="drag-dots">⋮⋮</span>
          <span class="drag-title">语音通话</span>
          <button class="close-btn" @click="close">✕</button>
        </div>

        <!-- 紧凑头部 -->
        <div class="modal-header-compact">
          <div
            class="portrait-small"
            :style="{ background: character?.avatar ? 'transparent' : characterGradient }"
          >
            <img
              v-if="character?.avatar"
              :src="getCharacterAvatarUrl(character.avatar)"
              class="portrait-img"
              alt="角色头像"
            />
            <span v-else class="portrait-initial">{{ getCharacterInitial(character?.name) }}</span>
          </div>
          <div class="char-name-status">
            <span class="char-name">{{ character?.name || 'AI角色' }}</span>
            <span class="status-dot" :class="{ active: isConnected }"></span>
            <span class="status-text-sm" :class="phaseClass">{{ getConnectionText() }}</span>
          </div>
          <span class="call-duration-sm">{{ formatDuration(callDuration) }}</span>
        </div>

        <!-- 音频可视化（紧凑） -->
        <div class="audio-viz-compact">
          <div
            v-for="(level, index) in (isConnected ? audioLevels : Array(6).fill(5))"
            :key="index"
            class="audio-bar-sm"
            :style="{ height: `${Math.max(4, isConnected ? level : 5)}%` }"
          ></div>
        </div>

        <!-- 对话记录（紧凑） -->
        <div class="transcript-area-sm" ref="transcriptEl">
          <div v-if="transcript.length === 0 && !isAiThinking && !interimText" class="transcript-empty">
            说话即可开始对话...
          </div>
          <div v-for="(item, idx) in transcript" :key="idx" class="ts-line" :class="`ts-${item.role}`">
            <template v-if="item.role === 'status'">
              <span class="ts-status">{{ item.text }}</span>
            </template>
            <template v-else>
              <span class="ts-text">{{ item.text }}</span>
            </template>
          </div>
          <div v-if="isAiThinking" class="ts-line ts-assistant">
            <span class="ts-text thinking">思考中...</span>
          </div>
          <div v-if="interimText" class="ts-line ts-user interim">
            <span class="ts-text">{{ interimText }}</span>
          </div>
        </div>

        <!-- 错误提示 -->
        <div v-if="error" class="error-bar">
          <span class="error-msg" @click="clearError">{{ error }}</span>
        </div>

        <!-- 通话控制（紧凑） -->
        <div class="controls-bar">
          <button class="ctrl-btn" :class="{ active: isMuted }" @click="toggleMute" title="静音">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M11 5L6 9H2v6h4l5 4V5z"/>
              <path d="M19.07 4.93a10 10 0 0 1 0 14.14" />
            </svg>
          </button>

          <button class="ctrl-btn end-btn-sm" @click="toggleVoiceCall" title="挂断">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
              <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
            </svg>
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick, reactive } from 'vue'
import { useChatStore } from '@/stores/chatStore'
import { useVoiceCallStore } from '@/stores/voiceCallStore'
import { webrtcService, playTtsAudio } from '@/services/webrtcService'
import {
  getCharacterAvatarUrl,
  getCharacterGradient,
  getCharacterInitial,
} from '@/utils/character'

interface Props {
  character?: any
}

interface TranscriptItem {
  role: 'user' | 'assistant' | 'status'
  text: string
  time: number
}

const props = defineProps<Props>()
const emit = defineEmits(['close'])

const store = useChatStore()
const voiceCallStore = useVoiceCallStore()

// 通话状态（从store获取）
const isConnected = computed(() => voiceCallStore.isConnected)
const isCalling = computed(() => voiceCallStore.isCalling)
const isMuted = computed(() => voiceCallStore.isMuted)
const isSpeakerOn = computed(() => voiceCallStore.isSpeakerOn)
const callDuration = computed(() => voiceCallStore.callDuration)
const audioLevels = ref(Array(12).fill(0))
const networkQuality = computed(() => voiceCallStore.networkQuality)
const ttsProvider = computed(() => voiceCallStore.ttsProvider)
const connectionState = computed(() => voiceCallStore.connectionState)
const error = computed(() => voiceCallStore.error)

// 对话记录
const transcript = ref<TranscriptItem[]>([])
const transcriptEl = ref<HTMLElement | null>(null)
// isAiThinking 统一走 store（供 callPhase 状态指示 + 打断判断使用）
const isAiThinking = computed({
  get: () => voiceCallStore.isAiThinking,
  set: (v: boolean) => { voiceCallStore.isAiThinking = v },
})
const callPhase = computed(() => voiceCallStore.callPhase)
const isAiSpeaking = computed(() => voiceCallStore.isAiSpeaking)

// 语音识别
let recognition: any = null
const isRecognizing = ref(false)
const interimText = ref('')
// 缓冲：合并短停顿的连续语音
let speechBuffer = ''
let speechFlushTimer: ReturnType<typeof setTimeout> | null = null

// 计算属性
const characterGradient = computed(() =>
  getCharacterGradient(props.character?.id || 'default')
)

// ---- 语音识别 ----

function initSpeechRecognition() {
  const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
  if (!SpeechRecognition) {
    console.warn('[Voice Modal] 浏览器不支持语音识别')
    return
  }

  console.log('[Voice Modal] 初始化语音识别 (lang=zh-CN)')
  recognition = new SpeechRecognition()
  recognition.lang = 'zh-CN'
  recognition.continuous = true
  recognition.interimResults = true
  recognition.maxAlternatives = 1

  recognition.onresult = (event: any) => {
    let finalText = ''
    let interim = ''
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const result = event.results[i]
      if (result.isFinal) {
        finalText += result[0].transcript
      } else {
        interim += result[0].transcript
      }
    }
    if (interim) {
      interimText.value = interim
    }

    if (finalText.trim()) {
      // 缓冲机制：暂停 1.5s 内继续说话则合并，否则发送
      speechBuffer += finalText.trim()
      console.log('[Voice Modal] 识别片段: "%s", 缓冲: "%s"', finalText.trim(), speechBuffer)

      // 重置发送计时器
      if (speechFlushTimer) clearTimeout(speechFlushTimer)
      speechFlushTimer = setTimeout(() => {
        const combined = speechBuffer.trim()
        if (combined) {
          console.log('[Voice Modal] 发送合并文本: "%s"', combined)
          addTranscript('user', combined)
          webrtcService.sendTextMessage(combined)
          isAiThinking.value = true
        }
        speechBuffer = ''
        speechFlushTimer = null
      }, 1500)
    }
  }

  recognition.onerror = (event: any) => {
    console.warn('[Voice Modal] 语音识别错误:', event.error)
    if (event.error === 'no-speech' || event.error === 'aborted') {
      if (isRecognizing.value && recognition) {
        try { recognition.start() } catch (_) { /* ignore */ }
      }
    }
  }

  recognition.onend = () => {
    console.log('[Voice Modal] 语音识别 onend, isRecognizing=%s', isRecognizing.value)
    if (isRecognizing.value) {
      setTimeout(() => {
        try { recognition?.start() } catch (_) { /* ignore */ }
      }, 200)
    }
  }
}

function startRecognition() {
  if (!recognition) initSpeechRecognition()
  if (!recognition) return
  isRecognizing.value = true
  try {
    recognition.start()
    console.log('语音识别已启动')
  } catch (_) {
    // 可能已经在运行
    isRecognizing.value = true
  }
}

function stopRecognition() {
  isRecognizing.value = false
  interimText.value = ''
  // 清空缓冲（不发送未完成的内容）
  speechBuffer = ''
  if (speechFlushTimer) { clearTimeout(speechFlushTimer); speechFlushTimer = null }
  if (recognition) {
    try { recognition.abort() } catch (_) { /* ignore */ }
  }
}

// ---- 对话记录 ----

function addTranscript(role: 'user' | 'assistant' | 'status', text: string) {
  transcript.value.push({ role, text, time: Date.now() })
  nextTick(() => {
    if (transcriptEl.value) {
      transcriptEl.value.scrollTop = transcriptEl.value.scrollHeight
    }
  })
}

function setupMessageHandler() {
  console.log('[Voice Modal] 设置消息回调')
  webrtcService.setOnMessage((message: any) => {
    console.log('[Voice Modal] onMessage:', message.type)
    if (message.type === 'response') {
      console.log('[Voice Modal] ← AI 回复: "%s"', message.text?.substring(0, 80))
      isAiThinking.value = false
      if (message.text) {
        addTranscript('assistant', message.text)
        // 同步到主聊天界面
        store.refreshAll()
      }
    } else if (message.type === 'conversation_started') {
      console.log('[Voice Modal] conversation_started success=%s', message.success)
      if (message.success) {
        addTranscript('status', '对话已开始，请说话...')
        startRecognition()
      } else {
        addTranscript('status', '对话初始化失败，请重试')
      }
    } else if (message.type === 'tts_audio') {
      console.log('[Voice Modal] ← TTS 音频 (%d chars)', message.audio?.length || 0)
      if (message.audio) {
        playTtsAudio(message.audio)
      }
    } else if (message.type === 'call_ended') {
      console.log('[Voice Modal] 通话已结束')
    } else if (message.type === 'interrupted') {
      console.log('[Voice Modal] 已打断 AI 播放')
      addTranscript('status', '（已打断，请说…）')
      isAiThinking.value = false
    } else if (message.type === 'connection_state') {
      console.log('[Voice Modal] 连接状态: %s', message.state)
    } else if (message.type === 'error') {
      console.error('[Voice Modal] 服务器错误:', message.message)
      isAiThinking.value = false
      addTranscript('status', `错误: ${message.message || '未知错误'}`)
    }
  })
}

// ---- 拖动 ----

const dragState = reactive({
  dragging: false,
  startX: 0,
  startY: 0,
  offsetX: 0,
  offsetY: 0,
})

function onDragStart(e: MouseEvent) {
  dragState.dragging = true
  dragState.startX = e.clientX - dragState.offsetX
  dragState.startY = e.clientY - dragState.offsetY
  document.addEventListener('mousemove', onDragMove)
  document.addEventListener('mouseup', onDragEnd)
}

function onDragMove(e: MouseEvent) {
  if (!dragState.dragging) return
  dragState.offsetX = e.clientX - dragState.startX
  dragState.offsetY = e.clientY - dragState.startY
}

function onDragEnd() {
  dragState.dragging = false
  document.removeEventListener('mousemove', onDragMove)
  document.removeEventListener('mouseup', onDragEnd)
}

// ---- 方法 ----

const close = async () => {
  // 先刷出缓冲区中未发送的语音
  if (speechBuffer.trim() && speechFlushTimer) {
    clearTimeout(speechFlushTimer)
    addTranscript('user', speechBuffer.trim())
    webrtcService.sendTextMessage(speechBuffer.trim())
    isAiThinking.value = true
    speechBuffer = ''
    speechFlushTimer = null
  }
  stopRecognition()
  if (voiceCallStore.isCalling) {
    await voiceCallStore.endCall()
  }
  emit('close')
}

const toggleMute = () => {
  voiceCallStore.toggleMute()
}

const toggleSpeaker = () => {
  voiceCallStore.toggleSpeaker()
}

const toggleScreenshare = () => {
  console.log('Screen share not implemented yet')
}

const toggleVoiceCall = async () => {
  close()
}

const formatDuration = (seconds: number) => {
  const mins = Math.floor(seconds / 60)
  const secs = seconds % 60
  return `${mins}:${secs.toString().padStart(2, '0')}`
}

const getNetworkQualityText = () => {
  if (networkQuality.value > 80) return '优秀'
  if (networkQuality.value > 50) return '良好'
  return '较差'
}

const getConnectionText = () => {
  if (error.value) return '连接失败'
  if (isCalling.value && !isConnected.value) return '连接中...'
  if (isConnected.value) {
    // 细分对话阶段
    const phase = callPhase.value
    if (phase === 'speaking') return '🔊 正在说话'
    if (phase === 'thinking') return '💭 思考中'
    if (phase === 'listening') return '🎧 聆听中'
    return '正在通话中'
  }
  return '准备连接'
}

const phaseClass = computed(() => `phase-${callPhase.value}`)

// 音频可视化
let interval: ReturnType<typeof setInterval>

const updateAudioLevels = () => {
  // AI 说话时可视化跟 AI 音量；否则跟用户麦克风音量（直观反映"现在谁在说"）
  const currentLevel = isAiSpeaking.value
    ? voiceCallStore.audioLevel
    : (isMuted.value ? 0 : voiceCallStore.micLevel)
  audioLevels.value = audioLevels.value.map((_, index) => {
    const wave = Math.sin(Date.now() / 200 + index * 0.5)
    const level = currentLevel * (0.5 + wave * 0.5)
    return Math.min(100, Math.floor(level))
  })
}

const networkQualityClass = computed(() => voiceCallStore.networkQualityClass)

const clearError = () => {
  voiceCallStore.clearError()
}

watch(error, (newError) => {
  if (newError) {
    console.error('Voice call error:', newError)
  }
})

// 监听连接成功 — 启动语音识别（仅首次）
let recognitionWasStarted = false
watch(isConnected, (connected) => {
  if (connected && !recognitionWasStarted) {
    recognitionWasStarted = true
    addTranscript('status', '对话已开始，请说话...')
    startRecognition()
  }
})

onMounted(() => {
  interval = setInterval(() => {
    updateAudioLevels()
  }, 100)

  // 立即注册消息回调（必须在 conversation_started 到达之前，否则会丢失）
  setupMessageHandler()
})

onUnmounted(() => {
  clearInterval(interval)
  stopRecognition()
  if (voiceCallStore.isCalling) {
    voiceCallStore.endCall()
  }
})
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  z-index: 1000;
}

.voice-modal {
  position: fixed;
  top: 50%;
  left: 50%;
  width: 280px;
  background: rgba(25, 25, 45, 0.96);
  backdrop-filter: blur(12px);
  border-radius: 16px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.5);
  overflow: hidden;
  z-index: 1001;
  margin-left: -140px;
  margin-top: -200px;
  user-select: none;
}

.voice-modal.dragging { cursor: grabbing; }

.drag-handle {
  display: flex;
  align-items: center;
  padding: 6px 12px;
  background: rgba(255, 255, 255, 0.05);
  cursor: grab;
  gap: 8px;
}
.drag-handle:active { cursor: grabbing; }
.drag-dots { color: #666; font-size: 14px; letter-spacing: 2px; }
.drag-title { color: #999; font-size: 12px; flex: 1; }

.close-btn {
  width: 24px; height: 24px;
  border: none; border-radius: 6px;
  background: rgba(255, 255, 255, 0.1);
  color: #e8e8f0;
  cursor: pointer; font-size: 14px;
  display: flex; align-items: center; justify-content: center;
}
.close-btn:hover { background: rgba(255, 255, 255, 0.25); }

.modal-header-compact {
  display: flex; align-items: center;
  padding: 10px 14px; gap: 10px;
}

.portrait-small {
  width: 36px; height: 36px; border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  font-size: 16px; font-weight: 600; color: white; flex-shrink: 0;
}
.portrait-small .portrait-img {
  width: 100%; height: 100%; border-radius: 10px; object-fit: cover;
}

.char-name-status {
  display: flex; align-items: center; gap: 6px;
  flex: 1; min-width: 0;
}
.char-name {
  color: #e8e8f0; font-size: 14px; font-weight: 600;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.status-dot { width: 7px; height: 7px; border-radius: 50%; background: #666; flex-shrink: 0; }
.status-dot.active { background: #4ade80; box-shadow: 0 0 6px #4ade80; }
.status-text-sm { color: #888; font-size: 11px; transition: color 0.2s ease; }
.status-text-sm.phase-listening { color: #6ee7b7; }
.status-text-sm.phase-thinking { color: #fde68a; }
.status-text-sm.phase-speaking { color: #c4b5fd; }
.call-duration-sm { color: #666; font-size: 12px; font-variant-numeric: tabular-nums; flex-shrink: 0; }

.audio-viz-compact {
  height: 32px; display: flex;
  align-items: flex-end; justify-content: center;
  gap: 3px; padding: 0 14px 4px;
}
.audio-bar-sm {
  width: 5px; background: linear-gradient(to top, #7b5cff, #ff6b9d);
  border-radius: 3px; min-height: 3px; flex-shrink: 0;
}

.transcript-area-sm {
  margin: 0 10px; max-height: 140px; min-height: 40px;
  overflow-y: auto; padding: 8px;
  background: rgba(0, 0, 0, 0.2); border-radius: 10px;
  display: flex; flex-direction: column; gap: 4px;
}
.transcript-area-sm::-webkit-scrollbar { width: 3px; }
.transcript-area-sm::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.1); border-radius: 2px;
}
.transcript-empty { color: #555; font-size: 12px; text-align: center; padding: 12px 0; }

.ts-line { animation: tsIn 0.2s ease; }
.ts-user .ts-text {
  background: rgba(123, 92, 255, 0.25);
  border-radius: 8px 8px 0 8px; margin-left: auto;
}
.ts-assistant .ts-text {
  background: rgba(255, 255, 255, 0.06);
  border-radius: 8px 8px 8px 0;
}
.ts-text {
  display: inline-block; padding: 4px 10px;
  color: #e0e0e0; font-size: 12px; line-height: 1.4;
  max-width: 90%; word-break: break-word;
}
.ts-text.thinking { opacity: 0.5; font-style: italic; }
.ts-status { color: #555; font-size: 11px; text-align: center; display: block; padding: 2px 0; }
.ts-line.interim .ts-text {
  opacity: 0.5;
  background: rgba(123, 92, 255, 0.1);
}
.ts-line.interim .ts-text::after {
  content: '▍';
  animation: blink-caret 1s step-end infinite;
  color: #a78bfa;
  margin-left: 2px;
}
@keyframes blink-caret {
  50% { opacity: 0; }
}

.error-bar {
  margin: 4px 10px; padding: 4px 10px;
  background: rgba(239, 68, 68, 0.15); border-radius: 6px;
}
.error-msg { color: #f87171; font-size: 11px; cursor: pointer; }

.controls-bar {
  display: flex; align-items: center; justify-content: center;
  gap: 16px; padding: 10px 14px;
}
.ctrl-btn {
  width: 36px; height: 36px; border: none; border-radius: 10px;
  background: rgba(255, 255, 255, 0.08); color: #e8e8f0;
  cursor: pointer; display: flex; align-items: center; justify-content: center;
}
.ctrl-btn:hover { background: rgba(255, 255, 255, 0.15); }
.ctrl-btn.active { background: rgba(255, 107, 157, 0.3); }
.end-btn-sm {
  width: 48px; height: 48px; border-radius: 14px;
  background: linear-gradient(135deg, #ff6b9d, #ff8e8e);
}
.end-btn-sm:hover { transform: scale(1.08); }

@keyframes tsIn {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
