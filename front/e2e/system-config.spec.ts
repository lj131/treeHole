import { test, expect, type Page } from '@playwright/test'

/**
 * 系统配置页（`/admin`）。
 *
 * 需要后端在跑；没有则整体跳过（CI 里没有后端进程）。
 */
const API_BASE = process.env.E2E_API_BASE || 'http://127.0.0.1:8000'

async function adminToken(page: Page): Promise<string | null> {
  try {
    const res = await page.request.post(`${API_BASE}/auth/login`, {
      data: { username: 'admin', password: 'admin123' },
      timeout: 5_000,
    })
    if (!res.ok()) return null
    return ((await res.json()) as { token?: string }).token ?? null
  } catch {
    return null
  }
}

test.describe('系统配置页', () => {
  test('管理员直接打开 /admin（含刷新路径）能看到系统配置区', async ({ page }) => {
    const token = await adminToken(page)
    test.skip(!token, `后端不可用：${API_BASE}`)
    await page.addInitScript((t: string) => localStorage.setItem('auth_token', t), token!)

    // 直接落到 /admin —— 这是一条**回归用例**：
    // 用户信息是 App.vue 的 onMounted 里异步拉的，而路由守卫跑在它之前。
    // 守卫若不同步补一次 fetchMe，管理员刷新 /admin 会被弹回首页。
    await page.goto('/#/admin')
    await expect(page.locator('.cfg-groups')).toBeVisible({ timeout: 20_000 })
    expect(page.url()).toContain('/admin')

    // schema 驱动的字段要真的渲染出来
    expect(await page.locator('.cfg-row').count()).toBeGreaterThan(0)
    expect(await page.locator('.cfg-group').count()).toBeGreaterThan(0)
  })

  test('非管理员访问 /admin 被弹回首页', async ({ page }) => {
    const token = await adminToken(page)
    test.skip(!token, `后端不可用：${API_BASE}`)

    const name = `e2e_cfg_${Date.now().toString(36)}`
    const pwd = 'pass1234'
    let userToken: string | null = null
    try {
      const reg = await page.request.post(`${API_BASE}/auth/register`, {
        data: { username: name, password: pwd },
        timeout: 5_000,
      })
      if (!reg.ok()) test.skip(true, '注册失败，跳过')
      const uid = ((await reg.json()) as { user: { id: number } }).user.id
      await page.request.post(`${API_BASE}/auth/admin/approve/${uid}`, {
        headers: { Authorization: `Bearer ${token}` },
        timeout: 5_000,
      })
      const lg = await page.request.post(`${API_BASE}/auth/login`, {
        data: { username: name, password: pwd },
        timeout: 5_000,
      })
      userToken = ((await lg.json()) as { token?: string }).token ?? null
    } catch {
      test.skip(true, '创建普通用户失败，跳过')
    }
    test.skip(!userToken, '普通用户登录失败，跳过')

    await page.addInitScript((t: string) => localStorage.setItem('auth_token', t), userToken!)
    await page.goto('/#/admin')
    // 被守卫拦下 → 回首页（hero 文案是首页的标志）
    await expect(page.locator('.hero, .home-page, h1').first()).toBeVisible({ timeout: 20_000 })
    await expect(page.locator('.cfg-groups')).toHaveCount(0)
  })

  test('密钥类配置不出现在页面上', async ({ page }) => {
    const token = await adminToken(page)
    test.skip(!token, `后端不可用：${API_BASE}`)
    await page.addInitScript((t: string) => localStorage.setItem('auth_token', t), token!)

    await page.goto('/#/admin')
    await expect(page.locator('.cfg-groups')).toBeVisible({ timeout: 20_000 })

    const text = (await page.locator('.cfg-groups').innerText()).toLowerCase()
    for (const forbidden of ['jwt', 'secret', 'password', 'api_key', 'apikey']) {
      expect(text).not.toContain(forbidden)
    }
  })
})
