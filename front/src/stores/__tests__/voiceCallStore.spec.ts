/**
 * VoiceCallStore TDD 测试
 *
 * RED → GREEN → REFACTOR 循环：
 * 每个测试先写、确认失败、再实现、确认通过
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useVoiceCallStore } from '@/stores/voiceCallStore'

// Mock webrtcService 以避免浏览器 API 依赖
vi.mock('@/services/webrtcService', () => ({
  webrtcService: {
    init: vi.fn<() => Promise<void>>().mockResolvedValue(undefined),
    startVoiceCall: vi.fn<() => Promise<string>>().mockResolvedValue('call_initiated'),
    endVoiceCall: vi.fn<() => Promise<void>>().mockResolvedValue(undefined),
    isConnected: vi.fn<() => boolean>().mockReturnValue(false),
    setOnConnectionStateChange: vi.fn<(cb: (s: string) => void) => void>(),
    setOnAudioLevelChange: vi.fn<(cb: (l: number) => void) => void>(),
    setOnError: vi.fn<(cb: (e: Error) => void) => void>(),
    setOnMessage: vi.fn<(cb: (m: unknown) => void) => void>(),
    sendTextMessage: vi.fn<(t: string) => Promise<void>>(),
    getConnectionState: vi.fn<() => string>().mockReturnValue('disconnected'),
    setMuted: vi.fn<(m: boolean) => void>(),
    setSpeakerEnabled: vi.fn<(e: boolean) => void>(),
    isMuted: vi.fn<() => boolean>().mockReturnValue(false),
    isSpeakerOn: vi.fn<() => boolean>().mockReturnValue(true),
  },
}))

describe('voiceCallStore - endCall 状态重置', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('endCall 正常结束后重置所有状态字段', async () => {
    const store = useVoiceCallStore()

    // 设置通话中状态
    store.isCalling = true
    store.isConnected = true
    store.isConnecting = false
    store.callId = 'test-call-123'
    store.audioLevel = 75
    store.connectionState = 'connected'
    store.callDuration = 120
    store.networkQuality = 50
    store.error = 'some error'

    await store.endCall()

    expect(store.isCalling).toBe(false)
    expect(store.isConnected).toBe(false)
    expect(store.isConnecting).toBe(false)
    expect(store.callId).toBeNull()
    expect(store.audioLevel).toBe(0)
    expect(store.connectionState).toBe('disconnected')
    expect(store.callDuration).toBe(0)
    expect(store.networkQuality).toBe(95) // 重置到默认值
  })

  it('endCall 异常后也应重置所有状态字段', async () => {
    const { webrtcService } = await import('@/services/webrtcService')
    // 模拟 endVoiceCall 抛异常
    vi.mocked(webrtcService.endVoiceCall).mockRejectedValueOnce(new Error('连接已断开'))

    const store = useVoiceCallStore()

    store.isCalling = true
    store.isConnected = true
    store.callId = 'test-call-456'
    store.audioLevel = 60
    store.connectionState = 'connected' as RTCPeerConnectionState
    store.callDuration = 300
    store.networkQuality = 30
    store.error = 'old error'

    const result = await store.endCall()

    // 即使异常也应重置
    expect(result).toBe(false)
    expect(store.isCalling).toBe(false)
    expect(store.isConnected).toBe(false)
    expect(store.isConnecting).toBe(false)
    expect(store.callId).toBeNull()
    expect(store.audioLevel).toBe(0)
    expect(store.connectionState).toBe('disconnected')
    // ⚠️ 下面这个断言会失败 — catch 分支里 networkQuality 和 callDuration 没重置！
    expect(store.callDuration).toBe(0)
    expect(store.networkQuality).toBe(95)
  })
})
