<template>
  <div class="memory-page">
    <!-- 头部 -->
    <header class="memory-header glass-card">
      <div>
        <h1 class="page-title"><span>🧠</span> 记忆中心</h1>
        <p class="page-subtitle">查看与管理 AI 记住的一切</p>
      </div>
      <button class="btn primary" :disabled="loading" @click="loadAll">
        <span v-if="loading">加载中...</span>
        <span v-else>↻ 刷新</span>
      </button>
    </header>

    <p v-if="error" class="error-bar">{{ error }}</p>

    <!-- 统计卡片墙 -->
    <section class="stats-row">
      <div v-for="c in collectionMeta" :key="c.key" class="stat-card glass-card">
        <span class="stat-icon">{{ c.icon }}</span>
        <div>
          <div class="stat-count">{{ stats?.collections?.[c.key] ?? 0 }}</div>
          <div class="stat-label">{{ c.label }}</div>
        </div>
      </div>
    </section>

    <!-- 语义搜索 -->
    <section class="glass-card search-card">
      <h2 class="section-title"><span>🔍</span> 语义搜索</h2>
      <p class="card-hint">输入问题，从所有记忆里语义检索最相关的内容</p>
      <div class="search-row">
        <input
          v-model="searchQuery"
          class="search-input"
          placeholder="如：我在哪工作？/ 发生过什么故事？"
          @keydown.enter="doSearch"
        />
        <select v-model="searchTopK" class="search-select">
          <option :value="3">3 条</option>
          <option :value="5">5 条</option>
          <option :value="10">10 条</option>
        </select>
        <button class="btn primary" :disabled="!searchQuery.trim() || searching" @click="doSearch">
          {{ searching ? '搜索中...' : '搜索' }}
        </button>
      </div>

      <div v-if="searched && searchResults.length === 0" class="empty-hint">没有找到相关记忆</div>
      <div v-else class="search-results">
        <div v-for="(r, i) in searchResults" :key="i" class="search-result-item">
          <div class="result-header">
            <span class="collection-tag" :class="'tag-' + r.collection">{{ collectionLabel(r.collection) }}</span>
            <span class="relevance" :class="relevanceClass(r.score)">相关度 {{ relevancePercent(r.score) }}%</span>
          </div>
          <p class="result-text">{{ r.text }}</p>
        </div>
      </div>
    </section>

    <!-- 全景概览 -->
    <section v-if="fullMemory" class="overview-section">
      <h2 class="section-title"><span>📋</span> 全景概览</h2>
      <div class="overview-grid">
        <!-- 画像 -->
        <div class="glass-card overview-card">
          <div class="card-head">
            <h3>👤 用户画像</h3>
            <button v-if="!editingProfile && !isReadonly" class="btn sm" @click="startEditProfile">编辑</button>
          </div>
          <template v-if="!editingProfile">
            <div class="kv"><span>姓名</span><b>{{ fullMemory.profile?.name || '—' }}</b></div>
            <div class="kv"><span>城市</span><b>{{ fullMemory.profile?.city || '—' }}</b></div>
            <div class="kv"><span>职业</span><b>{{ fullMemory.profile?.job || '—' }}</b></div>
            <div class="kv"><span>情绪</span><b>{{ fullMemory.profile?.mood || '—' }}</b></div>
            <div v-if="fullMemory.profile?.recent_topics?.length" class="kv">
              <span>话题</span>
              <div class="tags">
                <span v-for="t in fullMemory.profile.recent_topics" :key="t" class="topic-tag">{{ t }}</span>
              </div>
            </div>
          </template>
          <template v-else>
            <div class="kv"><span>姓名</span><input v-model="profileDraft.name" class="kv-input" /></div>
            <div class="kv"><span>城市</span><input v-model="profileDraft.city" class="kv-input" /></div>
            <div class="kv"><span>职业</span><input v-model="profileDraft.job" class="kv-input" /></div>
            <div class="kv"><span>情绪</span><input v-model="profileDraft.mood" class="kv-input" /></div>
            <div class="edit-actions">
              <button class="btn sm primary" :disabled="savingProfile" @click="saveProfileEdit">
                {{ savingProfile ? '保存中...' : '保存' }}
              </button>
              <button class="btn sm" @click="editingProfile = false">取消</button>
            </div>
          </template>
        </div>

        <!-- 关系 -->
        <div class="glass-card overview-card">
          <h3>💝 关系</h3>
          <div class="kv"><span>等级</span><b>{{ fullMemory.relationship?.level || '—' }}</b></div>
          <div class="favor-bar">
            <div class="favor-fill" :style="{ width: (fullMemory.favorability ?? 0) + '%' }"></div>
            <span class="favor-text">{{ fullMemory.favorability ?? 0 }} / 100</span>
          </div>
          <div v-if="fullMemory.relationship?.last_reason" class="kv reason">
            <span>变化原因</span>
            <p class="reason-text">{{ fullMemory.relationship.last_reason }}</p>
          </div>
        </div>

        <!-- 状态 -->
        <div class="glass-card overview-card">
          <h3>🎭 角色状态</h3>
          <div class="kv"><span>心情</span><b>{{ fullMemory.character_state?.mood || '—' }}</b></div>
          <div class="kv"><span>精力</span><b>{{ fullMemory.character_state?.energy ?? '—' }}</b></div>
          <div v-if="currentEventTitle" class="kv">
            <span>当前事件</span>
            <p class="reason-text">{{ currentEventTitle }}</p>
          </div>
        </div>

        <!-- 剧情（多线） -->
        <div class="glass-card overview-card story-overview">
          <h3>📖 剧情</h3>
          <div v-if="activeStories.length">
            <div v-for="s in activeStories" :key="s.id" class="story-mini">
              <div class="story-mini-head">
                <span class="story-type-badge" :class="'type-' + (s.type || 'main')">
                  {{ s.type === 'side' ? '支线' : '主线' }}
                </span>
                <b>{{ s.title }}</b>
              </div>
              <p v-if="s.description" class="reason-text">{{ s.description }}</p>
              <div class="kv">
                <span>进度</span>
                <b>第 {{ (s.stage ?? 0) + 1 }} / {{ (s.stages?.length ?? 0) }} 阶段</b>
              </div>
              <div v-if="s.branch_points?.length" class="branch-summary">
                📌 {{ s.branch_points.length }} 个分支存档点
              </div>
            </div>
          </div>
          <div v-else class="empty-hint">暂无剧情</div>
        </div>
      </div>
    </section>

    <!-- 分类管理 Tab -->
    <section class="glass-card manage-section">
      <div class="tabs">
        <button
          v-for="t in tabs"
          :key="t.key"
          class="tab-btn"
          :class="{ active: activeTab === t.key }"
          @click="activeTab = t.key"
        >
          {{ t.icon }} {{ t.label }}
          <span class="tab-count">{{ tabCount(t.key) }}</span>
        </button>
      </div>

      <!-- 长期记忆 -->
      <div v-if="activeTab === 'long_memory'" class="tab-panel">
        <div class="add-row">
          <input v-if="!isReadonly" v-model="newMemory" placeholder="添加新的长期记忆..." @keydown.enter="handleAddMemory" />
          <button v-if="!isReadonly" class="btn primary" :disabled="!newMemory.trim()" @click="handleAddMemory">添加</button>
        </div>
        <div class="manage-list">
          <div v-for="(mem, i) in longMemory" :key="i" class="manage-row">
            <template v-if="editingMemoryIndex === i">
              <input v-model="editingMemoryText" class="edit-input" />
              <button class="btn sm primary" @click="confirmEditMemory(mem)">确认</button>
              <button class="btn sm" @click="editingMemoryIndex = -1">取消</button>
            </template>
            <template v-else>
              <span class="row-text">{{ mem }}</span>
              <div class="row-actions">
                <button v-if="!isReadonly" class="btn sm" @click="editingMemoryIndex = i; editingMemoryText = mem">编辑</button>
                <button v-if="!isReadonly" class="btn sm danger" @click="handleDeleteMemory(mem)">删除</button>
              </div>
            </template>
          </div>
          <p v-if="longMemory.length === 0" class="empty-hint">暂无长期记忆</p>
        </div>
      </div>

      <!-- 事件 -->
      <div v-if="activeTab === 'events'" class="tab-panel">
        <div class="add-row">
          <input v-if="!isReadonly" v-model="newEvent" placeholder="添加事件..." @keydown.enter="handleAddEvent" />
          <button v-if="!isReadonly" class="btn primary" :disabled="!newEvent.trim()" @click="handleAddEvent">添加</button>
        </div>
        <div class="manage-list">
          <div v-for="(ev, i) in events" :key="i" class="manage-row">
            <div class="event-row">
              <span class="row-text">{{ ev.event }}</span>
              <span v-if="ev.time" class="event-time">{{ ev.time }}</span>
            </div>
          </div>
          <p v-if="events.length === 0" class="empty-hint">暂无事件</p>
        </div>
      </div>

      <!-- 聊天摘要（只读） -->
      <div v-if="activeTab === 'chat_summary'" class="tab-panel">
        <div class="manage-list">
          <div v-for="(s, i) in chatSummary" :key="i" class="manage-row">
            <span class="row-text summary-text">{{ s }}</span>
          </div>
          <p v-if="chatSummary.length === 0" class="empty-hint">暂无聊天摘要</p>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { useAuthStore } from '@/stores/authStore'
import {
  getFullMemory,
  getMemoryStats,
  getMemorySearch,
  getLongMemory,
  addLongMemory,
  updateLongMemory,
  deleteLongMemory,
  getEvents,
  addEvent,
  saveProfile,
} from '@/api'
import type { FullMemory, MemorySearchResult, UserProfile } from '@/types/api'

const auth = useAuthStore()
const isReadonly = computed(() => auth.isPending)

// ---- 主数据 ----
const loading = ref(false)
const error = ref('')
const fullMemory = ref<FullMemory | null>(null)
const stats = ref<{ collections: Record<string, number> } | null>(null)

// ---- 搜索 ----
const searchQuery = ref('')
const searchTopK = ref(5)
const searching = ref(false)
const searched = ref(false)
const searchResults = ref<MemorySearchResult[]>([])

// ---- 画像编辑 ----
const editingProfile = ref(false)
const savingProfile = ref(false)
const profileDraft = reactive<UserProfile>({ name: '', city: '', job: '', mood: '' })

// ---- 长期记忆 ----
const longMemory = ref<string[]>([])
const newMemory = ref('')
const editingMemoryIndex = ref(-1)
const editingMemoryText = ref('')

// ---- 事件 ----
const events = ref<{ time?: string; event: string }[]>([])
const newEvent = ref('')

// ---- 聊天摘要 ----
const chatSummary = ref<string[]>([])

// ---- Tab ----
const activeTab = ref<'long_memory' | 'events' | 'chat_summary'>('long_memory')
const tabs = [
  { key: 'long_memory' as const, label: '长期记忆', icon: '🧠' },
  { key: 'events' as const, label: '事件', icon: '🌟' },
  { key: 'chat_summary' as const, label: '聊天摘要', icon: '💬' },
]

// 集合元信息（统计卡片 + 标签）
const collectionMeta = [
  { key: 'profile', label: '用户画像', icon: '👤' },
  { key: 'long_memory', label: '长期记忆', icon: '🧠' },
  { key: 'story', label: '剧情', icon: '📖' },
  { key: 'events', label: '事件', icon: '🌟' },
  { key: 'relationship', label: '关系', icon: '💝' },
  { key: 'chat_summary', label: '聊天摘要', icon: '💬' },
]

function collectionLabel(key: string): string {
  return collectionMeta.find((c) => c.key === key)?.label ?? key
}

function tabCount(key: string): number {
  if (key === 'long_memory') return longMemory.value.length
  if (key === 'events') return events.value.length
  if (key === 'chat_summary') return chatSummary.value.length
  return 0
}

// current_event 可能是 string 或对象，统一取标题文本
const currentEventTitle = computed(() => {
  const ce = fullMemory.value?.character_state?.current_event
  if (!ce) return ''
  return typeof ce === 'string' ? ce : ce.title ?? ''
})

// 多剧情：取所有 active 的，主线在前
const activeStories = computed(() => {
  const stories = fullMemory.value?.stories ?? []
  return stories
    .filter((s) => s.status === 'active')
    .sort((a, b) => {
      if (a.type === 'main' && b.type !== 'main') return -1
      if (a.type !== 'main' && b.type === 'main') return 1
      return 0
    })
})

// score → 相关度百分比（实测 score 范围约 0.9~1.3，越小越相关）
function relevancePercent(score: number): number {
  const min = 0.9
  const max = 1.3
  const pct = ((max - score) / (max - min)) * 100
  return Math.max(0, Math.min(100, Math.round(pct)))
}

function relevanceClass(score: number): string {
  const pct = relevancePercent(score)
  if (pct >= 66) return 'rel-high'
  if (pct >= 33) return 'rel-mid'
  return 'rel-low'
}

// ---- 加载 ----
async function loadAll() {
  loading.value = true
  error.value = ''
  try {
    const [fullRes, statsRes] = await Promise.all([getFullMemory(), getMemoryStats()])
    fullMemory.value = fullRes.memory
    stats.value = statsRes
    longMemory.value = fullRes.memory.long_memory ?? []
    events.value = fullRes.memory.events ?? []
    chatSummary.value = fullRes.memory.chat_summary ?? []
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

// ---- 搜索 ----
async function doSearch() {
  if (!searchQuery.value.trim()) return
  searching.value = true
  searched.value = true
  error.value = ''
  try {
    const res = await getMemorySearch(searchQuery.value.trim(), searchTopK.value)
    searchResults.value = res.results ?? []
  } catch (e) {
    error.value = e instanceof Error ? e.message : '搜索失败'
    searchResults.value = []
  } finally {
    searching.value = false
  }
}

// ---- 画像编辑 ----
function startEditProfile() {
  const p = fullMemory.value?.profile
  profileDraft.name = p?.name ?? ''
  profileDraft.city = p?.city ?? ''
  profileDraft.job = p?.job ?? ''
  profileDraft.mood = p?.mood ?? ''
  editingProfile.value = true
}

async function saveProfileEdit() {
  savingProfile.value = true
  try {
    await saveProfile({ ...profileDraft })
    // 本地更新
    if (fullMemory.value) {
      fullMemory.value.profile = { ...profileDraft }
    }
    editingProfile.value = false
  } catch (e) {
    error.value = e instanceof Error ? e.message : '保存画像失败'
  } finally {
    savingProfile.value = false
  }
}

// ---- 长期记忆 CRUD ----
async function handleAddMemory() {
  const text = newMemory.value.trim()
  if (!text) return
  try {
    const res = await addLongMemory(text)
    longMemory.value = res.long_memory ?? []
    newMemory.value = ''
    await refreshStats()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '添加失败'
  }
}

async function confirmEditMemory(oldText: string) {
  const newText = editingMemoryText.value.trim()
  if (!newText) return
  try {
    const res = await updateLongMemory(oldText, newText)
    longMemory.value = res.long_memory ?? []
    editingMemoryIndex.value = -1
  } catch (e) {
    error.value = e instanceof Error ? e.message : '更新失败'
  }
}

async function handleDeleteMemory(mem: string) {
  try {
    const res = await deleteLongMemory(mem)
    longMemory.value = res.long_memory ?? []
    await refreshStats()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '删除失败'
  }
}

// ---- 事件 ----
async function handleAddEvent() {
  const text = newEvent.value.trim()
  if (!text) return
  try {
    const res = await addEvent(text)
    events.value = res.events ?? []
    newEvent.value = ''
    await refreshStats()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '添加事件失败'
  }
}

async function refreshStats() {
  try {
    stats.value = await getMemoryStats()
  } catch {
    // 统计刷新失败不影响主流程
  }
}

onMounted(loadAll)
</script>

<style scoped>
.memory-page {
  min-height: calc(100vh - 64px);
  padding: 32px 24px;
  max-width: 1200px;
  margin: 0 auto;
  color: #e2e8f0;
}

.glass-card {
  background: rgba(255, 255, 255, 0.05);
  backdrop-filter: blur(10px);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 20px;
}

/* 头部 */
.memory-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 24px 28px;
  margin-bottom: 24px;
}
.page-title {
  font-size: 1.75rem;
  font-weight: 700;
  margin: 0 0 6px;
}
.page-subtitle {
  margin: 0;
  color: #94a3b8;
  font-size: 0.95rem;
}

.error-bar {
  padding: 10px 14px;
  border-radius: 12px;
  background: rgba(248, 113, 113, 0.12);
  border: 1px solid rgba(248, 113, 113, 0.3);
  color: #fca5a5;
  font-size: 0.88rem;
  margin-bottom: 16px;
}

/* 统计卡片墙 */
.stats-row {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 16px;
  margin-bottom: 28px;
}
.stat-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 18px 20px;
}
.stat-icon {
  font-size: 1.8rem;
}
.stat-count {
  font-size: 1.6rem;
  font-weight: 700;
  color: #c4b5fd;
}
.stat-label {
  font-size: 0.82rem;
  color: #94a3b8;
}

/* 通用 section */
.section-title {
  font-size: 1.2rem;
  font-weight: 600;
  margin: 0 0 14px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.card-hint {
  margin: 0 0 14px;
  color: #94a3b8;
  font-size: 0.85rem;
}

/* 搜索 */
.search-card {
  padding: 24px;
  margin-bottom: 28px;
}
.search-row {
  display: flex;
  gap: 10px;
  margin-bottom: 16px;
}
.search-input {
  flex: 1;
  padding: 10px 14px;
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(255, 255, 255, 0.04);
  color: #e2e8f0;
  font-size: 0.92rem;
  font-family: inherit;
}
.search-input:focus {
  outline: none;
  border-color: rgba(123, 92, 255, 0.6);
}
.search-select {
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(255, 255, 255, 0.04);
  color: #e2e8f0;
  font-size: 0.88rem;
}
.search-results {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.search-result-item {
  padding: 12px 14px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
}
.result-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}
.collection-tag {
  padding: 2px 10px;
  border-radius: 10px;
  font-size: 0.75rem;
  font-weight: 600;
}
.tag-profile { background: rgba(96, 165, 250, 0.2); color: #93c5fd; }
.tag-long_memory { background: rgba(167, 139, 250, 0.2); color: #c4b5fd; }
.tag-story { background: rgba(52, 211, 153, 0.2); color: #6ee7b7; }
.tag-events { background: rgba(251, 146, 60, 0.2); color: #fdba74; }
.tag-relationship { background: rgba(244, 114, 182, 0.2); color: #f9a8d4; }
.tag-chat_summary { background: rgba(148, 163, 184, 0.2); color: #cbd5e1; }
.relevance {
  font-size: 0.75rem;
  font-weight: 600;
}
.rel-high { color: #6ee7b7; }
.rel-mid { color: #fde68a; }
.rel-low { color: #fca5a5; }
.result-text {
  margin: 0;
  font-size: 0.9rem;
  color: #cbd5e1;
  line-height: 1.5;
}

/* 概览 */
.overview-section {
  margin-bottom: 28px;
}
.overview-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 18px;
}
.overview-card {
  padding: 20px;
}
.overview-card h3 {
  font-size: 1rem;
  margin: 0 0 12px;
  color: #e2e8f0;
}
.story-overview .story-mini {
  margin-bottom: 14px;
  padding-bottom: 14px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}
.story-overview .story-mini:last-child {
  border-bottom: none;
  margin-bottom: 0;
  padding-bottom: 0;
}
.story-mini-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.story-mini-head b {
  font-size: 0.95rem;
}
.story-type-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
}
.story-type-badge.type-main {
  background: rgba(123, 92, 255, 0.2);
  color: #c8b6ff;
}
.story-type-badge.type-side {
  background: rgba(52, 211, 153, 0.2);
  color: #6ee7b7;
}
.branch-summary {
  margin-top: 6px;
  font-size: 12px;
  color: #94a3b8;
}
.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.card-head h3 {
  margin: 0;
}
.kv {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 8px;
  font-size: 0.88rem;
}
.kv > span {
  color: #94a3b8;
  min-width: 60px;
  flex-shrink: 0;
}
.kv b {
  color: #e2e8f0;
  font-weight: 500;
}
.kv-input {
  flex: 1;
  padding: 5px 10px;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(255, 255, 255, 0.04);
  color: #e2e8f0;
  font-size: 0.85rem;
  font-family: inherit;
}
.kv-input:focus {
  outline: none;
  border-color: rgba(123, 92, 255, 0.6);
}
.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.topic-tag {
  padding: 2px 8px;
  border-radius: 8px;
  background: rgba(123, 92, 255, 0.15);
  color: #c4b5fd;
  font-size: 0.75rem;
}
.edit-actions {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}
.favor-bar {
  position: relative;
  height: 22px;
  border-radius: 11px;
  background: rgba(255, 255, 255, 0.06);
  overflow: hidden;
  margin: 8px 0;
}
.favor-fill {
  height: 100%;
  background: linear-gradient(90deg, #f472b6, #c084fc);
  transition: width 0.4s ease;
}
.favor-text {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.78rem;
  font-weight: 600;
  color: #fff;
}
.reason-text {
  margin: 4px 0 0;
  font-size: 0.82rem;
  color: #94a3b8;
  line-height: 1.5;
}

/* Tab 管理 */
.manage-section {
  padding: 24px;
}
.tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 20px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  padding-bottom: 12px;
}
.tab-btn {
  padding: 8px 16px;
  border-radius: 10px;
  border: 1px solid transparent;
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
  font-size: 0.9rem;
  transition: all 0.2s ease;
}
.tab-btn:hover {
  background: rgba(255, 255, 255, 0.04);
}
.tab-btn.active {
  background: rgba(123, 92, 255, 0.15);
  border-color: rgba(123, 92, 255, 0.4);
  color: #fff;
}
.tab-count {
  margin-left: 6px;
  padding: 1px 7px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.1);
  font-size: 0.72rem;
}
.add-row {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
}
.add-row input {
  flex: 1;
  padding: 9px 12px;
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(255, 255, 255, 0.04);
  color: #e2e8f0;
  font-size: 0.88rem;
  font-family: inherit;
}
.add-row input:focus {
  outline: none;
  border-color: rgba(123, 92, 255, 0.6);
}
.manage-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.manage-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
}
.row-text {
  flex: 1;
  font-size: 0.88rem;
  color: #cbd5e1;
  word-break: break-all;
}
.summary-text {
  font-size: 0.84rem;
  color: #94a3b8;
}
.event-row {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.event-time {
  font-size: 0.72rem;
  color: #64748b;
}
.edit-input {
  flex: 1;
  padding: 6px 10px;
  border-radius: 8px;
  border: 1px solid rgba(123, 92, 255, 0.4);
  background: rgba(255, 255, 255, 0.04);
  color: #e2e8f0;
  font-size: 0.85rem;
  font-family: inherit;
}
.row-actions {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}
.empty-hint {
  text-align: center;
  padding: 24px;
  color: #64748b;
  font-size: 0.88rem;
}

/* 通用按钮（与 AboutView 一致） */
.btn {
  padding: 8px 16px;
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(255, 255, 255, 0.04);
  color: #cbd5e1;
  cursor: pointer;
  font-size: 0.86rem;
  transition: all 0.2s ease;
}
.btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.08);
}
.btn.primary {
  border: none;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: #fff;
}
.btn.sm {
  padding: 5px 12px;
  font-size: 0.8rem;
}
.btn.danger {
  border-color: rgba(248, 113, 113, 0.4);
  color: #fca5a5;
}
.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

@media (max-width: 600px) {
  .memory-page {
    padding: 20px 14px;
  }
  .search-row {
    flex-wrap: wrap;
  }
  .search-select {
    flex: 1;
  }
}
</style>
