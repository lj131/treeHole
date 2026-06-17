import { request } from './request'
import type { User, UsageSummary } from '@/types/api'

export const listUsers = () => {
  return request<{ users: User[] }>('/auth/admin/users')
}

export const updateQuota = (userId: number, data: { daily_chat_limit?: number; character_limit?: number }) => {
  return request<{ message: string; user: User }>(`/auth/admin/quota/${userId}`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export const getUserUsage = (userId: number) => {
  return request<UsageSummary>(`/auth/admin/usage/${userId}`)
}
