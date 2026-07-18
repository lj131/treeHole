/**
 * 语音通话服务（纯 WebSocket，无 WebRTC）
 *
 * - 语音识别：浏览器 SpeechRecognition API（在 VoiceCallModal 中）
 * - AI 回复 + TTS：WebSocket 文本 → 后端 DeepSeek + Edge TTS → base64 WAV 回传
 * - 打断检测：AudioContext 分析本地麦克风音量
 */
export class VoiceService {
  private localStream: MediaStream | null = null
  private websocket: WebSocket | null = null
  private audioContext: AudioContext | null = null
  private isInitialized = false
  private currentCallId: string = ''
  private currentCharacterId: string = ''

  // 静音 / 扬声器状态
  private muted = false
  private speakerEnabled = true

  // 事件回调
  private onError?: (error: Error) => void
  private onMessage?: (message: any) => void
  private onMicLevelChange?: (level: number) => void
  private onCallEnd?: () => void
  private onWsOpen?: () => void
  private onWsClose?: () => void
  private micAnalyzer: AnalyserNode | null = null
  private micRafId: number | null = null

  /**
   * 初始化（只创建 AudioContext，不连接 WebSocket）
   */
  async init(): Promise<void> {
    if (this.isInitialized) return
    this.audioContext = new AudioContext()
    this.isInitialized = true
    this._cleanedUp = false
    console.log('[Voice] 服务初始化成功（AudioContext 就绪）')
  }

  /**
   * 建立 WebSocket 连接（在所有回调注册之后调用）
   */
  private connectWebSocket(): Promise<void> {
    return new Promise((resolve, reject) => {
      const wsBase = import.meta.env.VITE_WS_BASE
        || (import.meta.env.VITE_API_BASE?.startsWith('http')
          ? import.meta.env.VITE_API_BASE.replace('http', 'ws')
          : (typeof location !== 'undefined'
            ? `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}`
            : 'ws://127.0.0.1:8000'))
      const token = localStorage.getItem('auth_token') || ''
      const wsUrl = `${wsBase}/voice/call?token=${encodeURIComponent(token)}`
      this.websocket = new WebSocket(wsUrl)

      this.websocket.onopen = () => {
        console.log('[Voice] WebSocket 连接已建立')
        // 连接成功后才注册 onclose（避免连接失败时触发 store 通知）
        this.websocket!.onclose = this.handleWebSocketClose.bind(this)
        this.onWsOpen?.()
        resolve()
      }
      this.websocket.onmessage = this.handleWebSocketMessage.bind(this)
      this.websocket.onerror = (event) => {
        console.error('[Voice] WebSocket 错误:', event)
        this.onError?.(new Error('WebSocket连接失败'))
        reject(new Error('WebSocket连接失败'))
      }
    })
  }

  /**
   * 开始语音通话
   */
  async startVoiceCall(characterId: string): Promise<string> {
    try {
      // 1. 建立 WebSocket
      await this.connectWebSocket()

      // 2. 获取麦克风（用于打断检测）
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          sampleRate: 48000,
          channelCount: 1,
        },
      })
      this.currentCharacterId = characterId
      this.localStream = stream
      this.setupMicLevelAnalysis()

      // 3. 生成 call_id 并发起对话
      this.currentCallId = crypto.randomUUID()
      await this.sendWebSocketMessage({
        type: 'start_conversation',
        call_id: this.currentCallId,
        character_id: characterId,
      })

      return this.currentCallId
    } catch (error) {
      console.error('[Voice] 开始通话失败:', error)
      await this.cleanup()
      throw error
    }
  }

  /**
   * 处理 WebSocket 消息
   */
  private handleWebSocketMessage(event: MessageEvent): void {
    const message = JSON.parse(event.data)
    const msgType = message.type
    if (msgType !== 'pong') {
      console.log('[Voice WS] 收到:', msgType, msgType === 'tts_audio' ? '(audio data)' : message)
    }
    if (msgType !== 'pong') {
      this.onMessage?.(message)
    }
  }

  /**
   * 处理 WebSocket 关闭（异常断连时通知 store 重置状态）
   */
  private handleWebSocketClose(): void {
    console.log('[Voice] WebSocket 连接已关闭')
    this.cleanup(true)
    this.onWsClose?.()
  }

  private _cleanedUp = false

  /**
   * 清理资源
   * @param notifyStore 是否通知 store 重置状态（WebSocket 异常断连时为 true）
   */
  private async cleanup(notifyStore = false): Promise<void> {
    if (this._cleanedUp) return
    this._cleanedUp = true

    // 停止所有本地媒体轨道（关闭麦克风）
    if (this.localStream) {
      this.localStream.getTracks().forEach(track => {
        track.stop()
        console.log('[Voice] 已停止媒体轨道:', track.kind)
      })
      this.localStream = null
    }

    // 关闭 WebSocket
    if (this.websocket) {
      this.websocket.onclose = null // 防止 handleWebSocketClose 再次触发 cleanup
      this.websocket.close()
      this.websocket = null
    }

    // 关闭音频上下文
    if (this.audioContext) {
      this.audioContext.close()
      this.audioContext = null
    }

    this.currentCallId = ''
    this.currentCharacterId = ''
    this.isInitialized = false
    this.muted = false
    this.speakerEnabled = true

    this.stopMicLevelAnalysis()
    stopTtsAudio()

    if (notifyStore) {
      this.onCallEnd?.()
    }
  }

  private async sendWebSocketMessage(message: any): Promise<void> {
    if (!this.websocket || this.websocket.readyState !== WebSocket.OPEN) {
      throw new Error('WebSocket未连接')
    }
    this.websocket.send(JSON.stringify(message))
  }

  /**
   * 结束通话
   */
  async endVoiceCall(): Promise<void> {
    try {
      if (this.websocket && this.websocket.readyState === WebSocket.OPEN) {
        await this.sendWebSocketMessage({
          type: 'end_call',
          call_id: this.currentCallId,
        })
      }
    } catch (error) {
      console.error('[Voice] 发送结束通话消息失败:', error)
    } finally {
      await this.cleanup()
    }
  }

  /**
   * 发送文本消息给后端 AI
   */
  async sendTextMessage(text: string): Promise<void> {
    if (!this.websocket || this.websocket.readyState !== WebSocket.OPEN) {
      console.warn('[Voice] WebSocket 未连接，无法发送文本消息')
      return
    }
    console.log('[Voice] → 发送 text_message: "%s" call_id=%s', text, this.currentCallId)
    this.websocket.send(JSON.stringify({
      type: 'text_message',
      call_id: this.currentCallId,
      text,
    }))
  }

  /**
   * 用户打断：立即停止本地 TTS 播放 + 通知后端丢弃待发队列
   */
  interrupt(): void {
    console.log('[Voice] → interrupt call_id=%s', this.currentCallId)
    stopTtsAudio()
    if (this.websocket && this.websocket.readyState === WebSocket.OPEN) {
      this.websocket.send(JSON.stringify({
        type: 'interrupt',
        call_id: this.currentCallId,
      }))
    }
  }

  // ---- 麦克风音量分析（打断检测用） ----

  private setupMicLevelAnalysis(): void {
    if (!this.audioContext || !this.localStream) return
    const source = this.audioContext.createMediaStreamSource(this.localStream)
    const analyzer = this.audioContext.createAnalyser()
    analyzer.fftSize = 256
    source.connect(analyzer)
    this.micAnalyzer = analyzer

    const dataArray = new Uint8Array(analyzer.frequencyBinCount)
    const bufferLength = analyzer.frequencyBinCount

    const updateMicLevel = () => {
      analyzer.getByteFrequencyData(dataArray)
      let sum = 0
      for (let i = 0; i < bufferLength; i++) {
        sum += dataArray[i] ?? 0
      }
      const average = sum / bufferLength
      const level = Math.min(100, Math.floor(average / 2.55))
      this.onMicLevelChange?.(level)

      if (this.localStream) {
        this.micRafId = requestAnimationFrame(updateMicLevel)
      }
    }
    updateMicLevel()
  }

  private stopMicLevelAnalysis(): void {
    if (this.micRafId !== null) {
      cancelAnimationFrame(this.micRafId)
      this.micRafId = null
    }
    this.micAnalyzer = null
  }

  // ---- 回调注册 ----

  setOnError(callback: (error: Error) => void): void { this.onError = callback }
  setOnMessage(callback: (message: any) => void): void { this.onMessage = callback }
  setOnMicLevelChange(callback: (level: number) => void): void { this.onMicLevelChange = callback }
  setOnCallEnd(callback: () => void): void { this.onCallEnd = callback }
  setOnWsOpen(callback: () => void): void { this.onWsOpen = callback }
  setOnWsClose(callback: () => void): void { this.onWsClose = callback }

  // ---- 静音 / 扬声器 ----

  setMuted(muted: boolean): void {
    this.muted = muted
    if (this.localStream) {
      this.localStream.getAudioTracks().forEach(track => { track.enabled = !muted })
      console.log('[Voice] 本地麦克风 %s', muted ? '已静音' : '已恢复')
    }
  }

  isMuted(): boolean { return this.muted }
  setSpeakerEnabled(enabled: boolean): void { this.speakerEnabled = enabled }
  isSpeakerOn(): boolean { return this.speakerEnabled }
}

// 创建全局实例（保持变量名兼容，外部 import 名也兼容）
export const webrtcService = new VoiceService()

// ============================================================
// TTS 播放（可中断）+ 播放状态回调 + lip-sync 音量回调
// ============================================================

let _currentSource: AudioBufferSourceNode | null = null
let _currentCtx: AudioContext | null = null
let _currentCtxOwned = false
let _onPlayStateChange: ((playing: boolean) => void) | null = null
const _ttsLipSyncListeners = new Set<(intensity: number) => void>()
let _lipSyncRaf: number | null = null

export function setOnTtsPlayStateChange(cb: ((playing: boolean) => void) | null): void {
  _onPlayStateChange = cb
}

/** 订阅 TTS 嘴型强度 0–1；返回取消订阅函数 */
export function subscribeTtsLipSync(cb: (intensity: number) => void): () => void {
  _ttsLipSyncListeners.add(cb)
  return () => {
    _ttsLipSyncListeners.delete(cb)
  }
}

/** @deprecated 使用 subscribeTtsLipSync；保留兼容单订阅写法 */
export function setOnTtsLipSync(cb: ((intensity: number) => void) | null): void {
  _ttsLipSyncListeners.clear()
  if (cb) _ttsLipSyncListeners.add(cb)
}

function emitTtsLipSync(intensity: number): void {
  for (const cb of _ttsLipSyncListeners) {
    try {
      cb(intensity)
    } catch (e) {
      console.debug('[Voice] lip-sync listener 忽略:', e)
    }
  }
}

function notifyPlayState(playing: boolean): void {
  if (_onPlayStateChange) _onPlayStateChange(playing)
}

function stopLipSyncLoop(resetMouth = true): void {
  if (_lipSyncRaf !== null) {
    cancelAnimationFrame(_lipSyncRaf)
    _lipSyncRaf = null
  }
  if (resetMouth && _ttsLipSyncListeners.size > 0) {
    emitTtsLipSync(0)
  }
}

function mouthIntensityFromAnalyser(
  analyser: AnalyserNode,
  dataArray: Uint8Array,
): number {
  analyser.getByteFrequencyData(dataArray)
  let sum = 0
  for (let i = 0; i < dataArray.length; i++) {
    const v = dataArray[i] ?? 0
    sum += v * v
  }
  const volume = Math.sqrt(sum / dataArray.length)
  const silenceThreshold = 8
  const maxVolume = 90
  if (volume < silenceThreshold) return 0
  return Math.min((volume - silenceThreshold) / (maxVolume - silenceThreshold), 1)
}

function startLipSyncLoop(analyser: AnalyserNode, source: AudioBufferSourceNode): void {
  stopLipSyncLoop(false)
  if (_ttsLipSyncListeners.size === 0) return

  const dataArray = new Uint8Array(analyser.frequencyBinCount)
  const tick = () => {
    if (_currentSource !== source) {
      stopLipSyncLoop(true)
      return
    }
    emitTtsLipSync(mouthIntensityFromAnalyser(analyser, dataArray))
    _lipSyncRaf = requestAnimationFrame(tick)
  }
  tick()
}

export function stopTtsAudio(): void {
  stopLipSyncLoop(true)
  if (_currentSource) {
    try {
      _currentSource.onended = null
      _currentSource.stop()
    } catch (e) {
      console.debug('[Voice] stop source 忽略:', e)
    }
    _currentSource = null
  }
  if (_currentCtxOwned && _currentCtx) {
    try { _currentCtx.close() } catch (e) { console.debug('[Voice] close ctx 忽略:', e) }
  }
  _currentCtx = null
  _currentCtxOwned = false
  notifyPlayState(false)
}

export async function playTtsAudio(
  base64Audio: string,
  audioCtx?: AudioContext,
): Promise<void> {
  if (!webrtcService.isSpeakerOn()) {
    console.log('[Voice] 扬声器已关闭，跳过 TTS 播放')
    return
  }

  stopTtsAudio()

  const owned = !audioCtx
  const ctx = audioCtx ?? new AudioContext()
  _currentCtx = ctx
  _currentCtxOwned = owned

  try {
    const binaryStr = atob(base64Audio)
    const bytes = new Uint8Array(binaryStr.length)
    for (let i = 0; i < binaryStr.length; i++) {
      bytes[i] = binaryStr.charCodeAt(i)
    }
    const audioBuffer = await ctx.decodeAudioData(bytes.buffer)

    if (_currentCtx !== ctx) {
      if (owned) ctx.close()
      return
    }

    const source = ctx.createBufferSource()
    source.buffer = audioBuffer

    // source → analyser → destination，供 lip-sync 读频谱
    const analyser = ctx.createAnalyser()
    analyser.fftSize = 256
    analyser.smoothingTimeConstant = 0.3
    source.connect(analyser)
    analyser.connect(ctx.destination)

    source.start(0)
    _currentSource = source
    startLipSyncLoop(analyser, source)

    source.onended = () => {
      if (_currentSource === source) {
        stopLipSyncLoop(true)
        _currentSource = null
        if (_currentCtxOwned && _currentCtx) {
          try { _currentCtx.close() } catch (e) { console.debug('[Voice] close 忽略:', e) }
        }
        _currentCtx = null
        _currentCtxOwned = false
        notifyPlayState(false)
      }
    }

    notifyPlayState(true)
  } catch (error) {
    console.error('TTS 音频播放失败:', error)
    stopLipSyncLoop(true)
    if (owned) {
      try { ctx.close() } catch (e) { console.debug('[Voice] close 忽略:', e) }
    }
    if (_currentCtx === ctx) {
      _currentCtx = null
      _currentCtxOwned = false
    }
    notifyPlayState(false)
  }
}
