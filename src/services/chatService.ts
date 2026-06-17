import { useChatStore } from '@/stores/chatStore'

const PROACTIVE_POLL_INTERVAL_MS = 60_000

let proactiveTimer: ReturnType<typeof setInterval> | null = null

export async function initChatService() {
  const store = useChatStore()
  await store.refreshAll()
  return store
}

export function startProactivePolling(intervalMs = PROACTIVE_POLL_INTERVAL_MS) {
  stopProactivePolling()

  const store = useChatStore()
  void store.checkProactive()

  proactiveTimer = setInterval(() => {
    void store.checkProactive()
  }, intervalMs)
}

export function stopProactivePolling() {
  if (proactiveTimer) {
    clearInterval(proactiveTimer)
    proactiveTimer = null
  }
}
