/**
 * WebRTCService — TTS 音频接收与播放。
 *
 * 这里用 fake 替掉 Web Audio API：jsdom 没有实现它。替身**逐成员声明类型**而不是 `as any` ——
 * 后者会同时触发 no-explicit-any，也丢掉「引擎改了成员名这里不会报错」的保护。
 */
import { describe, it, expect, vi, beforeEach, type Mock } from 'vitest'

interface FakeDecodedBuffer {
  data: ArrayBuffer
  length: number
}

interface FakeSourceNode {
  buffer: AudioBuffer | null
  connect: Mock<(node: unknown) => void>
  start: Mock<() => void>
  onended: (() => void) | null
}

interface FakeAnalyser {
  fftSize: number
  smoothingTimeConstant: number
  frequencyBinCount: number
  connect: Mock<(node: unknown) => void>
  getByteFrequencyData: Mock<(arr: Uint8Array) => void>
}

class FakeAudioContext {
  sampleRate = 48000
  destination = {}
  state = 'running'
  _buffers: FakeDecodedBuffer[] = []
  _sourceNodes: FakeSourceNode[] = []

  decodeAudioData(data: ArrayBuffer): Promise<AudioBuffer> {
    this._buffers.push({ data, length: data.byteLength })
    return Promise.resolve({
      duration: 1.0,
      numberOfChannels: 1,
    } as unknown as AudioBuffer)
  }

  createBufferSource(): AudioBufferSourceNode {
    const node: FakeSourceNode = {
      buffer: null,
      connect: vi.fn<(node: unknown) => void>(),
      start: vi.fn<() => void>(),
      onended: null,
    }
    this._sourceNodes.push(node)
    return node as unknown as AudioBufferSourceNode
  }

  createAnalyser(): AnalyserNode {
    const analyser: FakeAnalyser = {
      fftSize: 256,
      smoothingTimeConstant: 0.3,
      frequencyBinCount: 128,
      connect: vi.fn<(node: unknown) => void>(),
      getByteFrequencyData: vi.fn<(arr: Uint8Array) => void>((arr) => {
        arr.fill(0)
      }),
    }
    return analyser as unknown as AnalyserNode
  }

  close(): Promise<void> {
    this.state = 'closed'
    return Promise.resolve()
  }
}

vi.stubGlobal('AudioContext', FakeAudioContext)
vi.stubGlobal('webkitAudioContext', FakeAudioContext)

import { webrtcService, type VoiceServerMessage } from '@/services/webrtcService'

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

    let receivedMessage: VoiceServerMessage | null = null
    webrtcService.setOnMessage((msg) => {
      receivedMessage = msg
    })

    const event = { data: ttsMessage } as MessageEvent
    // handleWebSocketMessage 是私有方法，测试里显式断言出签名（比 as any 安全）
    const internals = webrtcService as unknown as {
      handleWebSocketMessage(e: MessageEvent): void
    }
    internals.handleWebSocketMessage(event)

    expect(receivedMessage).not.toBeNull()
    const received = receivedMessage as unknown as VoiceServerMessage
    expect(received.type).toBe('tts_audio')
    expect(received.audio).toBe('AAAA')
  })

  it('playTtsAudio 应解码 base64 音频并通过 AudioContext 播放', async () => {
    const { playTtsAudio } = await import('@/services/webrtcService')

    const fakeAudioCtx = new FakeAudioContext()

    // 构造一小段有效 base64（WAV 空文件头）
    const base64Audio = 'UklGRiQAAABXQVZFZm10IBAAAAABAAEAIlYAAESsAAACABAAZGF0YQAAAAA='

    await playTtsAudio(base64Audio, fakeAudioCtx as unknown as AudioContext)

    // 断言：音频被解码
    expect(fakeAudioCtx._buffers.length).toBe(1)

    // 断言：创建了播放节点并调用了 start
    expect(fakeAudioCtx._sourceNodes.length).toBe(1)
    expect(fakeAudioCtx._sourceNodes[0]?.start).toHaveBeenCalled()
  })
})
