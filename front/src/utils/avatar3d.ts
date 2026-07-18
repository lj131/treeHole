import type { AvatarExpression } from '@/components/3d/VRMAvatar.vue'

/** 默认演示模型（角色未配置 vrm 时使用） */
export const DEFAULT_VRM_URL = '/models/rpm_demo.vrm'

/** 检测 WebGL 是否可用 */
export function isWebGLAvailable(): boolean {
  try {
    const canvas = document.createElement('canvas')
    return !!(
      canvas.getContext('webgl2') ||
      canvas.getContext('webgl') ||
      canvas.getContext('experimental-webgl')
    )
  } catch {
    return false
  }
}

/**
 * 解析角色 VRM 地址：
 * 1. character.vrm_model（完整 URL 或站点路径）
 * 2. 默认 rpm_demo（角色专属模型待上传 API 落地后再按 id 约定）
 */
export function getCharacterVrmUrl(character?: {
  id?: string
  vrm_model?: string
} | null): string {
  if (character?.vrm_model) {
    if (character.vrm_model.startsWith('http') || character.vrm_model.startsWith('/')) {
      return character.vrm_model
    }
    return `/models/${character.vrm_model}`
  }
  return DEFAULT_VRM_URL
}

/**
 * 好感度 → 基础表情
 * 与后端关系档位大致对齐：冷淡 / 普通 / 友好 / 亲近
 */
export function expressionFromFavorability(favorability: number): {
  expression: AvatarExpression
  weight: number
} {
  const fav = Math.max(0, Math.min(100, favorability))
  if (fav >= 70) return { expression: 'happy', weight: 0.75 }
  if (fav >= 45) return { expression: 'relaxed', weight: 0.65 }
  if (fav >= 25) return { expression: 'neutral', weight: 0.5 }
  if (fav >= 10) return { expression: 'sad', weight: 0.45 }
  return { expression: 'angry', weight: 0.35 }
}
