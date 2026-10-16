import { request } from './request'
import type { World, WorldDigest, WorldInteractionsSnapshot } from '@/types/api'

export const getWorlds = () => {
  return request<{ worlds: World[] }>('/worlds')
}

export const switchWorld = (worldId: string) => {
  return request<{ message: string }>('/world/switch', {
    method: 'POST',
    body: JSON.stringify({ character_id: worldId }),
  })
}

export const getCurrentWorld = () => {
  return request<{ world: World }>('/world/current')
}

export const getWorldInteractions = () => {
  return request<WorldInteractionsSnapshot>('/world/interactions')
}

export const simulateWorldInteraction = () => {
  return request<{ action: string; reason?: string; interaction?: unknown }>(
    '/world/interaction/simulate',
    { method: 'POST' },
  )
}

/** 世界日报：这段时间"世界发生了什么"（后端纯聚合，零 LLM） */
export const getWorldDigest = (days = 7) => {
  return request<WorldDigest>(`/world/digest?days=${days}`)
}
