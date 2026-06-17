/**
 * WebRTCService TDD — TTS 音频接收与播放
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

class FakeAudioContext {
  sampleRate = 48000
  destination = {}
  state = 'running'
  _buffers: AudioBuffer[] = []
  _sourceNodes: AudioBufferSourceNode[] = []

  decodeAudioData(data: ArrayBuffer) {
    this._buffers.push({ data, length: data.byteLength } as any)
    return Promise.resolve({ duration: 1.0, numberOfChannels: 1 } as any)
  }

  createBufferSource() {
    const node = {
      buffer: null as any,
      connect: vi.fn<() => void>(),
      start: vi.fn<() => void>(),
      onended: null as any,
    }
    this._sourceNodes.push(node as any)
    return node as any
  }

  close() {
    this.state = 'closed'
    return Promise.resolve()
  }
}

vi.stubGlobal('AudioContext', FakeAudioContext)
vi.stubGlobal('webkitAudioContext', FakeAudioContext)

import { webrtcService } from '@/services/webrtcService'

describe('WebRTCService — TTS 音频处理', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('handleWebSocketMessage 应把 tts_audio 消息传给 onMessage 回调', () => {
    const ttsMessage = JSON.stringify({
      type: 'tts_audio',
      call_id: 'test-call-123',
      audio: 'AAAA',
      format: 'wav',
    })

    let receivedMessage: any = null
    webrtcService.setOnMessage((msg) => {
      receivedMessage = msg
    })

    const event = { data: ttsMessage } as MessageEvent
    ;(webrtcService as any).handleWebSocketMessage(event)

    expect(receivedMessage).not.toBeNull()
    expect(receivedMessage.type).toBe('tts_audio')
    expect(receivedMessage.audio).toBe('AAAA')
  })

  it('playTtsAudio 应解码 base64 音频并通过 AudioContext 播放', async () => {
    // 这个函数还不存在 — RED
    const { playTtsAudio } = await import('@/services/webrtcService')

    const fakeAudioCtx = new FakeAudioContext()

    // 构造一小段有效 base64（WAV 空文件头）
    const base64Audio = 'UklGRiQAAABXQVZFZm10IBAAAAABAAEAIlYAAESsAAACABAAZGF0YQAAAAA='

    await playTtsAudio(base64Audio, fakeAudioCtx as any)

    // 断言：音频被解码
    expect(fakeAudioCtx._buffers.length).toBe(1)

    // 断言：创建了播放节点并调用了 start
    expect(fakeAudioCtx._sourceNodes.length).toBe(1)
    expect(fakeAudioCtx._sourceNodes[0]?.start).toHaveBeenCalled()
  })
})
