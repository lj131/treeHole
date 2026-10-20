import { request } from './request'

/** 活动邀请（E11）*/
export interface ActivityInvitation {
  /** 活动名，如「周末的摄影展」 */
  activity: string
  /** 她说的一句话 */
  message: string
  /** 邀请发起者（character_id） */
  by?: string
  /** pending / accepted / declined */
  status?: 'pending' | 'accepted' | 'declined'
}

/**
 * 接受 / 拒绝她的邀请。
 *
 * **必须调**：拒绝会触发后端 3 天冷却，不调的话她还会再约。
 */
export const answerActivityInvitation = (action: 'accepted' | 'declined') => {
  return request<{ ok: boolean; action: string }>('/activity/invitation/answer', {
    method: 'POST',
    body: JSON.stringify({ action }),
  })
}
