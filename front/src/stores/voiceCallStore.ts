/**
 * 语音通话状态管理
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { webrtcService, setOnTtsPlayStateChange } from '@/services/webrtcService'

export interface VoiceCallState {
  isCalling: boolean
  isConnected: boolean
  isConnecting: boolean
  currentCharacter: string | null
  callId: string | null
  audioLevel: number
  connectionState: RTCPeerConnectionState
  error: string | null
  isMuted: boolean
  isSpeakerOn: boolean
  callDuration: number
  networkQuality: number
  ttsProvider: string
}

export const useVoiceCallStore = defineStore('voiceCall', () => {
  // 状态
  const isCalling = ref(false)
  const isConnected = ref(false)
  const isConnecting = ref(false)
  const currentCharacter = ref<string | null>(null)
  const callId = ref<string | null>(null)
  const audioLevel = ref(0)
  const connectionState = ref<RTCPeerConnectionState>('disconnected')
  const error = ref<string | null>(null)
  const isMuted = ref(false)
  const isSpeakerOn = ref(true)
  const callDuration = ref(0)
  const networkQuality = ref(95)
  const ttsProvider = ref('Edge TTS')
  const micLevel = ref(0)        // 用户麦克风音量（0-100），用于打断检测
  const isAiSpeaking = ref(false) // AI 正在播放 TTS
  const isAiThinking = ref(false) // AI 正在生成回复

  // 打断检测参数
  const INTERRUPT_THRESHOLD = 30  // 麦克风音量阈值
  const INTERRUPT_HOLD_MS = 300   // 持续超过此时长才判定为说话
  let micHighSince = 0            // 麦克风音量超阈值的起始时间戳

  // 计算属性
  const callStatus = computed(() => {
    if (error.value) return 'error'
    if (isConnecting.value) return 'connecting'
    if (isConnected.value) return 'connected'
    if (isCalling.value) return 'calling'
    return 'disconnected'
  })

  const networkQualityText = computed(() => {
    if (networkQuality.value > 80) return '优秀'
    if (networkQuality.value > 50) return '良好'
    return '较差'
  })

  const networkQualityClass = computed(() => {
    if (networkQuality.value > 80) return 'good'
    if (networkQuality.value > 50) return 'medium'
    return 'poor'
  })

  // 对话阶段（不同于连接层面的 callStatus）
  const callPhase = computed<'idle' | 'listening' | 'thinking' | 'speaking'>(() => {
    if (!isConnected.value) return 'idle'
    if (isAiSpeaking.value) return 'speaking'
    if (isAiThinking.value) return 'thinking'
    return 'listening'
  })

  /**
   * 打断检测：仅当 AI 正在说话、麦克风音量持续超阈值时触发一次打断。
   * 防误触发（咳嗽/环境音）：需持续 INTERRUPT_HOLD_MS。
   */
  const checkInterrupt = (level: number) => {
    if (!isAiSpeaking.value) {
      micHighSince = 0
      return
    }
    if (level < INTERRUPT_THRESHOLD) {
      micHighSince = 0
      return
    }
    if (micHighSince === 0) {
      micHighSince = Date.now()
      return
    }
    if (Date.now() - micHighSince >= INTERRUPT_HOLD_MS) {
      // 触发打断（一次性，isAiSpeaking 会在 stopTtsAudio 后变 false）
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

      // 初始化WebRTC服务
      await webrtcService.init()

      // 设置事件回调
      let iceFailTimer: ReturnType<typeof setTimeout> | null = null
      webrtcService.setOnConnectionStateChange((state) => {
        connectionState.value = state
        isConnected.value = state === 'connected'
        isConnecting.value = state === 'connecting'

        if (state === 'connected') {
          isCalling.value = true
          if (iceFailTimer) { clearTimeout(iceFailTimer); iceFailTimer = null }
          error.value = null
        } else if (state === 'failed' || state === 'disconnected') {
          // 3 秒后仍异常才认定为真正的失败（容忍 ICE 短暂重启）
          if (!iceFailTimer) {
            iceFailTimer = setTimeout(() => {
              isCalling.value = false
              error.value = '连接失败'
            }, 3000)
          }
        }
      })

      webrtcService.setOnAudioLevelChange((level) => {
        audioLevel.value = level
      })

      // 用户麦克风音量 + 打断检测
      webrtcService.setOnMicLevelChange((level) => {
        micLevel.value = level
        checkInterrupt(level)
      })

      // TTS 播放状态（开始/结束）
      setOnTtsPlayStateChange((playing) => {
        isAiSpeaking.value = playing
        // 播放结束或被打断时，重置打断检测计时
        if (!playing) micHighSince = 0
      })

      webrtcService.setOnError((err) => {
        error.value = err.message
      })

      // 开始通话
      const result = await webrtcService.startVoiceCall(characterId)
      isCalling.value = true
      callId.value = result // 实际应该从服务器获取call_id

      // 开始计时
      startCallTimer()

      // 开始监控网络质量
      startNetworkMonitoring()

      return true
    } catch (err) {
      error.value = err instanceof Error ? err.message : '启动通话失败'
      isConnecting.value = false
      return false
    }
  }

  const endCall = async () => {
    try {
      // 始终调用清理（即使连接未建立，也要停止本地麦克风）
      await webrtcService.endVoiceCall()

      // 重置状态
      isCalling.value = false
      isConnected.value = false
      isConnecting.value = false
      callId.value = null
      audioLevel.value = 0
      connectionState.value = 'disconnected'
      callDuration.value = 0
      networkQuality.value = 95

      // 停止计时
      stopCallTimer()

      // 停止监控
      stopNetworkMonitoring()

      return true
    } catch (err) {
      console.error('结束通话失败:', err)
      // 即使出错也要重置状态（与 try 分支保持完全一致）
      isCalling.value = false
      isConnected.value = false
      isConnecting.value = false
      callId.value = null
      audioLevel.value = 0
      connectionState.value = 'disconnected'
      callDuration.value = 0
      networkQuality.value = 95
      stopCallTimer()
      stopNetworkMonitoring()
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

  const clearError = () => {
    error.value = null
  }

  // 通话计时器
  let callTimer: ReturnType<typeof setInterval> | null = null

  const startCallTimer = () => {
    callTimer = setInterval(() => {
      if (isConnected.value) {
        callDuration.value++
      }
    }, 1000)
  }

  const stopCallTimer = () => {
    if (callTimer) {
      clearInterval(callTimer)
      callTimer = null
    }
  }

  // 网络质量监控
  let networkTimer: ReturnType<typeof setInterval> | null = null

  const startNetworkMonitoring = () => {
    networkTimer = setInterval(() => {
      // 基于 WebRTC 连接状态 + 音频活动估算网络质量（非纯随机）
      let target: number
      if (!isConnected.value) {
        target = connectionState.value === 'failed' ? 10 : 40
      } else if (audioLevel.value > 5) {
        // 有音频活动，链路健康
        target = 90 + Math.min(10, audioLevel.value / 10)
      } else {
        // 已连接但静默，轻微下行
        target = 75
      }
      // 平滑趋近目标值，避免跳变
      const current = networkQuality.value
      networkQuality.value = Math.round(current + (target - current) * 0.4)
    }, 2000)
  }

  const stopNetworkMonitoring = () => {
    if (networkTimer) {
      clearInterval(networkTimer)
      networkTimer = null
    }
  }

  // 生命周期钩子
  const onBeforeUnmount = () => {
    if (isCalling.value) {
      endCall()
    }
    stopCallTimer()
    stopNetworkMonitoring()
  }

  return {
    // 状态
    isCalling,
    isConnected,
    isConnecting,
    currentCharacter,
    callId,
    audioLevel,
    connectionState,
    error,
    isMuted,
    isSpeakerOn,
    callDuration,
    networkQuality,
    ttsProvider,
    micLevel,
    isAiSpeaking,
    isAiThinking,

    // 计算属性
    callStatus,
    networkQualityText,
    networkQualityClass,
    callPhase,

    // 方法
    startCall,
    endCall,
    toggleMute,
    toggleSpeaker,
    clearError,
    onBeforeUnmount
  }
})