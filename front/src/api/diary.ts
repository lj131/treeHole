import { request } from './request'

/** 一篇日记 */
export interface DiaryEntry {
  date: string
  text: string
}

export interface DiaryResult {
  /** 今天的日记；null = 她今天没写（素材不足） */
  diary: DiaryEntry | null
  /** 最近的几篇（新→旧） */
  history: DiaryEntry[]
}

/**
 * 角色日记本（E9）。
 *
 * ⚠️ 首次调用会**懒生成**一篇（后端要调 LLM，1-3 秒），
 * 所以前端必须给 loading 态。之后再打开是幂等的（直接复用）。
 */
export const getDiary = () => {
  return request<DiaryResult>('/diary')
}
