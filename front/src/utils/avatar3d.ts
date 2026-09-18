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

/**
 * 角色心情（后端 `character_state.mood`）→ VRM 表情。
 *
 * 取值与后端 `prompt`/`unified_state_agent` 产出以及前端 `getMoodEmoji()` 对齐。
 * 返回 null 表示「这个心情没有对应表情」（未知值/空值），调用方应回退到好感度表情。
 */
export function expressionFromMood(mood?: string | null): {
  expression: AvatarExpression
  weight: number
} | null {
  if (!mood) return null
  const key = mood.trim()
  const map: Record<string, { expression: AvatarExpression; weight: number }> = {
    开心: { expression: 'happy', weight: 0.8 },
    兴奋: { expression: 'happy', weight: 0.9 },
    // 没有「害羞」预设表情，用低强度放松笑近似
    害羞: { expression: 'relaxed', weight: 0.55 },
    生气: { expression: 'angry', weight: 0.7 },
    难过: { expression: 'sad', weight: 0.7 },
    平静: { expression: 'relaxed', weight: 0.35 },
    // 「困」和「冷淡」在 VRM 预设里没有对应项，保持中性
    困: { expression: 'neutral', weight: 0.45 },
    冷淡: { expression: 'neutral', weight: 0.5 },
    惊讶: { expression: 'surprised', weight: 0.8 },
  }
  return map[key] ?? null
}

/**
 * 决定脸部表情：**心情优先于好感度**。
 *
 * 理由：好感度是关系基线（长期），心情是当下状态（短期）。用户刚把角色哄开心，
 * 脸上却因为好感度没变而毫无反应，会显得很假。心情无对应表情时才回退好感度，
 * 再回退角色配置的默认表情。
 */
export function resolveExpression(input: {
  mood?: string | null
  favorability?: number | null
  defaultExpression?: AvatarExpression | null
}): { expression: AvatarExpression; weight: number; source: 'mood' | 'favorability' | 'default' } {
  const fromMood = expressionFromMood(input.mood)
  if (fromMood) return { ...fromMood, source: 'mood' }

  if (typeof input.favorability === 'number' && Number.isFinite(input.favorability)) {
    return { ...expressionFromFavorability(input.favorability), source: 'favorability' }
  }

  return {
    expression: input.defaultExpression ?? 'neutral',
    weight: 0.7,
    source: 'default',
  }
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

// ─────────────────────────────────────────
// 相机取景（纯数学，无 three 依赖，便于单测）
// ─────────────────────────────────────────

/** 取景方式：full = 全身入画；bust = 半身特写（头到胸） */
export type Framing = 'full' | 'bust'

/** 半身取景从模型高度的这个比例处往上裁（0.55 = 砍掉下面 55%，只留头胸） */
export const BUST_CROP_BOTTOM = 0.55

/** 头顶留白系数（长发 / 帽子） */
const HEAD_ROOM = 1.06
/** 水平留白系数（张开的手臂 / 裙摆） */
const SIDE_ROOM = 1.08

export interface FramingInput {
  /** 模型包围盒尺寸 */
  size: { x: number; y: number; z: number }
  /** 包围盒底面 y（脚底所在高度） */
  minY: number
  framing?: Framing
  /** 取景留白倍数，越大离得越远 */
  padding?: number
  /** 相机垂直视场角（度） */
  fovDeg?: number
  /** 相机宽高比 */
  aspect?: number
}

export interface FramingResult {
  /** 相机到模型的距离 */
  distance: number
  /** 相机看向的高度 */
  lookY: number
  /** 实际入画的垂直高度 */
  visibleHeight: number
}

/**
 * 由模型包围盒算出相机该站哪、看向哪。
 *
 * 之所以抽成纯函数：这段几何一旦写歪，表现是「脚被裁掉」「头顶出画」这类
 * 只有肉眼才看得出来的问题，单测能把它钉住。
 */
export function computeFraming(input: FramingInput): FramingResult {
  const height0 = Number.isFinite(input.size.y) && input.size.y > 0 ? input.size.y : 0.5
  // 注意：Math.max(NaN, ..., 0.3) 会返回 NaN，脏包围盒必须先把 NaN 洗掉再取 max
  const sx = Number.isFinite(input.size.x) ? input.size.x : 0
  const sz = Number.isFinite(input.size.z) ? input.size.z : 0
  const width0 = Math.max(sx, sz, 0.3)
  const minY = Number.isFinite(input.minY) ? input.minY : 0
  const padding = Number.isFinite(input.padding) && (input.padding as number) > 0 ? (input.padding as number) : 1
  const fovDeg = Number.isFinite(input.fovDeg) && (input.fovDeg as number) > 0 ? (input.fovDeg as number) : 35
  const aspect = Number.isFinite(input.aspect) && (input.aspect as number) > 0 ? (input.aspect as number) : 1

  // 取景裁剪：bust 只保留身体上部
  const cropBottom = input.framing === 'bust' ? BUST_CROP_BOTTOM : 0
  const cropTop = 1

  const visibleHeight = Math.max(height0 * (cropTop - cropBottom), 0.4)
  const lookY = minY + height0 * ((cropTop + cropBottom) / 2)

  const height = visibleHeight * HEAD_ROOM
  const width = width0 * SIDE_ROOM
  const fov = (fovDeg * Math.PI) / 180

  const distForHeight = height / 2 / Math.tan(fov / 2)
  const distForWidth = width / 2 / Math.tan(fov / 2) / aspect

  return {
    distance: Math.max(distForHeight, distForWidth) * padding,
    lookY,
    visibleHeight,
  }
}

// ─────────────────────────────────────────
// 无框浮出（pop-out）尺寸
// ─────────────────────────────────────────

/**
 * 浮出时画布相对槽位放大的倍数。
 *
 * 这几个数是量出来的，不是拍脑袋。以聊天页左栏 140×180 的槽位为例
 * （panelTop=0 / cardTop=20 / slotTop=45）：
 * - 画布 188×241，底边下探 6px → 画布顶边落在 y=-10，被左栏裁掉 10px。
 *   裁掉的是透明区，人物不受影响（人物顶部还有约 12% 的取景留白）。
 * - 人物头顶落在 y≈19，正好探出卡片顶边 1px 出头；
 *   再往上调就会被窗口顶边裁到头发了 —— 这是这套布局的物理上限。
 * - 人物高约 183px，比"框里"那版（约 133px）大 37%。
 * 槽位尺寸或卡片内边距变了，这几个数必须重新核对。
 */
export const POP_OUT_SCALE = 1.34

/**
 * 浮出时取景留白的缩放系数。
 * 画布被放大了 34%，如果留白倍数不变，人物在画面里就会显得比"框里"那版更空；
 * 乘 0.92 让它在放大后的画布里填得更满，同时也把头顶顶到卡片边缘。
 */
export const POP_OUT_FRAMING_SCALE = 0.92

/** 浮出时画布底边相对槽位底边的下探量（px），让角色像"踩"在卡片上 */
export const POP_OUT_BOTTOM_OFFSET = 6

export interface PopOutStage {
  canvasWidth: number
  canvasHeight: number
  /** 画布顶边高出槽位顶边多少 px（正值 = 溢出到槽位上方，头顶探出卡片） */
  overflowTop: number
  /** 画布底边相对槽位底边的下探量 */
  bottomOffset: number
  /** 取景留白该乘的系数（浮出时人物要填得更满） */
  framingScale: number
  popOut: boolean
}

/**
 * 算出浮出画布该多大、溢出多少。
 * 抽出来是为了能单测"头顶到底探出卡片多少"这类只有肉眼能看出的问题。
 */
export function computePopOutStage(input: {
  width: number
  height: number
  popOut?: boolean
}): PopOutStage {
  const w = Number.isFinite(input.width) && input.width > 0 ? input.width : 1
  const h = Number.isFinite(input.height) && input.height > 0 ? input.height : 1

  if (input.popOut === false) {
    return {
      canvasWidth: w,
      canvasHeight: h,
      overflowTop: 0,
      bottomOffset: 0,
      framingScale: 1,
      popOut: false,
    }
  }

  const canvasWidth = Math.round(w * POP_OUT_SCALE)
  const canvasHeight = Math.round(h * POP_OUT_SCALE)
  return {
    canvasWidth,
    canvasHeight,
    // 画布底部下探 bottomOffset，所以顶边高出槽位顶边的量要再减掉它
    overflowTop: canvasHeight - h - POP_OUT_BOTTOM_OFFSET,
    bottomOffset: POP_OUT_BOTTOM_OFFSET,
    framingScale: POP_OUT_FRAMING_SCALE,
    popOut: true,
  }
}
