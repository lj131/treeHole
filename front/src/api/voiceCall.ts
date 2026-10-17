import { request } from './request'

/** 当前角色信息（来电界面要显示名字） */
export interface IncomingCallInfo {
  character_id: string
  character_name: string
  reason: string
  greeting_hint?: string
}

/** `GET /voice/incoming` 的返回 */
export type IncomingCallResult =
  | ({ incoming: false; reason: string } & Partial<IncomingCallInfo>)
  | ({ incoming: true } & IncomingCallInfo)

/**
 * 查一下"她现在要不要打给你"。
 *
 * `incoming=false` 是常态（概率 30%/小时 + 双冷却 + 每日上限），
 * 前端这时**什么都不做** —— 不弹窗、不响铃。
 */
export const getIncomingCall = () => {
  return request<IncomingCallResult>('/voice/incoming')
}

/**
 * 反馈接听 / 拒绝。
 *
 * **必须调**：拒绝会触发 2 小时冷却（否则她一直打），
 * 而且不调的话刷新页面会重复弹出来电。
 */
export const answerIncomingCall = (action: 'answered' | 'declined') => {
  return request<{ ok: boolean; action: string }>('/voice/incoming/answer', {
    method: 'POST',
    body: JSON.stringify({ action }),
  })
}
