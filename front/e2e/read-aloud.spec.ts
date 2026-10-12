import { test, expect, type Page } from '@playwright/test'

/**
 * 聊天页朗读。
 *
 * 需要后端（127.0.0.1:8000）在跑；没有则整体跳过（CI 里没有后端进程）。
 *
 * 合成请求被**拦截并回一段自造的真实 WAV** —— 这样：
 * 1. 不依赖 edge-tts 云端（它的合成端点目前上游 403）；
 * 2. 不需要 LLM 也能验证「播放 → 嘴型 → 复位」这条状态机。
 */
const API_BASE = process.env.E2E_API_BASE || 'http://127.0.0.1:8000'

/** 造一段 1 秒 440Hz 正弦 WAV —— decodeAudioData 能直接解，不需要二进制 fixture */
function makeWav(seconds = 1, sampleRate = 8000, freq = 440): Buffer {
  const n = Math.floor(seconds * sampleRate)
  const dataSize = n * 2
  const buf = Buffer.alloc(44 + dataSize)
  buf.write('RIFF', 0)
  buf.writeUInt32LE(36 + dataSize, 4)
  buf.write('WAVE', 8)
  buf.write('fmt ', 12)
  buf.writeUInt32LE(16, 16)
  buf.writeUInt16LE(1, 20) // PCM
  buf.writeUInt16LE(1, 22) // 单声道
  buf.writeUInt32LE(sampleRate, 24)
  buf.writeUInt32LE(sampleRate * 2, 28)
  buf.writeUInt16LE(2, 32)
  buf.writeUInt16LE(16, 34)
  buf.write('data', 36)
  buf.writeUInt32LE(dataSize, 40)
  for (let i = 0; i < n; i++) {
    const v = Math.round(32767 * 0.3 * Math.sin((2 * Math.PI * freq * i) / sampleRate))
    buf.writeInt16LE(v, 44 + i * 2)
  }
  return buf
}

async function login(page: Page): Promise<boolean> {
  try {
    const res = await page.request.post(`${API_BASE}/auth/login`, {
      data: { username: 'admin', password: 'admin123' },
      timeout: 5_000,
    })
    if (!res.ok()) return false
    const { token } = (await res.json()) as { token?: string }
    if (!token) return false
    await page.addInitScript((t: string) => localStorage.setItem('auth_token', t), token)
    return true
  } catch {
    return false // CI 无后端 → 连接失败，跳过而不是报红
  }
}

test.describe('聊天页朗读', () => {
  test('开关可见、能切换、能持久化', async ({ page }) => {
    test.skip(!(await login(page)), `后端不可用：${API_BASE}`)

    await page.goto('/#/chat')
    const toggle = page.locator('.read-aloud-toggle')
    await expect(toggle).toBeVisible({ timeout: 20_000 })
    await expect(toggle).not.toHaveClass(/active/)

    await toggle.click()
    await expect(toggle).toHaveClass(/active/)
    expect(await page.evaluate(() => localStorage.getItem('chat_read_aloud_enabled'))).toBe('true')

    await toggle.click()
    await expect(toggle).not.toHaveClass(/active/)
    expect(await page.evaluate(() => localStorage.getItem('chat_read_aloud_enabled'))).toBe('false')
  })

  test('点朗读后进入播放态、嘴型有响应、播完复位', async ({ page }) => {
    test.skip(!(await login(page)), `后端不可用：${API_BASE}`)

    await page.route('**/chat/tts', (route) =>
      route.fulfill({ status: 200, contentType: 'audio/wav', body: makeWav() }),
    )

    await page.goto('/#/chat')
    await expect(page.locator('.chat-page')).toBeVisible({ timeout: 20_000 })
    await page.waitForTimeout(2500)

    const row = page.locator('.msg-row.assistant').first()
    test.skip(
      (await row.count()) === 0,
      '当前没有助手消息（需要真实 LLM 回复），跳过播放链路验证',
    )

    // 通过 Vite 模块图拿到同一个模块实例，订阅嘴型强度
    await page.evaluate(async () => {
      const mod = await import('/src/services/webrtcService.ts')
      ;(window as unknown as { __lipPeak: number }).__lipPeak = 0
      mod.subscribeTtsLipSync((i: number) => {
        const w = window as unknown as { __lipPeak: number }
        if (i > w.__lipPeak) w.__lipPeak = i
      })
    })

    await row.hover()
    const btn = row.locator('.speak-btn')
    await expect(btn).toBeVisible({ timeout: 10_000 })
    await expect(btn).toHaveText('▶')

    await btn.click()
    // 合成中 → 播放中
    await expect(btn).toHaveText('■', { timeout: 10_000 })
    // 嘴型强度要**轮询**着等：按钮变「■」只代表播放已开始，
    // lip-sync 是在下一个动画帧才发出第一个强度的
    await expect
      .poll(
        () => page.evaluate(() => (window as unknown as { __lipPeak: number }).__lipPeak),
        { timeout: 5_000 },
      )
      .toBeGreaterThan(0)

    // 播完复位
    await expect(btn).toHaveText('▶', { timeout: 10_000 })
  })
})
