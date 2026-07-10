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

export const updateProfile = (data: { nickname?: string; avatar?: string }) => {
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

export const uploadAvatar = async (file: File) => {
  const API_BASE_URL = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000'
  const token = localStorage.getItem('auth_token')
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(`${API_BASE_URL}/auth/avatar`, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  })
  if (!res.ok) {
    throw new Error(`Upload failed: ${res.status}`)
  }
  return res.json() as Promise<{ avatar: string }>
}

export const getMyUsage = (days?: number) => {
  const qs = days ? `?days=${days}` : ''
  return request<UsageSummary>(`/auth/usage${qs}`)
}
