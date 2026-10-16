import { describe, it, expect } from 'vitest'
import { layoutForceGraph } from '@/utils/forceGraph'

const OPTS = { width: 600, height: 360, radius: 26 }

function nodes(...ids: string[]) {
  return ids.map((id) => ({ id }))
}

function dist(a: { x: number; y: number }, b: { x: number; y: number }) {
  return Math.hypot(a.x - b.x, a.y - b.y)
}

describe('layoutForceGraph', () => {
  it('**确定性**：同一输入两次布局结果完全一致', () => {
    const n = nodes('a', 'b', 'c', 'd')
    const e = [
      { source: 'a', target: 'b' },
      { source: 'c', target: 'd' },
    ]
    const first = layoutForceGraph(n, e, OPTS)
    const second = layoutForceGraph(n, e, OPTS)
    expect(second).toEqual(first)
  })

  it('所有节点都在画布内（含半径内缩）', () => {
    const n = nodes('a', 'b', 'c', 'd', 'e', 'f')
    const out = layoutForceGraph(n, [], OPTS)
    for (const p of out) {
      expect(p.x).toBeGreaterThanOrEqual(OPTS.radius)
      expect(p.x).toBeLessThanOrEqual(OPTS.width - OPTS.radius)
      expect(p.y).toBeGreaterThanOrEqual(OPTS.radius)
      expect(p.y).toBeLessThanOrEqual(OPTS.height - OPTS.radius)
    }
  })

  it('**节点不重叠**（两两距离不小于最小间距）', () => {
    const n = nodes('a', 'b', 'c', 'd', 'e')
    const out = layoutForceGraph(n, [], OPTS)
    for (let i = 0; i < out.length; i++) {
      for (let j = i + 1; j < out.length; j++) {
        // 允许一点数值余量（力导向是近似收敛）
        expect(dist(out[i]!, out[j]!)).toBeGreaterThan(OPTS.radius * 1.6)
      }
    }
  })

  it('**有边的节点比无边的更近**（弹簧力起作用了）', () => {
    const n = nodes('a', 'b', 'c')
    const out = layoutForceGraph(n, [{ source: 'a', target: 'b' }], OPTS)
    const byId = Object.fromEntries(out.map((p) => [p.id, p]))
    const linked = dist(byId.a!, byId.b!)
    const unlinked = dist(byId.a!, byId.c!)
    expect(linked).toBeLessThan(unlinked)
  })

  it('单节点居中（力导向对单点没意义）', () => {
    const out = layoutForceGraph(nodes('only'), [], OPTS)
    expect(out).toHaveLength(1)
    expect(out[0]!.x).toBe(OPTS.width / 2)
    expect(out[0]!.y).toBe(OPTS.height / 2)
  })

  it('空图返回空数组（不崩）', () => {
    expect(layoutForceGraph([], [], OPTS)).toEqual([])
  })

  it('边引用了不存在的节点时忽略该边（不崩）', () => {
    const out = layoutForceGraph(
      nodes('a', 'b'),
      [{ source: 'a', target: 'ghost' }],
      OPTS,
    )
    expect(out).toHaveLength(2)
  })

  it('自环边忽略（不崩）', () => {
    const out = layoutForceGraph(nodes('a', 'b'), [{ source: 'a', target: 'a' }], OPTS)
    expect(out).toHaveLength(2)
  })

  it('节点极多时仍在画布内（边界 clamp 生效）', () => {
    const n = nodes(...Array.from({ length: 20 }, (_, i) => `n${i}`))
    const out = layoutForceGraph(n, [], { ...OPTS, iterations: 40 })
    for (const p of out) {
      expect(p.x).toBeGreaterThanOrEqual(0)
      expect(p.x).toBeLessThanOrEqual(OPTS.width)
      expect(p.y).toBeGreaterThanOrEqual(0)
      expect(p.y).toBeLessThanOrEqual(OPTS.height)
    }
  })
})
