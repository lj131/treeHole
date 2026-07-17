import { request } from './request'
import type {
  Character,
  CharacterBrief,
  CharacterCreateInput,
  CharacterState,
  Relationship,
} from '@/types/api'

export const getFavorability = () => {
  return request<{ favorability: number }>('/favorability')
}

export const getCharacters = () => {
  return request<{ characters: CharacterBrief[] }>('/characters')
}

export const switchCharacter = (characterId: string) => {
  return request<{ message: string }>('/character/switch', {
    method: 'POST',
    body: JSON.stringify({ character_id: characterId }),
  })
}

export const getCurrentCharacter = () => {
  return request<{ character: Character }>('/character/current')
}

/** 关键词 + AI 生成新角色，返回完整角色对象 */
export const createCharacter = (data: CharacterCreateInput) => {
  return request<{ character: Character } | { error: string }>('/character/create', {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export const getCharacterState = () => {
  return request<{ state: CharacterState }>('/character/state')
}

export const getRelationship = () => {
  return request<{ relationship: Relationship; favorability: number }>('/relationship')
}

/** 删除角色（仅创建者或 admin） */
export const deleteCharacter = (characterId: string) => {
  return request<{ message: string }>('/character/delete', {
    method: 'POST',
    body: JSON.stringify({ character_id: characterId }),
  })
}

/** @deprecated 后端未实现，请使用 getCurrentCharacter */
export const getCharacterName = async () => {
  const { character } = await getCurrentCharacter()
  return { name: character.name }
}

/** @deprecated 后端未实现 */
export const setCharacterName = (_name: string) => {
  return Promise.reject(new Error('后端未实现 POST /character/name 接口'))
}

/** 上传当前角色头像，返回新的 avatar URL */
export const uploadCharacterAvatar = async (file: File) => {
  const formData = new FormData()
  formData.append('file', file)
  const base = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000'
  const headers: Record<string, string> = {}
  try {
    const token = localStorage.getItem('auth_token')
    if (token) {
      headers['Authorization'] = `Bearer ${token}`
    }
  } catch {
    // localStorage 不可用，忽略
  }
  const res = await fetch(`${base}/character/avatar`, {
    method: 'POST',
    headers,
    body: formData,
  })
  if (!res.ok) {
    const err = await res.json()
    throw new Error(err.error || '上传失败')
  }
  return res.json() as Promise<{ message: string; avatar: string }>
}

export { request }
