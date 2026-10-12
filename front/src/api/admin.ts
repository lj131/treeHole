/**
 * 系统配置接口（仅管理员）。
 *
 * 走共享的 `request()` 就够了 —— 收发都是 JSON，不像语音包那边要传 FormData / 收 Blob。
 */
import { request } from './request'
import type { SystemConfigPatch, SystemConfigResponse } from '@/types/api'

/** 读配置 schema + 当前生效值 */
export const getSystemConfig = () => {
  return request<SystemConfigResponse>('/admin/config')
}

/** 局部更新。值为 null 表示恢复该项默认。 */
export const updateSystemConfig = (patch: SystemConfigPatch) => {
  return request<SystemConfigResponse>('/admin/config', {
    method: 'PATCH',
    body: JSON.stringify(patch),
  })
}
