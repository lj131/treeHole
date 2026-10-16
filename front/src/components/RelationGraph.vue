<template>
  <div class="relation-graph">
    <div v-if="!graph.nodes.length" class="graph-empty">
      <p>还没有角色数据。</p>
    </div>

    <template v-else>
      <svg
        class="graph-svg"
        :viewBox="`0 0 ${WIDTH} ${HEIGHT}`"
        role="img"
        aria-label="角色关系网"
      >
        <!-- 边：粗细 + 透明度表达好感 -->
        <g class="edges">
          <line
            v-for="e in drawnEdges"
            :key="e.key"
            :x1="e.x1"
            :y1="e.y1"
            :x2="e.x2"
            :y2="e.y2"
            :stroke-width="e.width"
            :stroke-opacity="e.opacity"
            :class="['edge', relationLevel(e.favorability).tone, { dim: dimmed(e) }]"
          />
        </g>

        <!-- 节点 -->
        <g class="nodes">
          <g
            v-for="n in drawnNodes"
            :key="n.id"
            class="node"
            :class="{ isolated: isolatedIds.has(n.id), dim: hoverId && hoverId !== n.id && !neighbors.has(n.id) }"
            @mouseenter="hoverId = n.id"
            @mouseleave="hoverId = null"
          >
            <circle :cx="n.x" :cy="n.y" r="24" class="node-circle" />
            <text :x="n.x" :y="n.y + 4" class="node-label">{{ n.label }}</text>
          </g>
        </g>
      </svg>

      <p v-if="!graph.edges.length" class="graph-hint">
        角色之间还没有互动记录 —— 世界还没跑过 NPC 互动。点下方「模拟一次互动」试试。
      </p>
      <p v-else-if="isolated.length" class="graph-hint isolated-hint">
        {{ isolated.map((n) => n.label).join('、') }} 还没有和任何人建立关系。
      </p>
      <p class="graph-legend">线条越粗越亮 = 关系越好 · 悬停看某人的圈子</p>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { WorldInteractionsSnapshot } from '@/types/api'
import { buildRelationGraph, findIsolated, relationLevel } from '@/utils/relationship'
import { layoutForceGraph } from '@/utils/forceGraph'

const props = defineProps<{ snapshot: WorldInteractionsSnapshot | null }>()

const WIDTH = 620
const HEIGHT = 340

const hoverId = ref<string | null>(null)

const graph = computed(() => buildRelationGraph(props.snapshot))
const isolated = computed(() => findIsolated(graph.value))
const isolatedIds = computed(() => new Set(isolated.value.map((n) => n.id)))

const positioned = computed(() =>
  layoutForceGraph(
    graph.value.nodes.map((n) => ({ id: n.id })),
    graph.value.edges.map((e) => ({ source: e.source, target: e.target })),
    { width: WIDTH, height: HEIGHT },
  ),
)

const posById = computed(() => new Map(positioned.value.map((p) => [p.id, p])))

const drawnNodes = computed(() =>
  graph.value.nodes.map((n) => {
    const p = posById.value.get(n.id) ?? { x: WIDTH / 2, y: HEIGHT / 2 }
    return { ...n, x: p.x, y: p.y }
  }),
)

const drawnEdges = computed(() =>
  graph.value.edges
    .map((e) => {
      const a = posById.value.get(e.source)
      const b = posById.value.get(e.target)
      if (!a || !b) return null
      // 好感 0-100 → 线宽 1.2-5.5、透明度 0.3-0.95
      const ratio = Math.min(Math.max(e.favorability, 0), 100) / 100
      return {
        key: `${e.source}-${e.target}`,
        x1: a.x,
        y1: a.y,
        x2: b.x,
        y2: b.y,
        favorability: e.favorability,
        width: Math.round((1.2 + ratio * 4.3) * 10) / 10,
        opacity: Math.round((0.3 + ratio * 0.65) * 100) / 100,
        source: e.source,
        target: e.target,
      }
    })
    .filter((x): x is NonNullable<typeof x> => x !== null),
)

/** 悬停时该节点 + 它的邻居要高亮，其他变暗 */
const neighbors = computed(() => {
  const set = new Set<string>()
  if (!hoverId.value) return set
  for (const e of graph.value.edges) {
    if (e.source === hoverId.value) set.add(e.target)
    if (e.target === hoverId.value) set.add(e.source)
  }
  return set
})

function dimmed(e: { source: string; target: string }): boolean {
  if (!hoverId.value) return false
  return e.source !== hoverId.value && e.target !== hoverId.value
}
</script>

<style scoped>
.relation-graph {
  width: 100%;
}

.graph-svg {
  width: 100%;
  height: auto;
  display: block;
}

.edge {
  stroke-linecap: round;
  transition: stroke-opacity 0.15s ease;
}

.edge.rel-close { stroke: #f472b6; }
.edge.rel-good { stroke: #34d399; }
.edge.rel-normal { stroke: #60a5fa; }
.edge.rel-cold { stroke: #94a3b8; }
.edge.rel-far { stroke: #64748b; }

.edge.dim {
  stroke-opacity: 0.08 !important;
}

.node {
  cursor: default;
}

.node.dim {
  opacity: 0.28;
}

.node-circle {
  fill: rgba(99, 102, 241, 0.22);
  stroke: rgba(129, 140, 248, 0.85);
  stroke-width: 1.6;
}

.node.isolated .node-circle {
  fill: rgba(148, 163, 184, 0.16);
  stroke: rgba(148, 163, 184, 0.7);
  stroke-dasharray: 4 3;
}

.node-label {
  fill: var(--text-primary, #e5e7eb);
  font-size: 12px;
  text-anchor: middle;
  pointer-events: none;
}

.graph-empty {
  padding: 24px;
  text-align: center;
  color: var(--text-secondary);
  font-size: 13px;
}

.graph-hint {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--text-secondary);
  text-align: center;
}

.isolated-hint {
  color: #94a3b8;
}

.graph-legend {
  margin: 6px 0 0;
  font-size: 11px;
  color: var(--text-secondary);
  text-align: center;
  opacity: 0.8;
}
</style>
