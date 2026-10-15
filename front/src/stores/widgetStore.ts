import { defineStore } from 'pinia'

type WidgetMode = 'compact' | 'expanded'

const PROACTIVE_ENABLED_KEY = 'widget_proactive_enabled'
const ALWAYS_ON_TOP_KEY = 'widget_always_on_top'
const AUTO_LAUNCH_KEY = 'widget_auto_launch'

function readBool(key: string, fallback: boolean) {
  try {
    const value = localStorage.getItem(key)
    if (value === null) return fallback
    return value === '1'
  } catch {
    return fallback
  }
}

function writeBool(key: string, value: boolean) {
  try {
    localStorage.setItem(key, value ? '1' : '0')
  } catch {
    // ignore
  }
}

export const useWidgetStore = defineStore('widget', {
  state: () => ({
    mode: 'compact' as WidgetMode,
    lastBubble: '',
    proactiveEnabled: readBool(PROACTIVE_ENABLED_KEY, true),
    alwaysOnTop: readBool(ALWAYS_ON_TOP_KEY, true),
    /** 开机自启。localStorage 只是"上次的期望"，权威在系统设置（见 syncAutoLaunch） */
    autoLaunch: readBool(AUTO_LAUNCH_KEY, false),
    lastProactiveAt: '',
  }),

  actions: {
    setMode(mode: WidgetMode) {
      this.mode = mode
      window.widgetApi?.setSize(mode)
    },

    toggleMode() {
      this.setMode(this.mode === 'compact' ? 'expanded' : 'compact')
    },

    setBubble(message: string) {
      this.lastBubble = message
      this.lastProactiveAt = new Date().toISOString()
    },

    clearBubble() {
      this.lastBubble = ''
    },

    setProactiveEnabled(enabled: boolean) {
      this.proactiveEnabled = enabled
      writeBool(PROACTIVE_ENABLED_KEY, enabled)
    },

    async toggleAlwaysOnTop() {
      const next = await window.widgetApi?.toggleAlwaysOnTop()
      if (typeof next === 'boolean') {
        this.alwaysOnTop = next
        writeBool(ALWAYS_ON_TOP_KEY, next)
      }
    },

    /**
     * 开机自启。
     *
     * localStorage 只是"上次的期望"，**系统里的真实状态才是权威** ——
     * 用户可能在系统设置里直接改掉。所以启动时要 `syncAutoLaunch()` 校准。
     *
     * 浏览器环境（没有 widgetApi）下读写 localStorage 即可，不影响使用。
     */
    async syncAutoLaunch() {
      const systemValue = await window.widgetApi?.getAutoLaunch()
      this.autoLaunch = typeof systemValue === 'boolean' ? systemValue : this.autoLaunch
      writeBool(AUTO_LAUNCH_KEY, this.autoLaunch)
    },

    async setAutoLaunch(enabled: boolean) {
      const previous = this.autoLaunch
      // 先乐观更新，失败再回滚——否则按钮会像卡住一样
      this.autoLaunch = enabled
      writeBool(AUTO_LAUNCH_KEY, enabled)
      try {
        const actual = await window.widgetApi?.setAutoLaunch(enabled)
        // 以系统返回的实际结果为准（可能被组策略/权限否决）
        this.autoLaunch = typeof actual === 'boolean' ? actual : enabled
        writeBool(AUTO_LAUNCH_KEY, this.autoLaunch)
      } catch {
        this.autoLaunch = previous
        writeBool(AUTO_LAUNCH_KEY, previous)
        throw new Error('开机自启设置失败')
      }
      return this.autoLaunch
    },

    async toggleAutoLaunch() {
      return this.setAutoLaunch(!this.autoLaunch)
    },
  },
})
