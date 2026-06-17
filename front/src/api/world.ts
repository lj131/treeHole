import { request } from './request'
import type { World, WorldInteractionsSnapshot } from '@/types/api'

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
