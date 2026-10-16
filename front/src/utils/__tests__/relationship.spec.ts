import { describe, it, expect } from 'vitest'
import { buildRelationGraph, edgeKey, relationLevel, findIsolated } from '@/utils/relationship'
import type { WorldInteractionsSnapshot } from '@/types/api'

/** 实测数据的形状：**有向且不对称** —— 有 linwan→maid，没有 maid→linwan */
function snapshot(overrides: Partial<WorldInteractionsSnapshot> = {}): WorldInteractionsSnapshot {
  return {
    world_id: 'campus',
    characters: { linwan: '林婉', maid: '小羽', xiaomei: '小梅' },
    relationships: {
      linwan: {
        maid: { favorability: 50, trust: 50, intimacy: 30 },
        xiaomei: { favorability: 51, trust: 50, intimacy: 30 },
      },
      maid: { xiaomei: { favorability: 50, trust: 50, intimacy: 30 } },
    },
    recent_interactions: [],
    gossip: [],
    world_impacts: [],
    last_interaction_date: '',
    ...overrides,
  } as WorldInteractionsSnapshot
}

describe('buildRelationGraph', () => {
  it('节点用显示名，不是 id', () => {
    const g = buildRelationGraph(snapshot())
    expect(g.nodes.map((n) => n.label).sort()).toEqual(['小梅', '小羽', '林婉'])
  })

  it('**有向数据去重成无向边** —— 3 条有向记录 = 3 条无向边（不是 3 条重边）', () => {
    const g = buildRelationGraph(snapshot())
    expect(g.edges).toHaveLength(3)
    const keys = g.edges.map((e) => edgeKey(e.source, e.target)).sort()
    expect(new Set(keys).size).toBe(3) // 无重复
  })

  it('**两个方向都有时合成一条**，权重取较高值', () => {
    const g = buildRelationGraph(
      snapshot({
        relationships: {
          linwan: { maid: { favorability: 40, trust: 50, intimacy: 30 } },
          maid: { linwan: { favorability: 88, trust: 70, intimacy: 60 } },
        },
      }),
    )
    expect(g.edges).toHaveLength(1)
    expect(g.edges[0]!.favorability).toBe(88)
    expect(g.edges[0]!.trust).toBe(70)
  })

  it('关系里出现但 characters 缺的 id 也要建节点（否则边指向不存在的节点）', () => {
    const g = buildRelationGraph(
      snapshot({
        characters: { linwan: '林婉' },
        relationships: { linwan: { ghost: { favorability: 50 } } },
      }),
    )
    expect(g.nodes.map((n) => n.id).sort()).toEqual(['ghost', 'linwan'])
    expect(g.nodes.find((n) => n.id === 'ghost')!.label).toBe('ghost') // 无名字时用 id 兜底
  })

  it('孤儿节点保留（没有任何关系的角色 = 被孤立，正是图要表达的）', () => {
    const g = buildRelationGraph(
      snapshot({
        characters: { linwan: '林婉', maid: '小羽', lonely: '独行侠' },
        relationships: { linwan: { maid: { favorability: 50 } } },
      }),
    )
    expect(g.nodes).toHaveLength(3)
    expect(findIsolated(g).map((n) => n.id)).toEqual(['lonely'])
  })

  it('空 relationships → 只有节点没有边（不崩）', () => {
    const g = buildRelationGraph(snapshot({ relationships: {} }))
    expect(g.nodes).toHaveLength(3)
    expect(g.edges).toEqual([])
    expect(findIsolated(g)).toHaveLength(3)
  })

  it('null / 缺字段都不崩', () => {
    expect(buildRelationGraph(null)).toEqual({ nodes: [], edges: [] })
    expect(buildRelationGraph({} as WorldInteractionsSnapshot)).toEqual({ nodes: [], edges: [] })
  })

  it('自环跳过（A→A 没有意义）', () => {
    const g = buildRelationGraph(
      snapshot({ relationships: { linwan: { linwan: { favorability: 99 } } } }),
    )
    expect(g.edges).toEqual([])
  })

  it('数值缺失/非法时用默认值（不产生 NaN）', () => {
    const g = buildRelationGraph(
      snapshot({
        relationships: { linwan: { maid: { favorability: 'x' as unknown as number } } },
      }),
    )
    expect(g.edges[0]!.favorability).toBe(50)
  })
})

describe('edgeKey', () => {
  it('无序 —— (a,b) 与 (b,a) 同 key', () => {
    expect(edgeKey('linwan', 'maid')).toBe(edgeKey('maid', 'linwan'))
  })
})

describe('relationLevel', () => {
  it('分档覆盖各区间', () => {
    expect(relationLevel(90).label).toBe('很亲近')
    expect(relationLevel(70).label).toBe('不错')
    expect(relationLevel(50).label).toBe('一般')
    expect(relationLevel(30).label).toBe('生疏')
    expect(relationLevel(10).label).toBe('疏远')
  })

  it('边界值归属明确', () => {
    expect(relationLevel(80).label).toBe('很亲近')
    expect(relationLevel(79).label).toBe('不错')
    expect(relationLevel(45).label).toBe('一般')
    expect(relationLevel(44).label).toBe('生疏')
  })
})
