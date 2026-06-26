import { defineStore } from 'pinia'

type WidgetMode = 'compact' | 'expanded'

const PROACTIVE_ENABLED_KEY = 'widget_proactive_enabled'
const ALWAYS_ON_TOP_KEY = 'widget_always_on_top'

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
  },
})
