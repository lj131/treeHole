<template>
  <div class="story-tree" :class="`status-${status}`">
    <div class="story-tree-head">
      <span class="story-type-badge" :class="'type-' + (story.type || 'main')">
        {{ story.type === 'side' ? '支线' : '主线' }}
      </span>
      <b class="story-title">{{ story.title || '未命名剧情' }}</b>
      <span class="story-status-badge" :class="'status-' + status">{{ statusLabel }}</span>
      <span class="story-progress">{{ currentStage + 1 }} / {{ totalStages }} 阶段</span>
    </div>
    <p v-if="story.description" class="story-desc">{{ story.description }}</p>

    <div v-if="totalStages > 0 || currentStage > 0" class="stage-spine">
      <div v-for="(label, i) in stageNodes" :key="i" class="stage-row">
        <div class="stage-node" :class="stageClass(i)">
          <span class="node-dot">{{ dotSymbol(i) }}</span>
          <span class="node-label">{{ label }}</span>
          <span v-if="i === currentStage && !isCompleted" class="node-tag current-tag">当前</span>
        </div>
        <div
          v-for="(bp, j) in branchesAt(i)"
          :key="j"
          class="branch-node"
        >
          <span class="branch-pin">📌</span>
          <span class="branch-alt">{{ bp.alt_direction || '备选方向' }}</span>
          <span v-if="bp.reason" class="branch-reason">{{ bp.reason }}</span>
          <span v-if="bp.favorability != null" class="branch-fav">好感{{ bp.favorability }}</span>
        </div>
      </div>
    </div>
    <div v-else class="empty-hint">暂无阶段</div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { Story } from '@/types/api'

const props = defineProps<{ story: Story }>()

const status = computed(() => props.story.status || 'active')
const statusLabel = computed(
  () =>
    ({ active: '进行中', paused: '暂停', completed: '已完结' } as Record<string, string>)[
      status.value
    ] || '进行中',
)

const stages = computed(() => props.story.stages ?? [])
const totalStages = computed(() => stages.value.length)
const currentStage = computed(() => props.story.stage ?? 0)
const isCompleted = computed(() => status.value === 'completed')

const stageNodes = computed(() => {
  const n = Math.max(totalStages.value, currentStage.value + 1)
  const arr: string[] = []
  for (let i = 0; i < n; i++) arr.push(stages.value[i] || '未解锁')
  return arr
})

function stageClass(i: number): string {
  if (isCompleted.value) return 'done'
  if (i < currentStage.value) return 'done'
  if (i === currentStage.value) return 'current'
  return 'future'
}

function dotSymbol(i: number): string {
  const c = stageClass(i)
  if (c === 'done') return '●'
  if (c === 'current') return '◉'
  return '○'
}

function branchesAt(i: number) {
  return (props.story.branch_points ?? []).filter((bp) => (bp.stage ?? 0) === i)
}
</script>

<style scoped>
.story-tree {
  background: var(--bg-secondary, #1e1e2e);
  border: 1px solid var(--border-color, #33334a);
  border-radius: 12px;
  padding: 16px;
  margin-bottom: 16px;
}
.story-tree-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
.story-title {
  font-size: 1.05rem;
  color: var(--text-primary, #e4e4e7);
}
.story-progress {
  margin-left: auto;
  color: var(--text-secondary, #a0a0b8);
  font-size: 0.85rem;
}
.story-desc {
  color: var(--text-secondary, #a0a0b8);
  font-size: 0.9rem;
  margin: 0 0 12px;
}
.story-type-badge,
.story-status-badge {
  font-size: 0.75rem;
  padding: 2px 8px;
  border-radius: 8px;
}
.story-type-badge.type-main {
  background: rgba(102, 126, 234, 0.2);
  color: #93a4ff;
}
.story-type-badge.type-side {
  background: rgba(52, 211, 153, 0.2);
  color: #6ee7b7;
}
.story-status-badge.status-active {
  background: rgba(52, 211, 153, 0.15);
  color: #6ee7b7;
}
.story-status-badge.status-paused {
  background: rgba(251, 191, 36, 0.15);
  color: #fcd34d;
}
.story-status-badge.status-completed {
  background: rgba(148, 163, 184, 0.15);
  color: #cbd5e1;
}
.stage-spine {
  margin-top: 8px;
}
.stage-row {
  position: relative;
  padding-left: 20px;
}
.stage-row:not(:last-child) {
  border-left: 2px solid var(--border-color, #33334a);
  margin-left: 5px;
  padding-bottom: 14px;
}
.stage-node {
  display: flex;
  align-items: center;
  gap: 8px;
  position: relative;
  left: -15px;
  background: var(--bg-secondary, #1e1e2e);
  padding-right: 6px;
}
.node-dot {
  width: 14px;
  text-align: center;
}
.stage-node.done .node-dot {
  color: #6ee7b7;
}
.stage-node.current .node-dot {
  color: #93a4ff;
}
.stage-node.future .node-dot {
  color: var(--text-secondary, #6b6b80);
}
.node-label {
  color: var(--text-primary, #e4e4e7);
}
.stage-node.future .node-label {
  color: var(--text-secondary, #6b6b80);
}
.current-tag {
  font-size: 0.7rem;
  background: rgba(102, 126, 234, 0.2);
  color: #93a4ff;
  padding: 1px 6px;
  border-radius: 6px;
}
.branch-node {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin: 6px 0 6px 16px;
  padding: 6px 10px;
  background: rgba(251, 191, 36, 0.08);
  border-left: 3px solid #fcd34d;
  border-radius: 0 6px 6px 0;
  font-size: 0.82rem;
}
.branch-alt {
  color: #fcd34d;
}
.branch-reason {
  color: var(--text-secondary, #a0a0b8);
}
.branch-fav {
  color: #f0abfc;
  font-size: 0.75rem;
}
.empty-hint {
  color: var(--text-secondary, #6b6b80);
  padding: 12px 0;
}
</style>
