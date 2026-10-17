/**
 * 主动来电（E7）—— 她打过来。
 *
 * 轮询 `GET /voice/incoming`，发现有来电就弹窗。
 *
 * ⚠️ **发现来电后立刻 POST answer**，原因有两个：
 *   1. 记录 consumed，刷新/多标签页不会重复弹
 *   2. 拒绝要触发后端冷却，否则她会一直打
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { answerIncomingCall, getIncomingCall, type IncomingCallInfo } from '@/api/voiceCall'

/** 轮询间隔。60s：来电不需要秒级响应，但别太钝。 */
const POLL_INTERVAL_MS = 60_000

/** 无操作自动挂断。真手机也是这样，且避免铃声一直响。 */
const AUTO_DISMISS_MS = 20_000

export const useIncomingCallStore = defineStore('incomingCall', () => {
  const incoming = ref<IncomingCallInfo | null>(null)
  const pollTimer = ref<number | null>(null)
  const dismissTimer = ref<number | null>(null)
  const ringing = ref(false)
  let inFlight = false

  function stopRinging() {
    ringing.value = false
    if (dismissTimer.value !== null) {
      clearTimeout(dismissTimer.value)
      dismissTimer.value = null
    }
  }

  /** 关掉来电界面（不反馈 —— 由 callers 显式 answer） */
  function dismiss() {
    incoming.value = null
    stopRinging()
  }

  async function answer(action: 'answered' | 'declined') {
    const current = incoming.value
    dismiss()
    if (!current) return
    try {
      await answerIncomingCall(action)
    } catch {
      /* 反馈失败不阻塞 UI（下次判定仍会基于旧记录，最多多打一次） */
    }
  }

  async function poll() {
    // 避免上一次请求还没回来又发一次（慢网络下会叠）
    if (inFlight || incoming.value) return
    inFlight = true
    try {
      const res = await getIncomingCall()
      if (res?.incoming && !incoming.value) {
        incoming.value = {
          character_id: res.character_id,
          character_name: res.character_name || res.character_id,
          reason: res.reason || '',
          greeting_hint: res.greeting_hint,
        }
        ringing.value = true
        // 无操作自动挂断
        dismissTimer.value = window.setTimeout(() => {
          void answer('declined')
        }, AUTO_DISMISS_MS)
      }
    } catch {
      /* 轮询失败安静跳过（不该因为一次网络抖动弹错误） */
    } finally {
      inFlight = false
    }
  }

  function startPolling() {
    if (pollTimer.value !== null) return
    void poll()
    pollTimer.value = window.setInterval(() => void poll(), POLL_INTERVAL_MS)
  }

  function stopPolling() {
    if (pollTimer.value !== null) {
      clearInterval(pollTimer.value)
      pollTimer.value = null
    }
    stopRinging()
  }

  return {
    incoming,
    ringing,
    dismiss,
    answer,
    poll,
    startPolling,
    stopPolling,
  }
})
