/**
 * 3D 场景的夜色背景。
 *
 * 背景来历：之前非透明模式直接把 HDRI 天空照（`puresky_1k.hdr`）当 `scene.background`，
 * 于是角色像"站在大白天里"—— 一张写实天空照配一个二次元人物，很出戏，而且那个天空
 * 是高饱和的蓝，跟整套暗色 UI 也打架。
 *
 * 现在改成程序化生成的柔和夜色：围绕基色做低饱和渐变 + 极淡星点 + 细噪点抖动。
 * 渐变数学抽成纯函数（`computeNightGradientStops`），canvas 只是渲染壳。
 *
 * 注意：HDRI 仍然保留给 `scene.environment`（材质需要 PBR 反射），只是不再当背景。
 */
import * as THREE from 'three'

const FALLBACK_BASE = '#1a1a2e'

export interface NightGradientStop {
  offset: number
  color: string
}

interface Rgb {
  r: number
  g: number
  b: number
}

interface Hsl {
  h: number
  s: number
  l: number
}

function clamp01(v: number): number {
  if (!Number.isFinite(v)) return 0
  return Math.min(1, Math.max(0, v))
}

function clamp255(v: number): number {
  return Math.min(255, Math.max(0, v))
}

function parseHex(hex: string): Rgb {
  const raw = (hex || '').trim().replace(/^#/, '')
  const full = raw.length === 3
    ? raw.split('').map((c) => c + c).join('')
    : raw
  // 脏输入不抛异常，直接退回默认夜色基色
  if (!/^[0-9a-f]{6}$/i.test(full)) return parseHex(FALLBACK_BASE)
  return {
    r: parseInt(full.slice(0, 2), 16),
    g: parseInt(full.slice(2, 4), 16),
    b: parseInt(full.slice(4, 6), 16),
  }
}

function rgbToHsl({ r, g, b }: Rgb): Hsl {
  const rn = r / 255
  const gn = g / 255
  const bn = b / 255
  const max = Math.max(rn, gn, bn)
  const min = Math.min(rn, gn, bn)
  const l = (max + min) / 2
  const d = max - min

  let h = 0
  let s = 0
  if (d !== 0) {
    s = d / (1 - Math.abs(2 * l - 1))
    if (max === rn) h = ((gn - bn) / d) % 6
    else if (max === gn) h = (bn - rn) / d + 2
    else h = (rn - gn) / d + 4
    h *= 60
    if (h < 0) h += 360
  }
  return { h, s, l }
}

function hslToHex({ h, s, l }: Hsl): string {
  const hn = ((h % 360) + 360) % 360
  const sn = clamp01(s)
  const ln = clamp01(l)
  const c = (1 - Math.abs(2 * ln - 1)) * sn
  const x = c * (1 - Math.abs(((hn / 60) % 2) - 1))
  const m = ln - c / 2

  let r = 0
  let g = 0
  let b = 0
  if (hn < 60) [r, g, b] = [c, x, 0]
  else if (hn < 120) [r, g, b] = [x, c, 0]
  else if (hn < 180) [r, g, b] = [0, c, x]
  else if (hn < 240) [r, g, b] = [0, x, c]
  else if (hn < 300) [r, g, b] = [x, 0, c]
  else [r, g, b] = [c, 0, x]

  const to255 = (v: number) => Math.round(clamp01(v + m) * 255)
  return `#${[to255(r), to255(g), to255(b)].map((v) => v.toString(16).padStart(2, '0')).join('')}`
}

/**
 * 由基色推出夜色渐变的色标。
 *
 * 三条约束：
 * 1. **饱和度只降不升** —— 高饱和就会出现"能看出轮廓的色块"，那正是要避免的；
 * 2. 顶部最暗、38% 处留一点极淡的"天光"（给人物当背光），底部再压暗；
 * 3. 全程贴着基色色相，所以换任何基色都不会跳色。
 */
export function computeNightGradientStops(baseHex: string): NightGradientStop[] {
  const hsl = rgbToHsl(parseHex(baseHex))
  // 亮度下限：纯黑基色如果照直算，顶部/底部会退化成 #000000，整块背景变成死黑。
  // 抬到 6% 保证渐变始终有可见的层次。
  const baseL = Math.max(hsl.l, 0.06)

  return [
    { offset: 0, color: hslToHex({ h: hsl.h, s: hsl.s * 0.85, l: baseL * 0.45 }) },
    { offset: 0.38, color: hslToHex({ h: hsl.h, s: hsl.s * 0.55, l: baseL * 1.4 + 0.015 }) },
    { offset: 1, color: hslToHex({ h: hsl.h, s: hsl.s * 0.9, l: baseL * 0.8 }) },
  ]
}

/** canvas 不可用时（如 jsdom）退回 1×1 纯色贴图，绝不抛异常 */
function createSolidTexture(baseHex: string): THREE.Texture {
  const { r, g, b } = parseHex(baseHex)
  const data = new Uint8Array([r, g, b, 255])
  const tex = new THREE.DataTexture(data, 1, 1, THREE.RGBAFormat)
  tex.colorSpace = THREE.SRGBColorSpace
  tex.needsUpdate = true
  return tex
}

export interface NightBackgroundOptions {
  /** 生成贴图的边长，默认 512 */
  size?: number
  /** 星点数量，默认 90；传 0 关掉 */
  starCount?: number
}

/**
 * 生成夜色背景贴图。
 * 作为 `scene.background` 使用时，three 会把它铺满整个视口（普通 UV 贴图 = 全屏四边形）。
 */
export function createNightBackgroundTexture(
  baseHex: string,
  options: NightBackgroundOptions = {},
): THREE.Texture {
  const size = options.size ?? 512
  const starCount = options.starCount ?? 90

  if (typeof document === 'undefined') return createSolidTexture(baseHex)
  const canvas = document.createElement('canvas')
  canvas.width = size
  canvas.height = size
  const ctx = canvas.getContext('2d')
  if (!ctx) return createSolidTexture(baseHex)

  // 1. 竖向渐变
  const grad = ctx.createLinearGradient(0, 0, 0, size)
  for (const stop of computeNightGradientStops(baseHex)) {
    grad.addColorStop(clamp01(stop.offset), stop.color)
  }
  ctx.fillStyle = grad
  ctx.fillRect(0, 0, size, size)

  // 2. 极淡星点，集中在上半部分（下半部分会被人物和地面阴影盖住）
  if (starCount > 0) {
    for (let i = 0; i < starCount; i++) {
      const x = Math.random() * size
      const y = Math.random() * size * 0.62
      const radius = Math.random() * 1.1 + 0.3
      const alpha = Math.random() * 0.16 + 0.03
      ctx.fillStyle = `rgba(255,255,255,${alpha.toFixed(3)})`
      ctx.beginPath()
      ctx.arc(x, y, radius, 0, Math.PI * 2)
      ctx.fill()
    }
  }

  // 3. 细噪点抖动：深色渐变在 8bit 屏上会出现明显色带（banding），加一点噪声就没了
  const image = ctx.getImageData(0, 0, size, size)
  const d = image.data
  for (let i = 0; i < d.length; i += 4) {
    const n = (Math.random() - 0.5) * 5
    d[i] = clamp255(d[i]! + n)
    d[i + 1] = clamp255(d[i + 1]! + n)
    d[i + 2] = clamp255(d[i + 2]! + n)
  }
  ctx.putImageData(image, 0, 0)

  const texture = new THREE.CanvasTexture(canvas)
  texture.colorSpace = THREE.SRGBColorSpace
  texture.minFilter = THREE.LinearFilter
  texture.magFilter = THREE.LinearFilter
  texture.generateMipmaps = false
  texture.needsUpdate = true
  return texture
}
