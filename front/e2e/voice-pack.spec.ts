import { test, expect, type Page } from '@playwright/test'

/**
 * 语音包设置区块的权限与可见性（需要后端在 127.0.0.1:8000 运行）。
 *
 * 核心约束：语音包是**全局资源，仅管理员可操作** —— 所以这里同时验证
 * 「管理员看得到」和「普通用户看不到」两面。没有后端时自动跳过而不是报红。
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
    // CI 里没有后端进程 → 连接失败，用例跳过而不是报红
    return null
  }
}

async function injectToken(page: Page, token: string) {
  await page.addInitScript((t: string) => {
    localStorage.setItem('auth_token', t)
  }, token)
}

test.describe('语音包设置区块', () => {
  test('管理员在设置页能看到语音包区块', async ({ page }) => {
    const token = await adminToken(page)
    test.skip(!token, `后端不可用或管理员登录失败：${API_BASE}`)
    await injectToken(page, token!)

    await page.goto('/#/settings')
    await expect(page.locator('.card:has(.vp-layout)')).toBeVisible({ timeout: 20_000 })
    await expect(page.locator('.vp-badge')).toHaveText('仅管理员')
    // 区块标题与角色音色列表都要在
    await expect(page.locator('.vp-col-title').first()).toContainText('语音包库')
    await expect(page.locator('.vp-col-title').nth(1)).toContainText('角色音色')

    // 新建表单能展开，且音色下拉有真实数据（不是空列表）
    await page.locator('.vp-col-head button').first().click()
    await expect(page.locator('.vp-form')).toBeVisible()
    const voiceOptions = page.locator('.vp-form select').nth(1).locator('option')
    expect(await voiceOptions.count()).toBeGreaterThan(0)
  })

  test('普通用户在设置页看不到语音包区块', async ({ page }) => {
    const token = await adminToken(page)
    test.skip(!token, `后端不可用或管理员登录失败：${API_BASE}`)

    // 注册 + 审批一个普通用户
    const name = `e2e_voice_${Date.now().toString(36)}`
    const pwd = 'pass1234'
    let userToken: string | null = null
    try {
      const reg = await page.request.post(`${API_BASE}/auth/register`, {
        data: { username: name, password: pwd },
        timeout: 5_000,
      })
      if (!reg.ok()) test.skip(true, '注册失败，跳过')
      const userId = ((await reg.json()) as { user: { id: number } }).user.id

      await page.request.post(`${API_BASE}/auth/admin/approve/${userId}`, {
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

    await injectToken(page, userToken!)
    await page.goto('/#/settings')
    // 等设置页真正渲染出来，避免"还没加载完所以没元素"的假通过
    await expect(page.locator('.settings-grid')).toBeVisible({ timeout: 20_000 })
    await expect(page.locator('.vp-layout')).toHaveCount(0)
    await expect(page.locator('.vp-badge')).toHaveCount(0)
  })
})
