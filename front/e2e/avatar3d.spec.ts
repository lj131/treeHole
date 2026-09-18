import { test, expect, type Page } from '@playwright/test'

/**
 * 3D 角色模型端到端验证（需要后端在 127.0.0.1:8000 运行，且目标角色已绑定模型）。
 *
 * 覆盖：真实 VRM 在浏览器里能加载出 WebGL 画面（不是降级静态头像）、
 *       角色页 3D 配置弹窗能读回后端配置。
 *
 * 若运行环境没有 WebGL（部分 headless 容器），用例自动跳过而不是误报失败。
 */
const API_BASE = process.env.E2E_API_BASE || 'http://127.0.0.1:8000'
const CHAR_ID = process.env.E2E_CHAR_ID || 'linwan'

async function loginAsAdmin(page: Page): Promise<string | null> {
  try {
    const res = await page.request.post(`${API_BASE}/auth/login`, {
      data: { username: 'admin', password: 'admin123' },
      timeout: 5_000,
    })
    if (!res.ok()) return null
    const body = (await res.json()) as { token?: string }
    if (!body.token) return null
    await page.addInitScript((token: string) => {
      localStorage.setItem('auth_token', token)
    }, body.token)
    return body.token
  } catch {
    // CI 里没有后端进程 → 连接失败，用例跳过而不是报红
    return null
  }
}

async function fetchModelConfig(
  page: Page,
  token: string,
): Promise<{ url?: string } | null> {
  try {
    const res = await page.request.get(`${API_BASE}/character/model?character_id=${CHAR_ID}`, {
      headers: { Authorization: `Bearer ${token}` },
      timeout: 5_000,
    })
    if (!res.ok()) return null
    const body = (await res.json()) as { model3d?: { url?: string } | null }
    return body.model3d ?? null
  } catch {
    return null
  }
}

async function hasWebGL(page: Page): Promise<boolean> {
  return page.evaluate(() => {
    const canvas = document.createElement('canvas')
    return !!(canvas.getContext('webgl2') || canvas.getContext('webgl'))
  })
}

test.describe('3D 角色模型', () => {
  test('聊天页角色卡渲染真实 3D 模型（非静态降级）', async ({ page }) => {
    const token = await loginAsAdmin(page)
    test.skip(!token, `后端不可用或管理员登录失败：${API_BASE}`)

    await page.goto('/#/chat')
    await page.waitForLoadState('domcontentloaded')

    const webgl = await hasWebGL(page)
    test.skip(!webgl, '当前浏览器/环境没有 WebGL，跳过 3D 渲染断言')

    // 角色卡挂载 3D 画布
    const canvas = page.locator('.portrait-3d-slot canvas').first()
    await expect(canvas).toBeVisible({ timeout: 30_000 })

    // 等模型加载 + 首帧渲染
    await page.waitForTimeout(6_000)

    // 未降级为静态头像
    await expect(page.locator('.portrait-3d-slot .static-portrait')).toHaveCount(0)

    // 画面有实际内容（纯色/空白截图的字节数会非常小）
    const shot = await canvas.screenshot()
    expect(shot.byteLength).toBeGreaterThan(2_000)
  })

  test('角色页 3D 弹窗读回后端模型配置', async ({ page }) => {
    const token = await loginAsAdmin(page)
    test.skip(!token, `后端不可用或管理员登录失败：${API_BASE}`)

    const model = await fetchModelConfig(page, token!)
    test.skip(!model?.url, `角色 ${CHAR_ID} 未绑定 3D 模型，跳过`)

    await page.goto('/#/characters')
    await expect(page.locator('.model-char-btn').first()).toBeVisible({ timeout: 20_000 })
    await page.locator('.model-char-btn').first().click()

    await expect(page.locator('.model-modal')).toBeVisible()
    await expect(page.locator('.model-preview-tag')).toContainText(/已绑定/i)
    await expect(page.locator('.model-modal')).toContainText('缩放')
    await expect(page.locator('.model-modal')).toContainText('相机距离')
  })
})
