<template>
  <div class="digest-view">
    <header class="digest-header">
      <div>
        <h1>📰 世界日报</h1>
        <p class="subtitle">
          你不在的时候，世界一直在动。这里是你错过的一切。
        </p>
      </div>
      <div class="range-switch">
        <button
          v-for="opt in RANGE_OPTIONS"
          :key="opt"
          class="range-btn"
          :class="{ active: days === opt }"
          :disabled="loading"
          @click="setDays(opt)"
        >
          {{ opt }} 天
        </button>
      </div>
    </header>

    <!-- 概览：一句话说清这段时间发生了什么 -->
    <section v-if="!loading && !error && digest" class="digest-summary">
      <span class="summary-text">{{ digest.summary }}</span>
      <span v-if="digest.total" class="summary-total">共 {{ digest.total }} 条</span>
    </section>

    <div v-if="loading" class="hint-line">正在整理这段时间发生的事...</div>
    <p v-else-if="error" class="error-line">{{ error }}</p>

    <template v-else-if="digest">
      <div v-if="!groups.length" class="empty-state">
        <p class="empty-title">这段时间世界很安静</p>
        <p class="empty-hint">换个更长的时间范围试试，或者去和角色聊聊天让世界动起来。</p>
      </div>

      <section v-for="group in groups" :key="group.date" class="day-group">
        <h2 class="day-label">
          {{ group.label }}
          <span class="day-date">{{ group.date }}</span>
        </h2>
        <ul class="entry-list">
          <li v-for="(entry, i) in group.entries" :key="`${entry.at}-${i}`" class="entry">
            <span class="entry-icon" :class="kindMeta(entry.kind).tone">
              {{ kindMeta(entry.kind).icon }}
            </span>
            <div class="entry-body">
              <div class="entry-head">
                <span class="entry-time">{{ timeOf(entry.at) }}</span>
                <span class="entry-kind">{{ kindMeta(entry.kind).label }}</span>
                <span class="entry-title">{{ entry.title }}</span>
              </div>
              <p v-if="entry.detail" class="entry-detail">{{ entry.detail }}</p>
              <div v-if="entry.actors.length" class="entry-actors">
                <span v-for="a in entry.actors" :key="a" class="actor-chip">{{ a }}</span>
              </div>
            </div>
          </li>
        </ul>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { getWorldDigest } from '@/api/world'
import { errorMessage } from '@/utils/error'
import { groupByDate, kindMeta, localToday, timeOf } from '@/utils/digest'
import type { WorldDigest } from '@/types/api'

/** 可选时间范围。1 = 只看今天。 */
const RANGE_OPTIONS = [1, 3, 7] as const

/** 默认 7 天（和后端 DEFAULT_DAYS 一致）：陪伴类用户可能几天才来一次，
 *  3 天窗口经常只有一两条，一进来看到"世界很安静"体验很差。 */
const days = ref<number>(7)
const digest = ref<WorldDigest | null>(null)
const loading = ref(false)
const error = ref('')

const groups = computed(() =>
  digest.value ? groupByDate(digest.value.entries, localToday()) : [],
)

async function load() {
  loading.value = true
  error.value = ''
  try {
    digest.value = await getWorldDigest(days.value)
  } catch (e: unknown) {
    error.value = errorMessage(e, '加载世界日报失败')
  } finally {
    loading.value = false
  }
}

function setDays(next: number) {
  if (days.value === next) return
  days.value = next
  load()
}

onMounted(load)
</script>

<style scoped>
.digest-view {
  max-width: 820px;
  margin: 0 auto;
  padding: 24px 16px 64px;
}

.digest-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}

.digest-header h1 {
  font-size: 22px;
  margin: 0 0 6px;
  color: var(--text-primary);
}

.subtitle {
  margin: 0;
  font-size: 13px;
  color: var(--text-secondary);
}

.range-switch {
  display: flex;
  gap: 6px;
}

.range-btn {
  padding: 5px 12px;
  font-size: 13px;
  border-radius: 999px;
  border: 1px solid var(--border-color, rgba(255, 255, 255, 0.16));
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
}

.range-btn.active {
  background: var(--accent-color, #6366f1);
  border-color: transparent;
  color: #fff;
}

.range-btn:disabled {
  opacity: 0.5;
  cursor: default;
}

.digest-summary {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  margin-bottom: 20px;
  border-radius: 10px;
  background: rgba(99, 102, 241, 0.1);
  border: 1px solid rgba(99, 102, 241, 0.24);
}

.summary-text {
  font-size: 14px;
  color: var(--text-primary);
}

.summary-total {
  font-size: 12px;
  color: var(--text-secondary);
  white-space: nowrap;
}

.day-group {
  margin-bottom: 24px;
}

.day-label {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 15px;
  margin: 0 0 10px;
  color: var(--text-primary);
}

.day-date {
  font-size: 12px;
  font-weight: normal;
  color: var(--text-secondary);
}

.entry-list {
  list-style: none;
  margin: 0;
  padding: 0 0 0 6px;
  border-left: 2px solid var(--border-color, rgba(255, 255, 255, 0.1));
}

.entry {
  display: flex;
  gap: 10px;
  padding: 8px 0 12px 12px;
  position: relative;
}

.entry-icon {
  flex: 0 0 auto;
  width: 26px;
  height: 26px;
  display: grid;
  place-items: center;
  font-size: 14px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.06);
}

.entry-body {
  min-width: 0;
  flex: 1;
}

.entry-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
}

.entry-time {
  font-size: 12px;
  color: var(--text-secondary);
  font-variant-numeric: tabular-nums;
}

.entry-kind {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.07);
  color: var(--text-secondary);
}

.entry-title {
  font-size: 14px;
  color: var(--text-primary);
}

.entry-detail {
  margin: 4px 0 0;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-secondary);
  white-space: pre-wrap;
  word-break: break-word;
}

.entry-actors {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 6px;
}

.actor-chip {
  font-size: 11px;
  padding: 1px 7px;
  border-radius: 999px;
  background: rgba(16, 185, 129, 0.14);
  color: #34d399;
}

.hint-line,
.error-line {
  padding: 12px 14px;
  border-radius: 8px;
  font-size: 13px;
}

.hint-line {
  color: var(--text-secondary);
  background: rgba(255, 255, 255, 0.04);
}

.error-line {
  color: #f87171;
  background: rgba(248, 113, 113, 0.1);
}

.empty-state {
  text-align: center;
  padding: 48px 16px;
}

.empty-title {
  font-size: 15px;
  color: var(--text-primary);
  margin: 0 0 8px;
}

.empty-hint {
  font-size: 13px;
  color: var(--text-secondary);
  margin: 0;
}

/* 类别配色：只改图标底色，不抢内容的注意力 */
.tone-world { background: rgba(59, 130, 246, 0.18); }
.tone-npc { background: rgba(168, 85, 247, 0.18); }
.tone-gossip { background: rgba(244, 114, 182, 0.18); }
.tone-impact { background: rgba(14, 165, 233, 0.18); }
.tone-story { background: rgba(245, 158, 11, 0.18); }
.tone-dream { background: rgba(139, 92, 246, 0.2); }
.tone-proactive { background: rgba(16, 185, 129, 0.18); }
.tone-milestone { background: rgba(250, 204, 21, 0.2); }
.tone-memory { background: rgba(148, 163, 184, 0.18); }
.tone-default { background: rgba(255, 255, 255, 0.06); }
</style>
