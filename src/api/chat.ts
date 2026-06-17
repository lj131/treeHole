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
