import { describe, it, expect } from 'vitest'
import {
  DEFAULT_VRM_URL,
  DEFAULT_CAMERA_DISTANCE,
  DEFAULT_CAMERA_PADDING,
  BUST_CROP_BOTTOM,
  toModelUrl,
  getCharacterVrmUrl,
  hasCustomModel,
  normalizeExpression,
  normalizeScale,
  normalizeRotationY,
  cameraDistanceToPadding,
  resolveModelRender,
  resolveExpression,
  expressionFromFavorability,
  expressionFromMood,
  computeFraming,
  computePopOutStage,
} from '@/utils/avatar3d'
import type { Model3DConfig } from '@/types/api'

function cfg(patch: Partial<Model3DConfig> = {}): Model3DConfig {
  return { url: '/models/linwan_ab12.vrm', format: 'vrm', ...patch }
}

describe('avatar3d / toModelUrl', () => {
  it('站内路径补 API base', () => {
    expect(toModelUrl('/models/a.vrm')).toContain('/models/a.vrm')
    expect(toModelUrl('/models/a.vrm')).toMatch(/^https?:\/\//)
  })

  it('缺前导斜杠也能拼', () => {
    expect(toModelUrl('models/a.vrm')).toContain('/models/a.vrm')
  })

  it('外链与 blob 原样返回', () => {
    expect(toModelUrl('https://cdn.x/a.glb')).toBe('https://cdn.x/a.glb')
    expect(toModelUrl('blob:http://localhost/abc')).toBe('blob:http://localhost/abc')
  })

  it('空值返回空串', () => {
    expect(toModelUrl(null)).toBe('')
    expect(toModelUrl(undefined)).toBe('')
  })
})

describe('avatar3d / getCharacterVrmUrl 优先级', () => {
  it('model3d.url 优先于旧 vrm_model', () => {
    const url = getCharacterVrmUrl({
      vrm_model: '/models/legacy.vrm',
      model3d: cfg({ url: '/models/new.vrm' }),
    })
    expect(url).toContain('/models/new.vrm')
    expect(url).not.toContain('legacy')
  })

  it('model3d.enabled=false 时忽略，回退旧字段', () => {
    const url = getCharacterVrmUrl({
      vrm_model: '/models/legacy.vrm',
      model3d: cfg({ url: '/models/off.vrm', enabled: false }),
    })
    expect(url).toContain('/models/legacy.vrm')
  })

  it('都没有时回退内置 demo', () => {
    expect(getCharacterVrmUrl(null)).toBe(DEFAULT_VRM_URL)
    expect(getCharacterVrmUrl({})).toBe(DEFAULT_VRM_URL)
  })
})

describe('avatar3d / hasCustomModel', () => {
  it('有 model3d 即视为自定义', () => {
    expect(hasCustomModel({ model3d: cfg() })).toBe(true)
  })
  it('仅旧字段也算', () => {
    expect(hasCustomModel({ vrm_model: '/models/a.vrm' })).toBe(true)
  })
  it('禁用 / 空值不算', () => {
    expect(hasCustomModel({ model3d: cfg({ enabled: false }) })).toBe(false)
    expect(hasCustomModel({})).toBe(false)
    expect(hasCustomModel(null)).toBe(false)
  })
})

describe('avatar3d / 数值归一化', () => {
  it('scale 夹到 0.1–5，非法值回 1', () => {
    expect(normalizeScale(2.5)).toBe(2.5)
    expect(normalizeScale(99)).toBe(5)
    expect(normalizeScale(0)).toBe(0.1)
    expect(normalizeScale(Number.NaN)).toBe(1)
    expect(normalizeScale(undefined)).toBe(1)
  })

  it('rotationY 夹到 -180–180', () => {
    expect(normalizeRotationY(90)).toBe(90)
    expect(normalizeRotationY(-400)).toBe(-180)
    expect(normalizeRotationY(400)).toBe(180)
    expect(normalizeRotationY(null)).toBe(0)
  })

  it('camera_distance → padding 线性映射，默认值对齐 1.35', () => {
    expect(cameraDistanceToPadding(DEFAULT_CAMERA_DISTANCE)).toBeCloseTo(DEFAULT_CAMERA_PADDING)
    expect(cameraDistanceToPadding(2.8)).toBeCloseTo(DEFAULT_CAMERA_PADDING * 2)
    expect(cameraDistanceToPadding(0.7)).toBeCloseTo(DEFAULT_CAMERA_PADDING * 0.5)
    // 非法值回退默认
    expect(cameraDistanceToPadding(0)).toBeCloseTo(DEFAULT_CAMERA_PADDING)
    expect(cameraDistanceToPadding(Number.NaN)).toBeCloseTo(DEFAULT_CAMERA_PADDING)
  })

  it('normalizeExpression 只认已知表情', () => {
    expect(normalizeExpression('HAPPY')).toBe('happy')
    expect(normalizeExpression(' excited ')).toBeNull()
    expect(normalizeExpression('')).toBeNull()
    expect(normalizeExpression(null)).toBeNull()
  })
})

describe('avatar3d / resolveModelRender', () => {
  it('未配置角色 → demo 模型 + 默认参数', () => {
    const r = resolveModelRender(null)
    expect(r.url).toBe(DEFAULT_VRM_URL)
    expect(r.isFallback).toBe(true)
    expect(r.scale).toBe(1)
    expect(r.rotationY).toBe(0)
    expect(r.cameraPadding).toBeCloseTo(DEFAULT_CAMERA_PADDING)
    expect(r.cameraFov).toBe(35)
    expect(r.autoRotate).toBe(false)
    expect(r.defaultExpression).toBeNull()
  })

  it('完整配置 → 逐项生效', () => {
    const r = resolveModelRender({
      model3d: cfg({
        scale: 1.5,
        rotation_y: 45,
        camera_distance: 2.1,
        camera_fov: 50,
        auto_rotate: true,
        default_expression: 'happy',
      }),
    })
    expect(r.isFallback).toBe(false)
    expect(r.scale).toBe(1.5)
    expect(r.rotationY).toBe(45)
    expect(r.cameraPadding).toBeCloseTo(cameraDistanceToPadding(2.1))
    expect(r.cameraFov).toBe(50)
    expect(r.autoRotate).toBe(true)
    expect(r.defaultExpression).toBe('happy')
  })

  it('脏数据不炸：越界/非法字段被夹或回退', () => {
    const r = resolveModelRender({
      model3d: cfg({
        scale: -5,
        rotation_y: 999,
        camera_distance: -1,
        camera_fov: 999,
        default_expression: 'furious',
      }),
    })
    expect(r.scale).toBe(0.1)
    expect(r.rotationY).toBe(180)
    expect(r.cameraPadding).toBeCloseTo(DEFAULT_CAMERA_PADDING)
    expect(r.cameraFov).toBe(90)
    expect(r.defaultExpression).toBeNull()
  })

  it('fov 低于下界被夹到 10', () => {
    expect(resolveModelRender({ model3d: cfg({ camera_fov: 1 }) }).cameraFov).toBe(10)
  })
})

describe('avatar3d / expressionFromFavorability', () => {
  it('好感分档映射表情', () => {
    expect(expressionFromFavorability(90).expression).toBe('happy')
    expect(expressionFromFavorability(50).expression).toBe('relaxed')
    expect(expressionFromFavorability(30).expression).toBe('neutral')
    expect(expressionFromFavorability(15).expression).toBe('sad')
    expect(expressionFromFavorability(0).expression).toBe('angry')
  })

  it('越界好感被夹', () => {
    expect(expressionFromFavorability(999).expression).toBe('happy')
    expect(expressionFromFavorability(-50).expression).toBe('angry')
  })
})

describe('avatar3d / expressionFromMood', () => {
  it('已知心情映射到 VRM 预设表情', () => {
    expect(expressionFromMood('开心')?.expression).toBe('happy')
    expect(expressionFromMood('兴奋')?.expression).toBe('happy')
    expect(expressionFromMood('生气')?.expression).toBe('angry')
    expect(expressionFromMood('难过')?.expression).toBe('sad')
    expect(expressionFromMood('害羞')?.expression).toBe('relaxed')
    expect(expressionFromMood('平静')?.expression).toBe('relaxed')
    expect(expressionFromMood('困')?.expression).toBe('neutral')
    expect(expressionFromMood('冷淡')?.expression).toBe('neutral')
  })

  it('兴奋比开心表情更强', () => {
    expect(expressionFromMood('兴奋')!.weight).toBeGreaterThan(
      expressionFromMood('开心')!.weight,
    )
  })

  it('允许前后空格', () => {
    expect(expressionFromMood('  开心 ')?.expression).toBe('happy')
  })

  it('未知 / 空值返回 null（交给好感度兜底）', () => {
    expect(expressionFromMood('暴走')).toBeNull()
    expect(expressionFromMood('')).toBeNull()
    expect(expressionFromMood(null)).toBeNull()
    expect(expressionFromMood(undefined)).toBeNull()
  })
})

describe('avatar3d / resolveExpression 优先级', () => {
  it('心情优先于好感度', () => {
    const r = resolveExpression({ mood: '生气', favorability: 90 })
    expect(r.expression).toBe('angry')
    expect(r.source).toBe('mood')
  })

  it('心情无对应表情 → 回退好感度', () => {
    const r = resolveExpression({ mood: '暴走', favorability: 20 })
    expect(r.expression).toBe('sad')
    expect(r.source).toBe('favorability')
  })

  it('无心情无好感度 → 回退模型默认表情', () => {
    const r = resolveExpression({ defaultExpression: 'happy' })
    expect(r.expression).toBe('happy')
    expect(r.source).toBe('default')
  })

  it('全空 → neutral', () => {
    const r = resolveExpression({})
    expect(r.expression).toBe('neutral')
    expect(r.source).toBe('default')
  })

  it('好感度为 0 时仍然生效（不能被当成空值跳过）', () => {
    const r = resolveExpression({ favorability: 0 })
    expect(r.expression).toBe('angry')
    expect(r.source).toBe('favorability')
  })

  it('非法好感度（NaN）不当成有效值', () => {
    const r = resolveExpression({ favorability: Number.NaN, defaultExpression: 'sad' })
    expect(r.expression).toBe('sad')
    expect(r.source).toBe('default')
  })
})

// ─────────────────────────────────────────
// 相机取景（computeFraming）
// ─────────────────────────────────────────
describe('computeFraming 相机取景', () => {
  /** 1.7m 高、站地上的标准角色 */
  const base = { size: { x: 0.5, y: 1.7, z: 0.3 }, minY: 0 }

  it('全身取景：入画高度 = 模型高度，看向身体中点', () => {
    const r = computeFraming({ ...base, framing: 'full' })
    expect(r.visibleHeight).toBeCloseTo(1.7, 5)
    expect(r.lookY).toBeCloseTo(0.85, 5)
  })

  it('半身取景：入画高度按裁剪比例缩小，视线抬到上半身', () => {
    const r = computeFraming({ ...base, framing: 'bust' })
    expect(r.visibleHeight).toBeCloseTo(1.7 * (1 - BUST_CROP_BOTTOM), 5)
    expect(r.lookY).toBeCloseTo(1.7 * ((1 + BUST_CROP_BOTTOM) / 2), 5)
  })

  it('半身比全身离得更近（否则特写没意义）', () => {
    const full = computeFraming({ ...base, framing: 'full' })
    const bust = computeFraming({ ...base, framing: 'bust' })
    expect(bust.distance).toBeLessThan(full.distance)
  })

  it('padding 线性放大距离', () => {
    const a = computeFraming({ ...base, padding: 1 })
    const b = computeFraming({ ...base, padding: 2 })
    expect(b.distance).toBeCloseTo(a.distance * 2, 5)
  })

  it('模型底面不在 0 时，视线随之抬升（脚底贴地逻辑变了也不会偏）', () => {
    const r = computeFraming({ ...base, minY: 0.4, framing: 'full' })
    expect(r.lookY).toBeCloseTo(0.4 + 0.85, 5)
  })

  it('窄画幅时按宽度兜底，避免横向被裁', () => {
    // 1.7m 高的模型在 35° FOV 下，画幅宽高比小于约 0.3 时宽度项才会成为主导
    const wide = computeFraming({ ...base, aspect: 2 })
    const narrow = computeFraming({ ...base, aspect: 0.2 })
    expect(narrow.distance).toBeGreaterThan(wide.distance)
  })

  it('退化输入（零高度 / NaN / 非法 padding）不会算出 NaN 或 0 距离', () => {
    const r = computeFraming({
      size: { x: Number.NaN, y: 0, z: Number.NaN },
      minY: Number.NaN,
      padding: Number.NaN,
      fovDeg: 0,
      aspect: 0,
    })
    expect(Number.isFinite(r.distance)).toBe(true)
    expect(r.distance).toBeGreaterThan(0)
    expect(Number.isFinite(r.lookY)).toBe(true)
    expect(Number.isFinite(r.visibleHeight)).toBe(true)
  })
})

// ─────────────────────────────────────────
// 无框浮出尺寸（computePopOutStage）
// ─────────────────────────────────────────
describe('computePopOutStage 无框浮出', () => {
  /** 聊天页左栏角色卡的槽位 */
  const chatSlot = { width: 140, height: 180 }

  it('关闭浮出时画布等于槽位、不溢出', () => {
    const r = computePopOutStage({ ...chatSlot, popOut: false })
    expect(r.popOut).toBe(false)
    expect(r.canvasWidth).toBe(140)
    expect(r.canvasHeight).toBe(180)
    expect(r.overflowTop).toBe(0)
    expect(r.bottomOffset).toBe(0)
  })

  it('开启浮出时画布放大且向上溢出（否则"浮出"没有视觉效果）', () => {
    const r = computePopOutStage(chatSlot)
    expect(r.popOut).toBe(true)
    expect(r.canvasWidth).toBeGreaterThan(chatSlot.width)
    expect(r.canvasHeight).toBeGreaterThan(chatSlot.height)
    expect(r.overflowTop).toBeGreaterThan(0)
  })

  it('聊天页槽位下，人物头顶不会被窗口顶边裁掉', () => {
    const r = computePopOutStage(chatSlot)

    // 槽位顶边距窗口顶边的距离 = 左栏 padding-top 20 + 卡片 padding-top 24
    const SLOT_TOP_OFFSET = 44
    // 人物在画布里是垂直居中的，顶部留白占画面高度的这个比例
    const padding = DEFAULT_CAMERA_PADDING * r.framingScale
    const headInset = (r.canvasHeight * (1 - 1 / (1.06 * padding))) / 2
    // 画布顶边相对窗口顶边的位置（负值 = 已经超出窗口）
    const canvasTop = SLOT_TOP_OFFSET - r.overflowTop
    const headY = canvasTop + headInset

    expect(headY).toBeGreaterThanOrEqual(0)
    // 同时也得真的探出卡片（卡片顶边在 y = 20）
    expect(headY).toBeLessThan(20)
  })

  it('开启浮出时取景留白要收紧（画布大了，人物得填得更满）', () => {
    const on = computePopOutStage(chatSlot)
    const off = computePopOutStage({ ...chatSlot, popOut: false })
    expect(on.framingScale).toBeLessThan(1)
    expect(off.framingScale).toBe(1)
  })

  it('放大不改变宽高比，避免角色被拉扁', () => {
    const r = computePopOutStage(chatSlot)
    const slotRatio = chatSlot.width / chatSlot.height
    const canvasRatio = r.canvasWidth / r.canvasHeight
    expect(Math.abs(canvasRatio - slotRatio)).toBeLessThan(0.01)
  })

  it('退化输入不会算出 0 或 NaN 尺寸', () => {
    const r = computePopOutStage({ width: Number.NaN, height: 0 })
    expect(Number.isFinite(r.canvasWidth)).toBe(true)
    expect(r.canvasWidth).toBeGreaterThan(0)
    expect(Number.isFinite(r.canvasHeight)).toBe(true)
    expect(r.canvasHeight).toBeGreaterThan(0)
  })
})
