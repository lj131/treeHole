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

// 个人设置（当前用户自己）

export const updateProfile = (data: { nickname?: string }) => {
  return request<{ message: string; user: User }>('/auth/profile', {
    method: 'PUT',
    body: JSON.stringify(data),
  })
}

export const changePassword = (data: { old_password: string; new_password: string }) => {
  return request<{ message: string }>('/auth/change-password', {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export const uploadAvatar = (file: File) => {
  // 后端 /auth/avatar 收原始字节（file: bytes），非 multipart
  return request<{ message: string; avatar: string }>('/auth/avatar', {
    method: 'POST',
    body: file,
    headers: { 'Content-Type': file.type || 'application/octet-stream' },
  })
}

export const getMyUsage = (days = 30) => {
  return request<UsageSummary>(`/auth/usage?days=${days}`)
}
