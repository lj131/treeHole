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

/** 一条世界事件（字段与后端 `world_state/current_events` 一致） */
export interface WorldEvent {
  id: string
  title: string
  description: string
  /** ⚠️ 是 **int**（如 6、7），不是 "low/medium/high" 字符串 */
  importance: number
  status: string
  progress: number
  created_at?: string
  finished_at?: string | null
}

/**
 * 手动注入一个世界事件（E10）。
 *
 * ⚠️ `importance` 必须传 **int**（1-10 量级）—— 后端 schema 是 `int`，
 * 传 "high" 这种字符串会 422（我实测踩过）。
 *
 * 注入后 NPC 会**自动**在对话里提起它：`status=="running"` 的事件
 * 会被 `prompt.py` 以「进行中的事件」注入 system prompt，这条链路早已存在。
 */
export const createWorldEvent = (payload: {
  title: string
  description?: string
  importance?: number
}) => {
  return request<{
    message?: string
    error?: string
    event: WorldEvent
    current_events: WorldEvent[]
  }>('/world/event/create', {
    method: 'POST',
    body: JSON.stringify({
      title: payload.title,
      description: payload.description ?? '',
      importance: payload.importance ?? 5,
    }),
  })
}

/** 当前世界的事件（进行中 + 已结束） */
export const getWorldEvents = () => {
  return request<{ current_events: WorldEvent[]; history_events?: WorldEvent[] }>(
    '/world/events',
  )
}

/** 世界日报：这段时间"世界发生了什么"（后端纯聚合，零 LLM） */
export const getWorldDigest = (days = 7) => {
  return request<WorldDigest>(`/world/digest?days=${days}`)
}
