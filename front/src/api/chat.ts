import { request } from './request'
import type { ChatMessage, MemoryEcho } from '@/types/api'

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
  /** 记忆回响（E3）：这轮参考了哪些记忆。**在首个 token 之前**回调一次。 */
  onMemories?: (memories: MemoryEcho[]) => void
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
              // 用 Array.isArray 而不是 `if (data.memories)` —— 空数组在 JS 里是
              // truthy，但**空数组是有意义的**（"这轮没参考记忆"），
              // 不能被 token/done 分支抢走。
              if (Array.isArray(data.memories)) {
                callbacks.onMemories?.(data.memories as MemoryEcho[])
              } else if (data.token) {
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

/**
 * 把一段文本合成为当前角色音色的语音，返回音频 Blob。
 *
 * **不走 `request()`**：它只认 JSON 响应，而这里要收音频字节。
 * 失败时把后端的 `detail` 提出来 —— 引擎不可用的原因（如上游 403）必须让用户看见，
 * 不能塌缩成一句"播放失败"。
 */
export const synthesizeSpeech = async (text: string, characterId?: string): Promise<Blob> => {
  const base = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000'
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  try {
    const token = localStorage.getItem('auth_token')
    if (token) headers['Authorization'] = `Bearer ${token}`
  } catch {
    // localStorage 不可用，忽略
  }

  const res = await fetch(`${base}/chat/tts`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ text, character_id: characterId }),
  })
  if (!res.ok) {
    let detail = ''
    try {
      detail = ((await res.json()) as { detail?: string })?.detail || ''
    } catch {
      // 响应不是 JSON（网关错误页之类），忽略
    }
    throw new Error(detail || `朗读失败（HTTP ${res.status}）`)
  }
  return res.blob()
}
