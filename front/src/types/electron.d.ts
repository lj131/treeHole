export {}

declare global {
  interface Window {
    widgetApi?: {
      setSize: (mode: 'compact' | 'expanded') => Promise<void>
      toggleAlwaysOnTop: () => Promise<boolean>
      hide: () => Promise<void>
      show: () => Promise<void>
      dragStart: () => void
      dragMove: () => void
      dragEnd: () => void
    }
  }
}
