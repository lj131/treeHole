import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useWidgetStore } from '@/stores/widgetStore'

const KEY = 'widget_auto_launch'

/** 装一个假的 window.widgetApi，返回 { api, calls } 供断言 */
function installWidgetApi(overrides: Record<string, unknown> = {}) {
  const calls: Record<string, unknown[]> = {}
  const rec =
    (name: string) =>
    (...args: unknown[]) => {
      calls[name] = calls[name] ? [...calls[name], args] : [args]
      return Promise.resolve()
    }
  const api = {
    setSize: rec('setSize'),
    toggleAlwaysOnTop: vi.fn<(_: boolean) => Promise<boolean>>(async () => true),
    hide: rec('hide'),
    show: rec('show'),
    toggleVisibility: rec('toggleVisibility'),
    getAutoLaunch: vi.fn<(_: boolean) => Promise<boolean>>(async () => false),
    setAutoLaunch: vi.fn<(_: boolean) => Promise<boolean>>(async () => true),
    dragStart: () => {},
    dragMove: () => {},
    dragEnd: () => {},
    ...overrides,
  }
  ;(window as unknown as { widgetApi?: unknown }).widgetApi = api
  return { api, calls }
}

describe('widgetStore 开机自启', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    delete (window as unknown as { widgetApi?: unknown }).widgetApi
  })

  afterEach(() => {
    localStorage.clear()
    delete (window as unknown as { widgetApi?: unknown }).widgetApi
  })

  it('默认关闭（不打扰用户）', () => {
    const w = useWidgetStore()
    expect(w.autoLaunch).toBe(false)
  })

  it('setAutoLaunch 成功 → 状态与 localStorage 都更新', async () => {
    installWidgetApi({ setAutoLaunch: vi.fn<(_: boolean) => Promise<boolean>>(async () => true) })
    const w = useWidgetStore()

    await w.setAutoLaunch(true)

    expect(w.autoLaunch).toBe(true)
    expect(localStorage.getItem(KEY)).toBe('1')
  })

  it('以系统返回的实际结果为准（被策略否决时不能自我欺骗）', async () => {
    // 系统说"没设上"，即使我们请求的是 true
    installWidgetApi({ setAutoLaunch: vi.fn<(_: boolean) => Promise<boolean>>(async () => false) })
    const w = useWidgetStore()

    const actual = await w.setAutoLaunch(true)

    expect(actual).toBe(false)
    expect(w.autoLaunch).toBe(false)          // 状态反映事实，不是期望
    expect(localStorage.getItem(KEY)).toBe('0')
  })

  it('宿主抛错 → 回滚到之前的值并向上抛（UI 能提示失败）', async () => {
    // 第一次成功设成 true；之后宿主开始报错 → 要回滚到 true 并抛出
    const setAutoLaunch = vi.fn<(_: boolean) => Promise<boolean>>()
    setAutoLaunch.mockResolvedValueOnce(true).mockRejectedValueOnce(new Error('权限不足'))
    installWidgetApi({ setAutoLaunch })
    const w = useWidgetStore()

    await w.setAutoLaunch(true)
    expect(w.autoLaunch).toBe(true)

    await expect(w.setAutoLaunch(false)).rejects.toThrow('开机自启设置失败')
    expect(w.autoLaunch).toBe(true)             // 回滚
    expect(localStorage.getItem(KEY)).toBe('1')  // localStorage 也回滚
  })

  it('syncAutoLaunch 以系统值为准（即使 localStorage 说是开）', async () => {
    localStorage.setItem(KEY, '1')              // 上次的期望：开
    installWidgetApi({ getAutoLaunch: vi.fn<(_: boolean) => Promise<boolean>>(async () => false) })  // 系统：关
    const w = useWidgetStore()

    await w.syncAutoLaunch()

    expect(w.autoLaunch).toBe(false)            // 系统赢
    expect(localStorage.getItem(KEY)).toBe('0')
  })

  it('浏览器环境（无 widgetApi）syncAutoLaunch 不抛，保留 localStorage 值', async () => {
    localStorage.setItem(KEY, '1')
    const w = useWidgetStore()

    await expect(w.syncAutoLaunch()).resolves.toBeUndefined()
    expect(w.autoLaunch).toBe(true)
  })

  it('toggleAutoLaunch 在开/关之间切换', async () => {
    installWidgetApi()
    const w = useWidgetStore()

    expect(await w.toggleAutoLaunch()).toBe(true)
    expect(await w.toggleAutoLaunch()).toBe(true)  // 假 api 恒返回 true
  })

  it('getAutoLaunch/setAutoLaunch 确实被调用（不是只改本地状态）', async () => {
    const { api } = installWidgetApi()
    const w = useWidgetStore()

    await w.syncAutoLaunch()
    await w.setAutoLaunch(true)

    expect(api.getAutoLaunch).toHaveBeenCalledTimes(1)
    expect(api.setAutoLaunch).toHaveBeenCalledWith(true)
  })
})
