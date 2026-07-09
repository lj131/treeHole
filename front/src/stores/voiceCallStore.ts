/**
 * 语音通话状态管理（纯 WebSocket，无 WebRTC）
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { webrtcService, setOnTtsPlayStateChange } from '@/services/webrtcService'

export const useVoiceCallStore = defineStore('voiceCall', () => {
  // 状态
  const isCalling = ref(false)
  const isConnected = ref(false)
  const isConnecting = ref(false)
  const currentCharacter = ref<string | null>(null)
  const callId = ref<string | null>(null)
  const error = ref<string | null>(null)
  const isMuted = ref(false)
  const isSpeakerOn = ref(true)
  const callDuration = ref(0)
  const ttsProvider = ref('Edge TTS')
  const micLevel = ref(0)
  const audioLevel = ref(0)   // AI 输出音量（TTS 播放时动态更新）
  const isAiSpeaking = ref(false)
  const isAiThinking = ref(false)

  // 打断检测参数
  const INTERRUPT_THRESHOLD = 30
  const INTERRUPT_HOLD_MS = 300
  let micHighSince = 0

  // 重连参数
  const MAX_RECONNECT = 3
  const RECONNECT_DELAYS = [1000, 2000, 4000]
  let reconnectAttempts = 0
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null

  // 计算属性
  const callStatus = computed(() => {
    if (error.value) return 'error'
    if (isConnecting.value) return 'connecting'
    if (isConnected.value) return 'connected'
    if (isCalling.value) return 'calling'
    return 'disconnected'
  })

  const callPhase = computed<'idle' | 'listening' | 'thinking' | 'speaking'>(() => {
    if (!isConnected.value) return 'idle'
    if (isAiSpeaking.value) return 'speaking'
    if (isAiThinking.value) return 'thinking'
    return 'listening'
  })

  /** 连接状态文本 */
  const connectionState = computed(() => {
    if (error.value) return 'error'
    if (isConnecting.value) return 'connecting'
    if (isConnected.value) return 'connected'
    return 'disconnected'
  })

  /** 网络质量评分 0-100（基于稳定连接时间估算） */
  const networkQuality = ref(80)

  /** 网络质量 CSS class */
  const networkQualityClass = computed(() => {
    if (networkQuality.value > 70) return 'quality-good'
    if (networkQuality.value > 40) return 'quality-fair'
    return 'quality-poor'
  })

  /**
   * 打断检测：仅当 AI 正在说话、麦克风音量持续超阈值时触发一次打断
   */
  const checkInterrupt = (level: number) => {
    if (!isAiSpeaking.value) { micHighSince = 0; return }
    if (level < INTERRUPT_THRESHOLD) { micHighSince = 0; return }
    if (micHighSince === 0) { micHighSince = Date.now(); return }
    if (Date.now() - micHighSince >= INTERRUPT_HOLD_MS) {
      micHighSince = 0
      console.log('[Voice] 检测到用户说话，触发打断')
      webrtcService.interrupt()
    }
  }

  // 方法
  const startCall = async (characterId: string) => {
    try {
      error.value = null
      isConnecting.value = true
      currentCharacter.value = characterId

      // 初始化（AudioContext）
      await webrtcService.init()

      // 注册回调
      webrtcService.setOnWsOpen(() => {
        isConnected.value = true
        isConnecting.value = false
        isCalling.value = true
        error.value = null
        reconnectAttempts = 0
      })

      webrtcService.setOnWsClose(() => {
        isConnected.value = false
        stopCallTimer()
        // 自动重连（用户未主动挂断时）
        if (isCalling.value && reconnectAttempts < MAX_RECONNECT) {
          const delay = RECONNECT_DELAYS[reconnectAttempts] ?? 4000
          reconnectAttempts++
          error.value = `连接断开，${delay / 1000}秒后重连 (${reconnectAttempts}/${MAX_RECONNECT})...`
          reconnectTimer = setTimeout(async () => {
            if (!isCalling.value) return // 用户已挂断
            try {
              await webrtcService.startVoiceCall(currentCharacter.value!)
              error.value = null
              reconnectAttempts = 0
            } catch {
              // 重连失败，等下次 onWsClose 再试
            }
          }, delay)
        } else if (reconnectAttempts >= MAX_RECONNECT) {
          isCalling.value = false
          isConnecting.value = false
          error.value = '重连失败，请重新发起通话'
          reconnectAttempts = 0
        } else {
          isCalling.value = false
          isConnecting.value = false
        }
      })

      webrtcService.setOnMicLevelChange((level) => {
        micLevel.value = level
        checkInterrupt(level)
      })

      setOnTtsPlayStateChange((playing) => {
        isAiSpeaking.value = playing
        audioLevel.value = playing ? 70 : 0
        if (!playing) micHighSince = 0
      })

      webrtcService.setOnError((err) => {
        error.value = err.message
      })

      webrtcService.setOnCallEnd(() => {
        isCalling.value = false
        isConnected.value = false
        isConnecting.value = false
        callId.value = null
        callDuration.value = 0
        stopCallTimer()
      })

      // 开始通话
      callId.value = await webrtcService.startVoiceCall(characterId)
      startCallTimer()

      return true
    } catch (err) {
      error.value = err instanceof Error ? err.message : '启动通话失败'
      isConnecting.value = false
      return false
    }
  }

  const endCall = async () => {
    // 取消重连
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null }
    reconnectAttempts = 0
    try {
      await webrtcService.endVoiceCall()
      isCalling.value = false
      isConnected.value = false
      isConnecting.value = false
      callId.value = null
      callDuration.value = 0
      stopCallTimer()
      return true
    } catch (err) {
      console.error('结束通话失败:', err)
      isCalling.value = false
      isConnected.value = false
      isConnecting.value = false
      callId.value = null
      callDuration.value = 0
      stopCallTimer()
      return false
    }
  }

  const toggleMute = () => {
    isMuted.value = !isMuted.value
    webrtcService.setMuted(isMuted.value)
  }

  const toggleSpeaker = () => {
    isSpeakerOn.value = !isSpeakerOn.value
    webrtcService.setSpeakerEnabled(isSpeakerOn.value)
  }

  const clearError = () => { error.value = null }

  // 通话计时器
  let callTimer: ReturnType<typeof setInterval> | null = null
  const startCallTimer = () => {
    callTimer = setInterval(() => { if (isConnected.value) callDuration.value++ }, 1000)
  }
  const stopCallTimer = () => {
    if (callTimer) { clearInterval(callTimer); callTimer = null }
  }

  const onBeforeUnmount = () => {
    if (isCalling.value) endCall()
    stopCallTimer()
  }

  return {
    isCalling, isConnected, isConnecting, currentCharacter, callId,
    error, isMuted, isSpeakerOn, callDuration, ttsProvider,
    micLevel, audioLevel, isAiSpeaking, isAiThinking,
    callStatus, callPhase, connectionState, networkQuality, networkQualityClass,
    startCall, endCall, toggleMute, toggleSpeaker, clearError, onBeforeUnmount,
  }
})
