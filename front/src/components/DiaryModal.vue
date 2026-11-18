<template>
  <div v-if="open" class="diary-overlay" @click.self="$emit('close')">
    <div class="diary-sheet">
      <!-- 抬头：像翻开的日记本 -->
      <div class="diary-top">
        <div class="diary-title">
          <span class="diary-cover">📔</span>
          <div>
            <h3>{{ name }}的日记</h3>
            <p class="diary-sub">偷看一眼她今天写了什么</p>
          </div>
        </div>
        <button class="diary-close" @click="$emit('close')">✕</button>
      </div>

      <!-- 加载态：懒生成要 1-3 秒 -->
      <div v-if="loading && !current" class="diary-body diary-loading">
        <span class="spinner" />
        <p>她正在写今天的日记…</p>
        <p class="diary-hint">第一次打开会现写一篇，要等一下</p>
      </div>

      <!-- 空态：素材不足，她今天没写 -->
      <div v-else-if="!current" class="diary-body diary-empty">
        <p class="diary-empty-title">她今天没写日记</p>
        <p class="diary-hint">大概是今天世界里没什么值得记的事</p>
      </div>

      <!-- 正文 -->
      <div v-else class="diary-body">
        <p class="diary-date">{{ current.date }}</p>
        <p class="diary-text">{{ current.text }}</p>
      </div>

      <!-- 历史几篇 -->
      <div v-if="history.length > 1" class="diary-history">
        <div class="diary-history-head">更早的几篇</div>
        <button
          v-for="(h, i) in history"
          :key="i"
          class="diary-history-item"
          :class="{ active: current && h.date === current.date }"
          @click="current = h"
        >
          <span class="diary-history-date">{{ h.date }}</span>
          <span class="diary-history-snippet">{{ h.text.slice(0, 18) }}…</span>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { getDiary, type DiaryEntry } from '@/api/diary'
import { useChatStore } from '@/stores/chatStore'

const props = defineProps<{ open: boolean }>()
defineEmits<{ (e: 'close'): void }>()

const store = useChatStore()
const loading = ref(false)
const diary = ref<DiaryEntry | null>(null)
const history = ref<DiaryEntry[]>([])

const name = computed(() => store.character?.name || '她')

/** 默认显示最新那篇 = 今天的；没今天的就显示历史第一篇 */
const current = ref<DiaryEntry | null>(null)
watch(
  () => props.open,
  async (isOpen) => {
    if (!isOpen) return
    // 已经加载过就不再请求（幂等，但也没必要重复）
    if (diary.value || history.value.length) return
    loading.value = true
    try {
      const res = await getDiary()
      diary.value = res.diary
      history.value = res.history ?? []
      current.value = res.diary ?? res.history?.[0] ?? null
    } catch {
      /* 取读失败就当"没写"，界面给空态，不弹错误打扰 */
    } finally {
      loading.value = false
    }
  },
  { immediate: true },
)
</script>

<style scoped>
.diary-overlay {
  position: fixed;
  inset: 0;
  z-index: 1100;
  display: grid;
  place-items: center;
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(4px);
}

.diary-sheet {
  width: min(420px, 90vw);
  max-height: 78vh;
  display: flex;
  flex-direction: column;
  border-radius: var(--radius-xl);
  background: var(--bg-secondary, #1f2430);
  border: 1px solid var(--border-color, rgba(255, 255, 255, 0.12));
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.45);
  overflow: hidden;
}

.diary-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 16px 18px 12px;
  border-bottom: 1px solid var(--border-color, rgba(255, 255, 255, 0.08));
}

.diary-title {
  display: flex;
  gap: 10px;
  align-items: center;
}

.diary-cover { font-size: 26px; }

.diary-top h3 {
  margin: 0;
  font-size: 15px;
  color: var(--text-primary);
}

.diary-sub {
  margin: 2px 0 0;
  font-size: 11px;
  color: var(--text-secondary);
}

.diary-close {
  border: none;
  background: none;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 14px;
}

.diary-body {
  padding: 16px 18px;
  /* 手账感：行距宽、左对齐、衬线 */
  font-family: "Songti SC", "Noto Serif CJK SC", Georgia, serif;
  line-height: 1.9;
  font-size: 14px;
  color: var(--text-primary);
  white-space: pre-wrap;
}

.diary-date {
  margin: 0 0 8px;
  font-size: 11px;
  letter-spacing: 1px;
  color: var(--text-secondary);
}

.diary-text { margin: 0; }

.diary-loading,
.diary-empty {
  display: grid;
  place-items: center;
  gap: 8px;
  padding: 34px 18px;
  text-align: center;
}

.diary-empty-title { margin: 0; font-size: 14px; }
.diary-hint { margin: 0; font-size: 11px; color: var(--text-secondary); }

.spinner {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  border: 2px solid rgba(129, 140, 248, 0.25);
  border-top-color: #818cf8;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.diary-history {
  padding: 10px 18px 16px;
  border-top: 1px solid var(--border-color, rgba(255, 255, 255, 0.08));
}

.diary-history-head {
  font-size: 11px;
  color: var(--text-secondary);
  margin-bottom: 8px;
}

.diary-history-item {
  display: flex;
  gap: 10px;
  width: 100%;
  padding: 7px 9px;
  margin-bottom: 6px;
  border: none;
  border-radius: var(--radius-sm);
  background: rgba(255, 255, 255, 0.04);
  color: var(--text-secondary);
  font-size: 12px;
  cursor: pointer;
  text-align: left;
}

.diary-history-item:hover { background: rgba(255, 255, 255, 0.08); }
.diary-history-item.active { color: var(--text-primary); background: rgba(129, 140, 248, 0.16); }

.diary-history-date { flex: 0 0 auto; opacity: 0.75; }
.diary-history-snippet { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
