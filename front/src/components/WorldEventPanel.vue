<template>
  <section class="event-panel">
    <div class="event-head">
      <h2 class="event-title">往世界里加一件事</h2>
      <p class="event-sub">
        注入后，NPC 会在对话里自然地提起它 —— 这条链路一直存在，只是以前没有入口。
      </p>
    </div>

    <div class="event-form">
      <input
        v-model="title"
        class="event-input"
        placeholder="事件标题，如：下周有校园祭"
        @keydown.enter="submit"
      />
      <input
        v-model="description"
        class="event-input"
        placeholder="一句话描述（可选），如：为期两天，各社团都要出摊位"
        @keydown.enter="submit"
      />
      <div class="event-importance">
        <label for="evt-importance">重要性</label>
        <input
          id="evt-importance"
          v-model.number="importance"
          class="event-importance-input"
          type="number"
          min="1"
          max="10"
        />
        <span class="event-importance-hint">1-10，越大越可能被 NPC 提起</span>
      </div>
      <button
        class="event-submit"
        :disabled="!title.trim() || submitting"
        @click="submit"
      >
        {{ submitting ? '注入中…' : '注入事件' }}
      </button>
    </div>

    <p v-if="message" class="event-message" :class="{ 'event-message--err': isError }">
      {{ message }}
    </p>

    <div v-if="loading" class="event-hint">正在读世界状态…</div>
    <template v-else>
      <h3 class="event-list-title">进行中的事件（{{ running.length }}）</h3>
      <div v-if="!running.length" class="event-hint">这个世界现在很平静。</div>
      <ul v-else class="event-list">
        <li v-for="ev in running" :key="ev.id" class="event-item">
          <span class="event-item-title">{{ ev.title }}</span>
          <span class="event-item-meta">
            重要性 {{ ev.importance }}<span v-if="ev.progress"> · 进度 {{ ev.progress }}%</span>
          </span>
          <p v-if="ev.description" class="event-item-desc">{{ ev.description }}</p>
        </li>
      </ul>

      <h3 v-if="history.length" class="event-list-title">已结束（{{ history.length }}）</h3>
      <ul v-if="history.length" class="event-list event-list--muted">
        <li v-for="ev in history" :key="ev.id" class="event-item">
          <span class="event-item-title">{{ ev.title }}</span>
          <span class="event-item-meta">重要性 {{ ev.importance }}</span>
        </li>
      </ul>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { createWorldEvent, getWorldEvents, type WorldEvent } from '@/api/world'

const title = ref('')
const description = ref('')
const importance = ref(5)
const submitting = ref(false)
const message = ref('')
const isError = ref(false)
const loading = ref(true)

const current = ref<WorldEvent[]>([])
const history = ref<WorldEvent[]>([])

const running = computed(() =>
  current.value.filter((e) => e.status === 'running'),
)

async function load() {
  loading.value = true
  try {
    const res = await getWorldEvents()
    current.value = res.current_events ?? []
    history.value = res.history_events ?? []
  } catch {
    /* 读不到就显示空态，不用错误打扰（日报页本身还有别的内容） */
  } finally {
    loading.value = false
  }
}

async function submit() {
  const t = title.value.trim()
  if (!t || submitting.value) return
  submitting.value = true
  isError.value = false
  message.value = ''
  try {
    const res = await createWorldEvent({
      title: t,
      description: description.value.trim(),
      importance: importance.value,
    })
    if (res.error) {
      isError.value = true
      message.value = res.error
    } else {
      message.value = `已注入「${res.event?.title || t}」—— 去聊天里看看谁会提起它。`
      title.value = ''
      description.value = ''
      // 用返回的列表刷新（省一次请求）
      if (Array.isArray(res.current_events)) {
        current.value = res.current_events
      }
    }
  } catch (e) {
    isError.value = true
    message.value = e instanceof Error ? e.message : '注入失败'
  } finally {
    submitting.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.event-panel {
  margin: 0 0 22px;
  padding: 16px 18px;
  border-radius: 14px;
  background: var(--bg-secondary, #1f2430);
  border: 1px solid var(--border-color, rgba(255, 255, 255, 0.1));
}

.event-head { margin-bottom: 12px; }

.event-title {
  margin: 0;
  font-size: 15px;
  color: var(--text-primary);
}

.event-sub {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--text-secondary);
}

.event-form {
  display: grid;
  gap: 8px;
}

.event-input {
  width: 100%;
  padding: 9px 11px;
  border-radius: 9px;
  border: 1px solid var(--border-color, rgba(255, 255, 255, 0.12));
  background: rgba(255, 255, 255, 0.04);
  color: var(--text-primary);
  font-size: 13px;
}

.event-input:focus {
  outline: none;
  border-color: rgba(129, 140, 248, 0.6);
}

.event-importance {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--text-secondary);
}

.event-importance-input {
  width: 62px;
  padding: 6px 8px;
  border-radius: 8px;
  border: 1px solid var(--border-color, rgba(255, 255, 255, 0.12));
  background: rgba(255, 255, 255, 0.04);
  color: var(--text-primary);
  font-size: 13px;
}

.event-importance-hint { opacity: 0.75; }

.event-submit {
  justify-self: start;
  margin-top: 2px;
  padding: 8px 18px;
  border: none;
  border-radius: 9px;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: #fff;
  font-size: 13px;
  cursor: pointer;
}

.event-submit:disabled { opacity: 0.5; cursor: default; }

.event-message {
  margin: 10px 0 0;
  font-size: 12px;
  color: #6ee7b7;
}

.event-message--err { color: #fca5a5; }

.event-hint {
  margin: 12px 0 0;
  font-size: 12px;
  color: var(--text-secondary);
}

.event-list-title {
  margin: 16px 0 8px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
}

.event-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 8px;
}

.event-item {
  padding: 9px 11px;
  border-radius: 9px;
  background: rgba(255, 255, 255, 0.04);
  display: grid;
  gap: 3px;
}

.event-list--muted .event-item { opacity: 0.6; }

.event-item-title {
  font-size: 13px;
  color: var(--text-primary);
}

.event-item-meta {
  font-size: 11px;
  color: var(--text-secondary);
}

.event-item-desc {
  margin: 2px 0 0;
  font-size: 12px;
  color: var(--text-secondary);
}
</style>
