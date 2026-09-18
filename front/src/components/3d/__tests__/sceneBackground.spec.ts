import { describe, it, expect } from 'vitest'
import { computeNightGradientStops } from '@/components/3d/sceneBackground'

/** #rrggbb → {h,s,l}，只用于断言，独立实现一遍避免和被测代码互相"圆谎" */
function hslOf(hex: string): { h: number; s: number; l: number } {
  const n = hex.replace('#', '')
  const r = parseInt(n.slice(0, 2), 16) / 255
  const g = parseInt(n.slice(2, 4), 16) / 255
  const b = parseInt(n.slice(4, 6), 16) / 255
  const max = Math.max(r, g, b)
  const min = Math.min(r, g, b)
  const l = (max + min) / 2
  const d = max - min
  if (d === 0) return { h: 0, s: 0, l }
  const s = d / (1 - Math.abs(2 * l - 1))
  let h: number
  if (max === r) h = ((g - b) / d) % 6
  else if (max === g) h = (b - r) / d + 2
  else h = (r - g) / d + 4
  h *= 60
  if (h < 0) h += 360
  return { h, s, l }
}

const BASE = '#16162a'

describe('computeNightGradientStops 夜色渐变', () => {
  it('返回 3 个色标，offset 递增且落在 0–1', () => {
    const stops = computeNightGradientStops(BASE)
    expect(stops).toHaveLength(3)
    expect(stops[0]!.offset).toBe(0)
    expect(stops[2]!.offset).toBe(1)
    for (let i = 1; i < stops.length; i++) {
      expect(stops[i]!.offset).toBeGreaterThan(stops[i - 1]!.offset)
    }
  })

  it('全部输出合法 #rrggbb（脏基色也不例外）', () => {
    for (const base of [BASE, '#fff', '#abcdef', 'not-a-color', '', '#12345']) {
      for (const stop of computeNightGradientStops(base)) {
        expect(stop.color).toMatch(/^#[0-9a-f]{6}$/)
      }
    }
  })

  it('饱和度只降不升 —— 高饱和就会露出"色块"，那正是要避免的', () => {
    const baseS = hslOf(BASE).s
    for (const stop of computeNightGradientStops(BASE)) {
      expect(hslOf(stop.color).s).toBeLessThanOrEqual(baseS + 1e-6)
    }
  })

  it('顶部比"天光"处更暗（做出上暗-中亮-下暗的夜色层次）', () => {
    const stops = computeNightGradientStops(BASE)
    const top = hslOf(stops[0]!.color).l
    const glow = hslOf(stops[1]!.color).l
    const bottom = hslOf(stops[2]!.color).l
    expect(glow).toBeGreaterThan(top)
    expect(glow).toBeGreaterThan(bottom)
  })

  it('整体是暗色（不能出现亮底把白色角色衬没）', () => {
    for (const stop of computeNightGradientStops(BASE)) {
      expect(hslOf(stop.color).l).toBeLessThan(0.35)
    }
  })

  it('色相贴着基色不跳色（换基色也只在同色相里微调）', () => {
    const warm = computeNightGradientStops('#2a1a16')
    const baseHue = hslOf('#2a1a16').h
    for (const stop of warm) {
      const { h } = hslOf(stop.color)
      const diff = Math.min(Math.abs(h - baseHue), 360 - Math.abs(h - baseHue))
      expect(diff).toBeLessThan(6)
    }
  })

  it('纯黑基色不会算出 NaN，也不会变成透明', () => {
    for (const stop of computeNightGradientStops('#000000')) {
      expect(stop.color).toMatch(/^#[0-9a-f]{6}$/)
      expect(stop.color).not.toBe('#000000')
    }
  })
})
