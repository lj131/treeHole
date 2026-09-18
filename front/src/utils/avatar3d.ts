import type { AvatarExpression } from '@/components/3d/VRMAvatar.vue'
import type { Model3DConfig } from '@/types/api'

/** 默认演示模型（角色未配置 3D 模型时使用） */
export const DEFAULT_VRM_URL = '/models/rpm_demo.vrm'

/** 后端 camera_distance 默认值（与 funcation/model3d.py 对齐） */
export const DEFAULT_CAMERA_DISTANCE = 1.4

/** ThreeScene.frameObject 默认 padding（与 ThreeScene.vue 对齐） */
export const DEFAULT_CAMERA_PADDING = 1.35

const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000'

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
 * 把角色配置里的模型地址转成可直接加载的 URL。
 * 站内路径（`/models/x.vrm`）补 API base；外链原样返回。
 */
export function toModelUrl(raw?: string | null): string {
  if (!raw) return ''
  if (raw.startsWith('http://') || raw.startsWith('https://') || raw.startsWith('blob:')) {
    return raw
  }
  return `${API_BASE}${raw.startsWith('/') ? '' : '/'}${raw}`
}

/** 角色上可用的模型地址（新字段优先，兼容旧 vrm_model，最后回退 demo） */
export function getCharacterVrmUrl(character?: {
  id?: string
  vrm_model?: string
  model3d?: Model3DConfig | null
} | null): string {
  const fromConfig = character?.model3d
  if (fromConfig?.url && fromConfig.enabled !== false) {
    return toModelUrl(fromConfig.url)
  }
  if (character?.vrm_model) {
    return toModelUrl(character.vrm_model)
  }
  return DEFAULT_VRM_URL
}

/** 该角色是否配置了自己的 3D 模型（用于 UI 上显示「自定义」标识） */
export function hasCustomModel(character?: {
  vrm_model?: string
  model3d?: Model3DConfig | null
} | null): boolean {
  const cfg = character?.model3d
  if (cfg?.url && cfg.enabled !== false) return true
  return !!character?.vrm_model
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

const VALID_EXPRESSIONS: AvatarExpression[] = [
  'neutral',
  'happy',
  'angry',
  'sad',
  'relaxed',
  'surprised',
]

/** 校验后端给的 default_expression 是否可用 */
export function normalizeExpression(raw?: string | null): AvatarExpression | null {
  if (!raw) return null
  const value = raw.trim().toLowerCase()
  return (VALID_EXPRESSIONS as string[]).includes(value)
    ? (value as AvatarExpression)
    : null
}

/** camera_distance（后端语义：越大越远）→ frameObject 的 padding */
export function cameraDistanceToPadding(distance?: number | null): number {
  const d = typeof distance === 'number' && Number.isFinite(distance) && distance > 0
    ? distance
    : DEFAULT_CAMERA_DISTANCE
  return (d / DEFAULT_CAMERA_DISTANCE) * DEFAULT_CAMERA_PADDING
}

/** 缩放：非法值 / 越界值统一夹到 0.1–5，默认 1 */
export function normalizeScale(scale?: number | null): number {
  if (typeof scale !== 'number' || !Number.isFinite(scale)) return 1
  return Math.max(0.1, Math.min(5, scale))
}

/** 旋转角（度）：夹到 -180–180，默认 0 */
export function normalizeRotationY(deg?: number | null): number {
  if (typeof deg !== 'number' || !Number.isFinite(deg)) return 0
  return Math.max(-180, Math.min(180, deg))
}

/** 解析后的渲染参数：交给 CharacterPortrait3D / VRMAvatar 直接用 */
export interface ResolvedModelRender {
  url: string
  /** 是否在使用内置 demo 模型（用于「角色还没有自己的模型」提示） */
  isFallback: boolean
  scale: number
  rotationY: number
  cameraPadding: number
  cameraFov: number
  autoRotate: boolean
  /** 角色配置里的默认表情（好感度表情优先级更高） */
  defaultExpression: AvatarExpression | null
}

/**
 * 汇总角色 3D 模型配置 → 渲染参数。
 * 所有数值都做一次防御性归一化，坏数据不会把场景搞崩。
 */
export function resolveModelRender(
  character?: {
    vrm_model?: string
    model3d?: Model3DConfig | null
  } | null,
): ResolvedModelRender {
  const cfg = character?.model3d ?? null
  const url = getCharacterVrmUrl(character)
  const fov = typeof cfg?.camera_fov === 'number' && Number.isFinite(cfg.camera_fov)
    ? Math.max(10, Math.min(90, cfg.camera_fov))
    : 35

  return {
    url,
    isFallback: url === DEFAULT_VRM_URL,
    scale: normalizeScale(cfg?.scale),
    rotationY: normalizeRotationY(cfg?.rotation_y),
    cameraPadding: cameraDistanceToPadding(cfg?.camera_distance),
    cameraFov: fov,
    autoRotate: cfg?.auto_rotate === true,
    defaultExpression: normalizeExpression(cfg?.default_expression),
  }
}
