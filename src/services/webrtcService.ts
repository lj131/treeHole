/**
 * WebRTC服务封装
 * 处理实时语音通话连接
 */
export class WebRTCService {
  private peerConnection: RTCPeerConnection | null = null
  private localStream: MediaStream | null = null
  private remoteStream: MediaStream | null = null
  private websocket: WebSocket | null = null
  private audioContext: AudioContext | null = null
  private mediaRecorder: MediaRecorder | null = null
  private audioChunks: Blob[] = []
  private isInitialized = false
  private currentCallId: string = ''
  private currentCharacterId: string = ''

  // 静音 / 扬声器状态（模块级，供 playTtsAudio 读取）
  private muted = false
  private speakerEnabled = true

  // 配置
  private config: RTCConfiguration = {
    iceServers: [
      { urls: 'stun:stun.l.google.com:19302' },
      { urls: 'stun:stun1.l.google.com:19302' },
      { urls: 'stun:stun2.l.google.com:19302' }
    ],
    iceCandidatePoolSize: 10,
    bundlePolicy: 'max-bundle',
    rtcpMuxPolicy: 'require',
  }

  // 事件回调
  private onConnectionStateChange?: (state: RTCPeerConnectionState) => void
  private onAudioLevelChange?: (level: number) => void
  private onError?: (error: Error) => void
  private onMessage?: (message: any) => void
  private onMicLevelChange?: (level: number) => void
  private micAnalyzer: AnalyserNode | null = null
  private micRafId: number | null = null

  /**
   * 初始化WebRTC服务
   */
  async init(): Promise<void> {
    if (this.isInitialized) return

    try {
      // 创建WebRTC连接
      this.peerConnection = new RTCPeerConnection(this.config)

      // 创建WebSocket连接：生产环境走同源 nginx 代理，开发直连 8000
      const wsBase = import.meta.env.VITE_WS_BASE
        || (import.meta.env.VITE_API_BASE?.startsWith('http')
          ? import.meta.env.VITE_API_BASE.replace('http', 'ws')
          : (typeof location !== 'undefined'
            ? `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}`
            : 'ws://127.0.0.1:8000'))
      const wsUrl = `${wsBase}/voice/call`
      this.websocket = new WebSocket(wsUrl)

      // 设置WebSocket事件处理
      this.websocket.onopen = this.handleWebSocketOpen.bind(this)
      this.websocket.onmessage = this.handleWebSocketMessage.bind(this)
      this.websocket.onclose = this.handleWebSocketClose.bind(this)
      this.websocket.onerror = this.handleWebSocketError.bind(this)

      // 设置WebRTC事件处理
      this.peerConnection.onconnectionstatechange = this.handleConnectionStateChange.bind(this)
      this.peerConnection.ontrack = this.handleTrack.bind(this)
      this.peerConnection.onicecandidate = this.handleIceCandidate.bind(this)
      this.peerConnection.oniceconnectionstatechange = this.handleIceConnectionStateChange.bind(this)

      // 初始化音频上下文
      this.audioContext = new AudioContext()

      this.isInitialized = true
      console.log('[Voice] WebRTC 服务初始化成功 ws=%s', wsUrl)
    } catch (error) {
      console.error('WebRTC服务初始化失败:', error)
      throw error
    }
  }

  /**
   * 开始语音通话
   */
  async startVoiceCall(characterId: string): Promise<string> {
    if (!this.peerConnection || !this.websocket) {
      throw new Error('WebRTC服务未初始化')
    }

    try {
      // 获取麦克风权限
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          sampleRate: 48000,
          channelCount: 1
        }
      })

      this.currentCharacterId = characterId
      this.localStream = stream

      // 启动用户麦克风音量分析（用于打断检测）
      this.setupMicLevelAnalysis()

      // 添加本地音频轨道
      stream.getTracks().forEach(track => {
        this.peerConnection!.addTrack(track, stream)
      })

      // 创建offer
      const offer = await this.peerConnection.createOffer()
      await this.peerConnection.setLocalDescription(offer)

      // 发送offer到服务器
      const message = {
        type: 'offer',
        offer: {
          sdp: offer.sdp,
          type: offer.type
        },
        user_id: 'current_user',
        character_id: characterId
      }

      await this.sendWebSocketMessage(message)

      return 'call_initiated'
    } catch (error) {
      console.error('开始语音通话失败:', error)
      throw error
    }
  }

  /**
   * 处理WebSocket打开
   */
  private handleWebSocketOpen(): void {
    console.log('WebSocket连接已建立')
  }

  /**
   * 处理WebSocket消息
   */
  private handleWebSocketMessage(event: MessageEvent): void {
    const message = JSON.parse(event.data)
    const msgType = message.type
    // 非高频消息都打印日志
    if (msgType !== 'pong' && msgType !== 'ice_candidate') {
      console.log('[Voice WS] 收到:', msgType, msgType === 'tts_audio' ? '(audio data)' : message)
    }

    switch (msgType) {
      case 'answer':
        console.log('[Voice WS] → handleAnswer call_id:', message.call_id)
        this.handleAnswer(message)
        break
      case 'ice_candidate':
        this.handleIceCandidateFromServer(message)
        break
      case 'error':
        console.error('[Voice WS] 服务器错误:', message.message)
        this.onError?.(new Error(message.message))
        break
      default:
        if (msgType !== 'pong') {
          console.log('[Voice WS] → onMessage:', msgType)
        }
        this.onMessage?.(message)
    }
  }

  /**
   * 处理WebRTC answer
   */
  private async handleAnswer(message: any): Promise<void> {
    if (!this.peerConnection) return

    try {
      // 存储服务器分配的 call_id
      if (message.call_id) {
        this.currentCallId = message.call_id
        // 发送之前暂存的 ICE 候选
        this._flushPendingCandidates()
      }

      const answer = new RTCSessionDescription({
        sdp: message.sdp,
        type: message.type
      })

      await this.peerConnection.setRemoteDescription(answer)

      // 开始对话
      await this.startConversation()
    } catch (error) {
      console.error('处理answer失败:', error)
      this.onError?.(error as Error)
    }
  }

  /**
   * 处理ICE候选
   */
  private handleIceCandidate(event: RTCPeerConnectionIceEvent): void {
    if (!event.candidate || !this.websocket) return
    // 等待服务器分配真实 call_id 后再发送 ICE 候选
    if (!this.currentCallId) {
      // 暂存候选，等 answer 到达后批量发送
      if (!this._pendingCandidates) this._pendingCandidates = []
      this._pendingCandidates.push(event.candidate)
      return
    }
    this._sendIceCandidate(event.candidate)
  }

  private _pendingCandidates: RTCIceCandidate[] | null = null

  private _sendIceCandidate(candidate: RTCIceCandidate): void {
    if (!this.websocket) return
    const message = {
      type: 'ice_candidate',
      candidate: candidate.candidate,
      sdpMid: candidate.sdpMid,
      sdpMLineIndex: candidate.sdpMLineIndex,
      call_id: this.getCurrentCallId(),
    }
    this.sendWebSocketMessage(message)
  }

  private _flushPendingCandidates(): void {
    if (!this._pendingCandidates) return
    for (const candidate of this._pendingCandidates) {
      this._sendIceCandidate(candidate)
    }
    this._pendingCandidates = null
  }

  /**
   * 处理服务器发送的ICE候选
   */
  private async handleIceCandidateFromServer(message: any): Promise<void> {
    if (!this.peerConnection) return

    try {
      const candidate = new RTCIceCandidate({
        sdpMid: message.sdpMid,
        sdpMLineIndex: message.sdpMLineIndex,
        candidate: message.candidate
      })

      await this.peerConnection.addIceCandidate(candidate)
    } catch (error) {
      console.error('添加ICE候选失败:', error)
    }
  }

  /**
   * 处理连接状态变化
   */
  private handleConnectionStateChange(): void {
    const state = this.peerConnection?.connectionState
    console.log('连接状态变化:', state)

    this.onConnectionStateChange?.(state || 'disconnected')
  }

  /**
   * 处理轨道事件
   */
  private handleTrack(event: RTCTrackEvent): void {
    console.log('收到轨道:', event.track.kind)

    if (event.track.kind === 'audio') {
      this.remoteStream = new MediaStream([event.track])
      this.setupAudioAnalysis()
    }
  }

  /**
   * 处理ICE连接状态变化
   */
  private handleIceConnectionStateChange(): void {
    const state = this.peerConnection?.iceConnectionState
    console.log('ICE连接状态:', state)
  }

  /**
   * 设置音频分析
   */
  private setupAudioAnalysis(): void {
    if (!this.audioContext || !this.remoteStream) return

    const source = this.audioContext.createMediaStreamSource(this.remoteStream)
    const analyzer = this.audioContext.createAnalyser()

    analyzer.fftSize = 256
    source.connect(analyzer)

    const dataArray = new Uint8Array(analyzer.frequencyBinCount)
    const bufferLength = analyzer.frequencyBinCount

    const updateAudioLevel = () => {
      analyzer.getByteFrequencyData(dataArray)

      // 计算平均音量
      let sum = 0
      for (let i = 0; i < bufferLength; i++) {
        sum += dataArray[i] ?? 0
      }
      const average = sum / bufferLength

      // 转换为0-100的级别
      const level = Math.min(100, Math.floor(average / 2.55))

      this.onAudioLevelChange?.(level)

      if (this.peerConnection?.connectionState === 'connected') {
        requestAnimationFrame(updateAudioLevel)
      }
    }

    updateAudioLevel()
  }

  /**
   * 用户麦克风音量分析（用于打断检测）。
   * 独立于 setupAudioAnalysis（那个分析 AI 远端音频）。
   */
  private setupMicLevelAnalysis(): void {
    if (!this.audioContext || !this.localStream) return

    // 复用同一个 audioContext，接 localStream
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

      if (this.localStream && this.peerConnection?.connectionState === 'connected') {
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

  /**
   * 开始对话
   */
  private async startConversation(): Promise<void> {
    if (!this.websocket) return

    try {
      const message = {
        type: 'start_conversation',
        call_id: this.getCurrentCallId(),
        character_id: this.currentCharacterId,
        user_id: 'current_user',
      }

      await this.sendWebSocketMessage(message)
    } catch (error) {
      console.error('开始对话失败:', error)
    }
  }

  /**
   * 发送音频数据（base64 编码，分块拼接避免大数组 spread 爆栈）
   * 注：当前语音识别在前端完成，此方法为预留路径。
   */
  async sendAudioData(audioData: ArrayBuffer): Promise<void> {
    if (!this.websocket) return

    try {
      const bytes = new Uint8Array(audioData)
      let binary = ''
      const chunkSize = 0x8000
      for (let i = 0; i < bytes.length; i += chunkSize) {
        binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunkSize) as unknown as number[])
      }
      const message = {
        type: 'audio_data',
        call_id: this.getCurrentCallId(),
        audio_data: btoa(binary),
      }

      await this.sendWebSocketMessage(message)
    } catch (error) {
      console.error('发送音频数据失败:', error)
    }
  }

  /**
   * 结束通话
   */
  async endVoiceCall(): Promise<void> {
    try {
      // 发送结束消息（仅在 WebSocket 可用时）
      if (this.websocket && this.websocket.readyState === WebSocket.OPEN) {
        const message = {
          type: 'end_call',
          call_id: this.getCurrentCallId()
        }
        await this.sendWebSocketMessage(message)
      }
    } catch (error) {
      console.error('发送结束通话消息失败:', error)
    } finally {
      // 无论如何都要清理资源（停止麦克风、关闭连接）
      await this.cleanup()
    }
  }

  /**
   * 清理资源 — 始终停止所有媒体轨道和连接
   */
  private async cleanup(): Promise<void> {
    // 关闭WebRTC连接（先关闭以触发 ICE 断开）
    if (this.peerConnection) {
      this.peerConnection.close()
      this.peerConnection = null
    }

    // 停止所有本地媒体轨道（最关键：关闭麦克风）
    if (this.localStream) {
      this.localStream.getTracks().forEach(track => {
        track.stop()
        console.log('已停止媒体轨道:', track.kind)
      })
      this.localStream = null
    }

    // 关闭WebSocket
    if (this.websocket) {
      this.websocket.close()
      this.websocket = null
    }

    // 关闭音频上下文
    if (this.audioContext) {
      this.audioContext.close()
      this.audioContext = null
    }

    this._pendingCandidates = null
    this.currentCallId = ''
    this.currentCharacterId = ''
    this.isInitialized = false
    this.muted = false
    this.speakerEnabled = true

    // 停止麦克风音量分析 + 当前 TTS 播放
    this.stopMicLevelAnalysis()
    stopTtsAudio()
  }

  /**
   * 处理WebSocket关闭
   */
  private handleWebSocketClose(): void {
    console.log('WebSocket连接已关闭')
    this.cleanup()
  }

  /**
   * 处理WebSocket错误
   */
  private handleWebSocketError(event: Event): void {
    console.error('WebSocket错误:', event)
    this.onError?.(new Error('WebSocket连接失败'))
  }

  /**
   * 发送WebSocket消息
   */
  private async sendWebSocketMessage(message: any): Promise<void> {
    if (!this.websocket || this.websocket.readyState !== WebSocket.OPEN) {
      throw new Error('WebSocket未连接')
    }

    this.websocket.send(JSON.stringify(message))
  }

  /**
   * 获取当前 call_id（从服务器 answer 响应中获取）
   */
  private getCurrentCallId(): string {
    return this.currentCallId || 'pending'
  }

  /**
   * 发送语音识别后的文本消息给后端 AI
   */
  async sendTextMessage(text: string): Promise<void> {
    if (!this.websocket || this.websocket.readyState !== WebSocket.OPEN) {
      console.warn('[Voice] WebSocket 未连接，无法发送文本消息')
      return
    }
    console.log('[Voice] → 发送 text_message: "%s" call_id=%s', text, this.getCurrentCallId())
    const message = {
      type: 'text_message',
      call_id: this.getCurrentCallId(),
      text,
    }
    this.websocket.send(JSON.stringify(message))
  }

  /**
   * 用户打断：立即停止本地 TTS 播放 + 通知后端丢弃待发队列。
   */
  interrupt(): void {
    console.log('[Voice] → interrupt call_id=%s', this.getCurrentCallId())
    stopTtsAudio()
    if (this.websocket && this.websocket.readyState === WebSocket.OPEN) {
      const message = {
        type: 'interrupt',
        call_id: this.getCurrentCallId(),
      }
      this.websocket.send(JSON.stringify(message))
    }
  }

  /**
   * 设置事件回调
   */
  setOnConnectionStateChange(callback: (state: RTCPeerConnectionState) => void): void {
    this.onConnectionStateChange = callback
  }

  setOnAudioLevelChange(callback: (level: number) => void): void {
    this.onAudioLevelChange = callback
  }

  setOnMicLevelChange(callback: (level: number) => void): void {
    this.onMicLevelChange = callback
  }

  setOnError(callback: (error: Error) => void): void {
    this.onError = callback
  }

  setOnMessage(callback: (message: any) => void): void {
    this.onMessage = callback
  }

  /**
   * 获取连接状态
   */
  getConnectionState(): RTCPeerConnectionState {
    return this.peerConnection?.connectionState || 'disconnected'
  }

  /**
   * 是否已连接
   */
  isConnected(): boolean {
    return this.getConnectionState() === 'connected'
  }

  /**
   * 静音 / 取消静音本地麦克风（控制上传的音频轨道）
   */
  setMuted(muted: boolean): void {
    this.muted = muted
    if (this.localStream) {
      this.localStream.getAudioTracks().forEach((track) => {
        track.enabled = !muted
      })
      console.log('[Voice] 本地麦克风 %s', muted ? '已静音' : '已恢复')
    }
  }

  isMuted(): boolean {
    return this.muted
  }

  /**
   * 开启 / 关闭扬声器（控制 TTS 与远程音频是否播放）
   */
  setSpeakerEnabled(enabled: boolean): void {
    this.speakerEnabled = enabled
    console.log('[Voice] 扬声器 %s', enabled ? '已开启' : '已关闭')
  }

  isSpeakerOn(): boolean {
    return this.speakerEnabled
  }
}

// 创建全局实例
export const webrtcService = new WebRTCService()

// ============================================================
// TTS 播放（可中断）+ 播放状态回调
// ============================================================

let _currentSource: AudioBufferSourceNode | null = null
let _currentCtx: AudioContext | null = null
let _currentCtxOwned = false  // 是否为 playTtsAudio 自建的 ctx（自建的需要关闭）
let _onPlayStateChange: ((playing: boolean) => void) | null = null

/** 注册 TTS 播放状态回调（开始/结束/被打断） */
export function setOnTtsPlayStateChange(cb: ((playing: boolean) => void) | null): void {
  _onPlayStateChange = cb
}

function notifyPlayState(playing: boolean): void {
  if (_onPlayStateChange) _onPlayStateChange(playing)
}

/** 立即停止当前 TTS 播放（用户打断时调用） */
export function stopTtsAudio(): void {
  if (_currentSource) {
    try {
      _currentSource.onended = null
      _currentSource.stop()
    } catch (e) {
      console.debug('[Voice] stop source 忽略预期异常:', e)
    }
    _currentSource = null
  }
  if (_currentCtxOwned && _currentCtx) {
    try {
      _currentCtx.close()
    } catch (e) {
      console.debug('[Voice] close ctx 忽略预期异常:', e)
    }
  }
  _currentCtx = null
  _currentCtxOwned = false
  notifyPlayState(false)
}

/**
 * 播放 TTS 音频（base64 编码的 WAV/PCM 数据）。
 * 新一段到来时会先停掉上一段；可被 stopTtsAudio() 中途打断。
 */
export async function playTtsAudio(
  base64Audio: string,
  audioCtx?: AudioContext,
): Promise<void> {
  // 扬声器关闭时不播放
  if (!webrtcService.isSpeakerOn()) {
    console.log('[Voice] 扬声器已关闭，跳过 TTS 播放')
    return
  }

  // 先停掉上一段（新 TTS 覆盖旧的）
  stopTtsAudio()

  const owned = !audioCtx
  const ctx = audioCtx ?? new AudioContext()
  _currentCtx = ctx
  _currentCtxOwned = owned

  try {
    // base64 → ArrayBuffer
    const binaryStr = atob(base64Audio)
    const bytes = new Uint8Array(binaryStr.length)
    for (let i = 0; i < binaryStr.length; i++) {
      bytes[i] = binaryStr.charCodeAt(i)
    }
    const audioBuffer = await ctx.decodeAudioData(bytes.buffer)

    // 合成/解码期间可能已被 stopTtsAudio 打断（ctx 被关），检查
    if (_currentCtx !== ctx) {
      // 已被打断，放弃这一段
      if (owned) ctx.close()
      return
    }

    const source = ctx.createBufferSource()
    source.buffer = audioBuffer
    source.connect(ctx.destination)
    source.start(0)
    _currentSource = source

    source.onended = () => {
      // 自然播放结束
      if (_currentSource === source) {
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