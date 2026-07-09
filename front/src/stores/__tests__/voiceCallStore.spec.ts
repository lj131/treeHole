/**
 * VoiceCallStore 测试 —— endCall 状态重置（成功 & 异常两条路径）。
 *
 * 注意：当前 store 实际暴露的字段是 isCalling / isConnected / isConnecting /
 * callId / callDuration / error / micLevel / callStatus（computed）等，
 * 不存在 audioLevel / networkQuality / connectionState —— 本测试按真实 API 写。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useVoiceCallStore } from '@/stores/voiceCallStore'

// Mock webrtcService（含 store 顶层 import 的 setOnTtsPlayStateChange）
vi.mock('@/services/webrtcService', () => ({
  webrtcService: {
    init: vi.fn<() => Promise<void>>().mockResolvedValue(undefined),
    startVoiceCall: vi.fn<() => Promise<string>>().mockResolvedValue('call_initiated'),
    endVoiceCall: vi.fn<() => Promise<void>>().mockResolvedValue(undefined),
    setMuted: vi.fn<(m: boolean) => void>(),
    setSpeakerEnabled: vi.fn<(e: boolean) => void>(),
    interrupt: vi.fn<() => void>(),
    setOnWsOpen: vi.fn<(cb: () => void) => void>(),
    setOnWsClose: vi.fn<(cb: () => void) => void>(),
    setOnMicLevelChange: vi.fn<(cb: (l: number) => void) => void>(),
    setOnError: vi.fn<(cb: (e: Error) => void) => void>(),
    setOnCallEnd: vi.fn<(cb: () => void) => void>(),
  },
  setOnTtsPlayStateChange: vi.fn<(cb: ((p: boolean) => void) | null) => void>(),
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
    store.callDuration = 120
    store.error = 'some error'

    const ok = await store.endCall()

    expect(ok).toBe(true)
    expect(store.isCalling).toBe(false)
    expect(store.isConnected).toBe(false)
    expect(store.isConnecting).toBe(false)
    expect(store.callId).toBeNull()
    expect(store.callDuration).toBe(0)
    // error 不在成功路径清空（只由 clearError 清），这里不断言它
  })

  it('endCall 异常后也重置状态字段并返回 false', async () => {
    const { webrtcService } = await import('@/services/webrtcService')
    // 模拟 endVoiceCall 抛异常
    vi.mocked(webrtcService.endVoiceCall).mockRejectedValueOnce(new Error('连接已断开'))

    const store = useVoiceCallStore()

    store.isCalling = true
    store.isConnected = true
    store.callId = 'test-call-456'
    store.callDuration = 300
    store.error = 'old error'

    const ok = await store.endCall()

    // 即使异常也应重置并返回 false
    expect(ok).toBe(false)
    expect(store.isCalling).toBe(false)
    expect(store.isConnected).toBe(false)
    expect(store.isConnecting).toBe(false)
    expect(store.callId).toBeNull()
    expect(store.callDuration).toBe(0)
  })
})
