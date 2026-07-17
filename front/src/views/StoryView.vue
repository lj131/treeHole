<template>
  <div class="story-page">
    <header class="page-head">
      <h2>📖 剧情可视化</h2>
      <button class="btn" :disabled="loading" @click="load">刷新</button>
    </header>

    <div v-if="loading && !stories.length" class="loading-hint">加载中...</div>
    <div v-else-if="error" class="error-hint">{{ error }}</div>
    <div
      v-else-if="!activeStories.length && !history.length"
      class="empty-hint"
    >
      暂无剧情，多和角色聊聊吧
    </div>
    <template v-else>
      <section v-if="activeStories.length" class="story-section">
        <h3>进行中</h3>
        <div v-for="s in activeStories" :key="s.id" class="story-item">
          <StoryTree :story="s" />
          <button
            class="btn sm advance-btn"
            :disabled="advancingId === s.id"
            @click="advance(s.id!)"
          >
            {{ advancingId === s.id ? '推进中…' : '推进剧情' }}
          </button>
        </div>
      </section>

      <section v-if="history.length" class="story-section">
        <h3>已完结</h3>
        <div v-for="h in history" :key="h.id" class="history-card">
          <span class="story-type-badge" :class="'type-' + (h.type || 'main')">
            {{ h.type === 'side' ? '支线' : '主线' }}
          </span>
          <b>{{ h.title || '未命名' }}</b>
          <span class="history-stages">{{ h.stages?.length ?? 0 }} 阶段</span>
        </div>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { getStory, advanceStory } from '@/api'
import type { Story, StoryHistoryItem } from '@/types/api'
import StoryTree from '@/components/StoryTree.vue'

const stories = ref<Story[]>([])
const history = ref<StoryHistoryItem[]>([])
const loading = ref(true)
const error = ref<string | null>(null)
const advancingId = ref<string | null>(null)

const activeStories = computed(() =>
  stories.value
    .filter((s) => s.status === 'active')
    .sort((a, b) => {
      if (a.type === 'main' && b.type !== 'main') return -1
      if (a.type !== 'main' && b.type === 'main') return 1
      return 0
    }),
)

async function load() {
  loading.value = true
  error.value = null
  try {
    const res = await getStory()
    stories.value = res.stories ?? []
    history.value = res.story_history ?? []
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

async function advance(storyId: string) {
  advancingId.value = storyId
  try {
    const res = await advanceStory(storyId)
    if ('error' in res) {
      error.value = res.error
    } else {
      error.value = null
      await load()
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : '推进失败'
  } finally {
    advancingId.value = null
  }
}

onMounted(load)
</script>

<style scoped>
.story-page {
  max-width: 900px;
  margin: 0 auto;
  padding: 20px;
}
.page-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.page-head h2 {
  margin: 0;
  color: var(--text-primary, #e4e4e7);
}
.story-section {
  margin-bottom: 24px;
}
.story-section h3 {
  color: var(--text-secondary, #a0a0b8);
  font-size: 0.95rem;
  margin: 0 0 12px;
}
.story-item {
  margin-bottom: 8px;
}
.advance-btn {
  margin-top: -8px;
  margin-bottom: 16px;
}
.history-card {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  background: var(--bg-secondary, #1e1e2e);
  border: 1px solid var(--border-color, #33334a);
  border-radius: 8px;
  margin-bottom: 8px;
}
.history-stages {
  margin-left: auto;
  color: var(--text-secondary, #a0a0b8);
  font-size: 0.85rem;
}
.loading-hint,
.empty-hint,
.error-hint {
  padding: 24px;
  text-align: center;
  color: var(--text-secondary, #a0a0b8);
}
.error-hint {
  color: #fca5a5;
}
</style>
