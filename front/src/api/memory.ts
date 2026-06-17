import { request } from './request'
import type { EventItem, FullMemory, MemorySearchResult } from '@/types/api'

export const getMemory = () => {
  return request<{ memory: string[] }>('/memory')
}

export const clearMemory = () => {
  return request<{ message?: string }>('/clear-memory', {
    method: 'POST',
  })
}

export const getLongMemory = () => {
  return request<{ long_memory: string[] }>('/long-memory')
}

export const getFullMemory = () => {
  return request<{ memory: FullMemory }>('/memory/full')
}

export const addLongMemory = (memory: string) => {
  return request<{ message: string; long_memory: string[] }>('/long-memory/add', {
    method: 'POST',
    body: JSON.stringify({ memory }),
  })
}

export const updateLongMemory = (oldMemory: string, newMemory: string) => {
  return request<{ message: string; long_memory: string[] }>('/long-memory/update', {
    method: 'POST',
    body: JSON.stringify({ old_memory: oldMemory, new_memory: newMemory }),
  })
}

export const deleteLongMemory = (memory: string) => {
  return request<{ message: string; long_memory: string[] }>('/long-memory', {
    method: 'DELETE',
    body: JSON.stringify({ memory }),
  })
}

export const getEvents = () => {
  return request<{ events: EventItem[] }>('/events')
}

export const addEvent = (event: string) => {
  return request<{ message: string; events: EventItem[] }>('/events', {
    method: 'POST',
    body: JSON.stringify({ event }),
  })
}

/** 语义检索记忆（跨集合），score 越小越相关 */
export const getMemorySearch = (query: string, topK = 5) =>
  request<{ character_id: string; query: string; results: MemorySearchResult[] }>(
    `/memory/search?query=${encodeURIComponent(query)}&top_k=${topK}`,
  )

/** 各记忆集合的文档数量统计 */
export const getMemoryStats = () =>
  request<{ character_id: string; collections: Record<string, number> }>('/memory/stats')
