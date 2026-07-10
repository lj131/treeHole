import { test, expect } from '@playwright/test'

/**
 * 烟雾测试：不依赖后端，只验证前端 shell 能挂载、静态首屏渲染、路由跳转可用。
 * 后端相关 API 调用失败不影响这些断言（API 失败由运行时降级处理，不在烟雾测试范围内）。
 */
test.describe('app smoke', () => {
  test('首屏挂载并显示 hero 文案', async ({ page }) => {
    await page.goto('/')

    // 标题
    await expect(page).toHaveTitle(/TreeHole/)

    // HomeView 静态 hero 文案（不依赖后端）
    await expect(page.locator('.hero-title')).toContainText('AI Test Project')

    // 导航栏品牌存在
    await expect(page.locator('.nav-brand .brand-name')).toContainText('AI Test')
  })

  test('点击「开始对话」跳转到聊天页', async ({ page }) => {
    await page.goto('/')

    await page.getByRole('link', { name: /开始对话/ }).click()

    // hash 路由 → URL 含 #/chat
    await expect(page).toHaveURL(/#\/chat/)

    // Chat 视图挂载（至少页面没白屏：body 内有内容）
    await expect(page.locator('body')).not.toBeEmpty()
  })

  test('角色管理页可达', async ({ page }) => {
    await page.goto('/#/characters')
    // 不 404、页面挂载
    await expect(page.locator('body')).not.toBeEmpty()
  })
})
