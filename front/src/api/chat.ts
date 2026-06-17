import { request } from './request'
import type { ChatMessage } from '@/types/api'

export interface ChatResponse {
  reply?: string
  favorability?: number
  error?: string
}

export const sendChat = (message: string) => {
  return request<ChatResponse>('/chat', {
    method: 'POST',
    body: JSON.stringify({ message }),
  })
}

// SSE 流式回调
export interface StreamCallbacks {
  onToken: (token: string) => void
  onDone: (favorability: number) => void
  onError: (error: string) => void
}

/**
 * 流式发送聊天消息（SSE），逐 token 回调。
 * 返回 abort 函数用于取消请求。
 * 不支持 ReadableStream 的环境将降级为普通 sendChat。
 */
export const sendChatStream = (
  message: string,
  callbacks: StreamCallbacks,
): { abort: () => void } => {
  const API_BASE_URL = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000'
  const controller = new AbortController()

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }
  try {
    const token = localStorage.getItem('auth_token')
    if (token) headers['Authorization'] = `Bearer ${token}`
  } catch {
    /* ignore */
  }

  fetch(`${API_BASE_URL}/chat/stream`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ message }),
    signal: controller.signal,
  })
    .then(async (res) => {
      if (!res.ok) {
        const text = await res.text().catch(() => '')
        callbacks.onError(`API Error ${res.status}: ${text}`)
        return
      }

      const reader = res.body?.getReader()
      if (!reader) {
        callbacks.onError('浏览器不支持流式读取')
        return
      }

      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6))
              if (data.token) {
                callbacks.onToken(data.token)
              } else if (data.done) {
                callbacks.onDone(data.favorability ?? 50)
              } else if (data.error) {
                callbacks.onError(data.error)
              }
            } catch {
              /* 解析失败跳过该行 */
            }
          }
        }
      }
    })
    .catch((err) => {
      if (err.name !== 'AbortError') {
        callbacks.onError(err.message || '发送失败')
      }
    })

  return { abort: () => controller.abort() }
}

export const getHistory = () => {
  return request<{ messages: ChatMessage[] }>('/history')
}

export const getChatSummary = () => {
  return request<{ chat_summary: string[] }>('/chat-summary')
}

export const getProactiveMessage = () => {
  return request<{ message: string | null }>('/proactive-message')
}

export const getProactive = () => {
  return request<{ message: string | null }>('/proactive')
}

export const getCaringMessage = () => {
  return request<{ message: string | null }>('/caring-message')
}
