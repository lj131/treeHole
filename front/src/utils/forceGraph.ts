/**
 * 极简力导向布局（纯函数、**确定性**）。
 *
 * 为什么不用 d3-force：只有几个节点，自己写 40 行就够，而且**不引依赖**。
 *
 * ⚠️ **确定性是硬要求**：初始位置按索引均分圆周，不用随机。
 * 否则（a）单测 flaky，（b）每次刷新图都在跳，看起来像在抖。
 */
export interface LayoutInput {
  id: string
}

export interface LayoutEdge {
  source: string
  target: string
}

export interface LayoutOptions {
  width: number
  height: number
  /** 迭代次数。节点少时 120 次足够收敛。 */
  iterations?: number
  /** 节点半径（用于防重叠与边界内缩） */
  radius?: number
  /** 节点最小间距 */
  minGap?: number
}

export interface Positioned {
  id: string
  x: number
  y: number
}

/** 布局参数（经验值，改之前先看测试断言的是"相对关系"不是绝对值） */
const REPULSION = 1.0
const SPRING = 0.08
const CENTER_PULL = 0.012
const DAMPING = 0.85

export function layoutForceGraph(
  nodes: LayoutInput[],
  edges: LayoutEdge[],
  opts: LayoutOptions,
): Positioned[] {
  const { width, height } = opts
  const radius = opts.radius ?? 26
  const minGap = opts.minGap ?? radius * 2 + 14
  const iterations = opts.iterations ?? 120
  const n = nodes.length

  if (n === 0) return []

  const cx = width / 2
  const cy = height / 2

  // 单节点：直接居中（力导向没意义）
  if (n === 1) return [{ id: nodes[0]!.id, x: cx, y: cy }]

  // 初始：均分圆周（**确定性**，不随机）
  const ringRadius = Math.min(width, height) / 2 - radius - 8
  const pos = nodes.map((node, i) => {
    const angle = (i / n) * Math.PI * 2 - Math.PI / 2
    return {
      id: node.id,
      x: cx + Math.cos(angle) * ringRadius,
      y: cy + Math.sin(angle) * ringRadius,
      vx: 0,
      vy: 0,
    }
  })

  const index = new Map(pos.map((p, i) => [p.id, i]))
  const springs = edges
    .map((e) => [index.get(e.source), index.get(e.target)] as const)
    .filter((pair): pair is readonly [number, number] =>
      pair[0] !== undefined && pair[1] !== undefined && pair[0] !== pair[1],
    )

  // 目标间距。调大 → 图更舒展；调小 → 更紧凑。
  const ideal = Math.max(minGap * 2.6, Math.min(width, height) / 1.9)

  for (let step = 0; step < iterations; step++) {
    // 斥力：所有节点对
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        const a = pos[i]!
        const b = pos[j]!
        let dx = a.x - b.x
        let dy = a.y - b.y
        let dist = Math.hypot(dx, dy)
        if (dist < 0.01) {
          // 完全重合时给一个确定性的微小偏移（不用随机，否则不确定）
          dx = (i - j) * 0.5
          dy = 0.5
          dist = Math.hypot(dx, dy) || 1
        }
        // 距离小于 minGap 时额外加力，保证节点不挤在一起
        const gapBoost = dist < minGap ? (minGap - dist) / minGap + 1 : 1
        const force = (REPULSION * ideal * ideal) / (dist * dist) * gapBoost
        const fx = (dx / dist) * force
        const fy = (dy / dist) * force
        a.vx += fx
        a.vy += fy
        b.vx -= fx
        b.vy -= fy
      }
    }

    // 弹簧力：有边的节点互相吸引
    for (const [i, j] of springs) {
      const a = pos[i]!
      const b = pos[j]!
      const dx = b.x - a.x
      const dy = b.y - a.y
      const dist = Math.hypot(dx, dy) || 0.01
      const force = SPRING * (dist - ideal)
      const fx = (dx / dist) * force
      const fy = (dy / dist) * force
      a.vx += fx
      a.vy += fy
      b.vx -= fx
      b.vy -= fy
    }

    // 向心力：防止整体飞散
    for (const p of pos) {
      p.vx += (cx - p.x) * CENTER_PULL
      p.vy += (cy - p.y) * CENTER_PULL
    }

    // 积分 + 阻尼 + 边界 clamp
    const pad = radius + 6
    for (const p of pos) {
      p.vx *= DAMPING
      p.vy *= DAMPING
      p.x += p.vx
      p.y += p.vy
      p.x = Math.min(Math.max(p.x, pad), width - pad)
      p.y = Math.min(Math.max(p.y, pad), height - pad)
    }
  }

  return pos.map((p) => ({ id: p.id, x: round2(p.x), y: round2(p.y) }))
}

/** 取两位小数：让输出稳定可比（浮点尾数会让"同输入同输出"的断言难写） */
function round2(v: number): number {
  return Math.round(v * 100) / 100
}
