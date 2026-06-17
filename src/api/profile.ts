import { request } from './request'
import type { UserProfile } from '@/types/api'

export const getProfile = () => {
  return request<{ profile: UserProfile }>('/profile')
}

export const saveProfile = (profile: UserProfile) => {
  return request<{ message: string }>('/profile', {
    method: 'POST',
    body: JSON.stringify({ message: JSON.stringify(profile) }),
  })
}
