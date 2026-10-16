<template>
  <div class="rel-timeline">
    <!-- 认识天数：最想让人看到的一行 -->
    <div v-if="daysKnown !== null" class="days-hero">
      <span class="days-number">{{ daysKnown }}</span>
      <span class="days-unit">天</span>
      <p class="days-caption">
        你和{{ characterName || '她' }}认识 {{ daysKnown }} 天了
        <span v-if="sinceLabel" class="since">（{{ sinceLabel }} 起）</span>
      </p>
    </div>
    <p v-else class="empty-hint">还没有聊天记录 —— 开始聊天后这里会记录你们的关系变化。</p>

    <template v-if="hasAnyData">
      <!-- 好感曲线 -->
      <section v-if="trail.length >= 2" class="tl-block">
        <h3 class="tl-title">好感变化</h3>
        <svg class="spark" :viewBox="`0 0 ${SPARK_W} ${SPARK_H}`" preserveAspectRatio="none">
          <polyline :points="sparkPoints" class="spark-line" />
          <circle
            v-for="p in sparkDots"
            :key="p.date"
            :cx="p.x"
            :cy="p.y"
            r="2.5"
            class="spark-dot"
          />
        </svg>
        <div class="spark-axis">
          <span>{{ trail[0]!.date }}</span>
          <span>{{ trail[trail.length - 1]!.date }}</span>
        </div>
        <p class="tl-hint">
          当前 {{ currentFavorability }}
          <span v-if="peakText" class="peak">· 最高 {{ peakText }}</span>
          <span v-if="minText" class="min">· 最低 {{ minText }}</span>
        </p>
      </section>

      <!-- 里程碑 -->
      <section v-if="milestones.length" class="tl-block">
        <h3 class="tl-title">关系里程碑</h3>
        <ul class="ms-list">
          <li v-for="(m, i) in milestones" :key="`${m.date}-${i}`" class="ms-item">
            <span class="ms-dot" />
            <span class="ms-date">{{ m.date }}</span>
            <span class="ms-change">
              {{ m.from || '?' }} <span class="ms-arrow">→</span>
              <b>{{ m.to || '?' }}</b>
            </span>
          </li>
        </ul>
      </section>

      <p v-if="isSparse" class="tl-hint">
        关系变化还不多 —— 多聊聊、或者等剧情推进，这里会记录下每一次转变。
      </p>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { SelfAwareness } from '@/types/api'
import { daysBetween, localToday } from '@/utils/digest'

const props = defineProps<{
  awareness: SelfAwareness | null | undefined
  characterName?: string
  currentFavorability?: number
}>()

const SPARK_W = 300
const SPARK_H = 64

const trail = computed(() => props.awareness?.fav_trail ?? [])
const milestones = computed(() => props.awareness?.milestones ?? [])

/** 认识多少天。起点晚于今天（时钟问题）或没有起点时为 null。 */
const daysKnown = computed(() => {
  const first = props.awareness?.first_chat_date
  if (!first) return null
  const n = daysBetween(first, localToday())
  return n === null || n < 0 ? null : n + 1 // 当天算第 1 天
})

const sinceLabel = computed(() => props.awareness?.first_chat_date || '')

/** 峰值/低谷：**日期可能为空**（好感从没超过初始值时后端不写日期）——
 *  那时只显示数值，别显示"最高 50（?）"。 */
const peakText = computed(() => {
  const v = props.awareness?.peak_favorability
  if (typeof v !== 'number') return ''
  const d = props.awareness?.peak_fav_date
  return d ? `${v}（${d}）` : `${v}`
})

const minText = computed(() => {
  const v = props.awareness?.min_favorability
  if (typeof v !== 'number') return ''
  const d = props.awareness?.min_fav_date
  return d ? `${v}（${d}）` : `${v}`
})

const hasAnyData = computed(() => trail.value.length > 0 || milestones.value.length > 0)

/**
 * 数据稀疏（不足以画出"变化"）→ 给一句引导。
 *
 * 条件不是"完全没有"，而是"看不出趋势"：只有 1 条里程碑或 1 个好感点时，
 * 页面会留一大片空白，用户不知道是坏了还是没数据。
 */
const isSparse = computed(() => trail.value.length < 2 && milestones.value.length < 2)

/** 好感折线：按 value 归一化到 0-100，再映射到画布高度 */
const sparkDots = computed(() => {
  const list = trail.value
  if (list.length < 2) return []
  const step = list.length > 1 ? SPARK_W / (list.length - 1) : SPARK_W
  return list.map((p, i) => {
    const value = Math.min(Math.max(Number(p.value) || 0, 0), 100)
    return {
      date: p.date,
      x: Math.round(i * step * 100) / 100,
      // y 轴翻转（SVG 原点在左上），留 6px 上下边距
      y: Math.round((SPARK_H - 6 - (value / 100) * (SPARK_H - 12)) * 100) / 100,
    }
  })
})

const sparkPoints = computed(() => sparkDots.value.map((p) => `${p.x},${p.y}`).join(' '))
</script>

<style scoped>
.rel-timeline {
  padding: 4px 0;
}

.days-hero {
  text-align: center;
  padding: 18px 0 22px;
}

.days-number {
  font-size: 44px;
  font-weight: 700;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}

.days-unit {
  font-size: 16px;
  color: var(--text-secondary);
  margin-left: 4px;
}

.days-caption {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--text-secondary);
}

.since {
  opacity: 0.75;
}

.tl-block {
  margin-bottom: 22px;
}

.tl-title {
  font-size: 14px;
  margin: 0 0 10px;
  color: var(--text-primary);
}

.spark {
  width: 100%;
  height: 64px;
  display: block;
}

.spark-line {
  fill: none;
  stroke: #60a5fa;
  stroke-width: 2;
  stroke-linejoin: round;
  vector-effect: non-scaling-stroke;
}

.spark-dot {
  fill: #93c5fd;
}

.spark-axis {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: var(--text-secondary);
  margin-top: 4px;
  opacity: 0.8;
}

.tl-hint {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--text-secondary);
}

.peak {
  color: #34d399;
}

.min {
  color: #f87171;
}

.ms-list {
  list-style: none;
  margin: 0;
  padding: 0 0 0 4px;
}

.ms-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 0;
  font-size: 13px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.ms-item:last-child {
  border-bottom: none;
}

.ms-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #fbbf24;
  flex: 0 0 auto;
}

.ms-date {
  color: var(--text-secondary);
  font-variant-numeric: tabular-nums;
}

.ms-change {
  color: var(--text-primary);
}

.ms-arrow {
  color: var(--text-secondary);
  margin: 0 2px;
}

.empty-hint {
  text-align: center;
  padding: 28px 16px;
  font-size: 13px;
  color: var(--text-secondary);
}
</style>
