import { request } from './request'
import type {
  Character,
  CharacterBrief,
  CharacterCreateInput,
  CharacterModelResponse,
  CharacterState,
  Model3DConfig,
  Model3DConfigPatch,
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

// ============================================================
// 3D 模型（VRM / glTF）
// ============================================================

/** 读取角色的 3D 模型配置（未配置时 model3d 为 null） */
export const getCharacterModel = (characterId?: string) => {
  const qs = characterId ? `?character_id=${encodeURIComponent(characterId)}` : ''
  return request<CharacterModelResponse>(`/character/model${qs}`)
}

/** 上传 3D 模型文件（.vrm / .glb / .gltf）并绑定到角色 */
export const uploadCharacterModel = async (file: File, characterId?: string) => {
  const formData = new FormData()
  formData.append('file', file)
  const base = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000'
  const qs = characterId ? `?character_id=${encodeURIComponent(characterId)}` : ''
  const headers: Record<string, string> = {}
  try {
    const token = localStorage.getItem('auth_token')
    if (token) {
      headers['Authorization'] = `Bearer ${token}`
    }
  } catch {
    // localStorage 不可用，忽略
  }
  const res = await fetch(`${base}/character/model${qs}`, {
    method: 'POST',
    headers,
    body: formData,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || err.error || '模型上传失败')
  }
  const body = (await res.json()) as { error?: string; model3d?: Model3DConfig }
  if (body.error) {
    throw new Error(body.error)
  }
  return body as { message: string; model3d: Model3DConfig }
}

/** 局部更新 3D 模型配置（缩放 / 相机 / 表情等） */
export const updateCharacterModelConfig = async (
  patch: Model3DConfigPatch,
  characterId?: string,
) => {
  const qs = characterId ? `?character_id=${encodeURIComponent(characterId)}` : ''
  const body = await request<{ error?: string; model3d?: Model3DConfig }>(
    `/character/model/config${qs}`,
    { method: 'POST', body: JSON.stringify(patch) },
  )
  if (body.error) {
    throw new Error(body.error)
  }
  return body as { message: string; model3d: Model3DConfig }
}

/** 移除角色的 3D 模型（回退 2D 头像） */
export const deleteCharacterModel = (characterId?: string) => {
  const qs = characterId ? `?character_id=${encodeURIComponent(characterId)}` : ''
  return request<{ message: string; model3d: null }>(`/character/model${qs}`, {
    method: 'DELETE',
  })
}
