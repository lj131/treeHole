import { describe, it, expect } from 'vitest'
import {
  DEFAULT_VRM_URL,
  DEFAULT_CAMERA_DISTANCE,
  DEFAULT_CAMERA_PADDING,
  toModelUrl,
  getCharacterVrmUrl,
  hasCustomModel,
  normalizeExpression,
  normalizeScale,
  normalizeRotationY,
  cameraDistanceToPadding,
  resolveModelRender,
  expressionFromFavorability,
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
