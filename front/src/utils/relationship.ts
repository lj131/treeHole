/**
 * 关系数据 → 图（节点 + 边）。纯函数，可单测。
 *
 * ⚠️ **核心难点：后端存的是有向关系，而且不对称。**
 * 实测数据里只有 `linwan → maid` 和 `linwan → xiaomei`、`maid → xiaomei`，
 * **没有**任何反向条目，也没有 `xiaomei → *`。
 * 所以直接遍历会漏边（maid→linwan 不存在就画不出来）或画重边。
 * → 一律**归一化成无向边**：`(a,b)` 与 `(b,a)` 合成一条，权重取较大值。
 */
import type { WorldInteractionsSnapshot } from '@/types/api'

export interface GraphNode {
  id: string
  /** 显示名（后端 characters 映射给的中文名） */
  label: string
}

export interface GraphEdge {
  source: string
  target: string
  favorability: number
  trust: number
  intimacy: number
}

export interface RelationGraph {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

/** 无向边的稳定 key（小 id 在前），用于去重。 */
export function edgeKey(a: string, b: string): string {
  return a < b ? `${a}|${b}` : `${b}|${a}`
}

export function buildRelationGraph(snapshot: WorldInteractionsSnapshot | null): RelationGraph {
  if (!snapshot) return { nodes: [], edges: [] }

  const names = (snapshot.characters ?? {}) as Record<string, string>
  const relationships = (snapshot.relationships ?? {}) as Record<
    string,
    Record<string, { favorability?: number; trust?: number; intimacy?: number }>
  >

  // 节点：以 characters 为准，但**关系里出现过的 id 也要收** ——
  // 万一 characters 缺了某个 id（数据不一致），只认 characters 会让边指向不存在的节点。
  const ids = new Set<string>(Object.keys(names))
  for (const [from, targets] of Object.entries(relationships)) {
    ids.add(from)
    if (targets && typeof targets === 'object') {
      // `Set.add` 只收一个参数，不能展开
      for (const to of Object.keys(targets)) ids.add(to)
    }
  }

  const nodes: GraphNode[] = [...ids].map((id) => ({ id, label: names[id] || id }))

  // 边：无向去重，权重取两者中较高的
  const merged = new Map<string, GraphEdge>()
  for (const [from, targets] of Object.entries(relationships)) {
    if (!targets || typeof targets !== 'object') continue
    for (const [to, stats] of Object.entries(targets)) {
      if (!to || to === from) continue // 自环跳过
      const key = edgeKey(from, to)
      const incoming = {
        favorability: num(stats?.favorability, 50),
        trust: num(stats?.trust, 50),
        intimacy: num(stats?.intimacy, 30),
      }
      const existing = merged.get(key)
      if (!existing) {
        merged.set(key, { source: from, target: to, ...incoming })
        continue
      }
      // 两个方向都有时取较高值 —— 关系是相互的，取"更亲近的那个方向"
      // 比取平均更能反映"实际有多近"
      if (incoming.favorability > existing.favorability) {
        merged.set(key, { source: from, target: to, ...incoming })
      }
    }
  }

  return { nodes, edges: [...merged.values()] }
}

function num(v: unknown, fallback: number): number {
  return typeof v === 'number' && Number.isFinite(v) ? v : fallback
}

/** 好感 → 关系档位。用于边的配色与文字。 */
export function relationLevel(favorability: number): { label: string; tone: string } {
  if (favorability >= 80) return { label: '很亲近', tone: 'rel-close' }
  if (favorability >= 65) return { label: '不错', tone: 'rel-good' }
  if (favorability >= 45) return { label: '一般', tone: 'rel-normal' }
  if (favorability >= 25) return { label: '生疏', tone: 'rel-cold' }
  return { label: '疏远', tone: 'rel-far' }
}

/**
 * 找出"孤立者"—— 没有任何关系的角色。
 * 这是关系图最想表达的一件事：谁被剩下了。
 */
export function findIsolated(graph: RelationGraph): GraphNode[] {
  const connected = new Set<string>()
  for (const e of graph.edges) {
    connected.add(e.source)
    connected.add(e.target)
  }
  return graph.nodes.filter((n) => !connected.has(n.id))
}
