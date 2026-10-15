import { describe, it, expect } from 'vitest'
import { describeRefUpload } from '@/utils/voiceRef'

describe('describeRefUpload', () => {
  it('有警告 → 警告文案 + ok=false（即使上传成功了）', () => {
    const n = describeRefUpload({
      size_kb: 42,
      duration_seconds: 2.0,
      warning: '这段音频只有 2.0 秒，偏短了，克隆出来的音色可能不像。',
    })
    expect(n.ok).toBe(false)
    expect(n.text).toContain('已上传')
    expect(n.text).toContain('偏短')
  })

  it('正常 WAV → 带时长 + 引导去试听', () => {
    const n = describeRefUpload({ size_kb: 128, duration_seconds: 8.0, warning: null })
    expect(n.ok).toBe(true)
    expect(n.text).toContain('128 KB')
    expect(n.text).toContain('8.0 秒')
    expect(n.text).toContain('试听')
  })

  it('读不出时长（非 WAV）→ 不编秒数，且不报警', () => {
    const n = describeRefUpload({ size_kb: 96, duration_seconds: null, warning: null })
    expect(n.ok).toBe(true)
    expect(n.text).toContain('96 KB')
    expect(n.text).not.toContain('秒')      // 不知道就别瞎说
    expect(n.text).toContain('试听')
  })

  it('duration 为 0 也算有效数字（不该被当成"未知"）', () => {
    const n = describeRefUpload({ size_kb: 1, duration_seconds: 0, warning: null })
    expect(n.text).toContain('0.0 秒')
  })
})
