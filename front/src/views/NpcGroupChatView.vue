<template>
  <div class="npc-page">
    <header class="npc-header glass-card">
      <div class="head-text">
        <h1><span>👥</span> NPC 群聊旁观</h1>
        <p class="subtitle">
          角色们背着用户聊了什么。所有内容由本地 LLM 在世界事件驱动下模拟生成，
          不影响用户自己的角色与主线剧情。
        </p>
      </div>
      <div class="head-actions">
        <button class="btn primary" :disabled="simulating" @click="handleSimulate">
          {{ simulating ? '模拟中…' : '触发一场群聊' }}
        </button>
      </div>
    </header>

    <p v-if="snapshot.last_interaction_date" class="meta-line">
      上次自动模拟：{{ snapshot.last_interaction_date }}（世界 tick 每日最多一次）
    </p>
    <p v-if="message" class="msg-line" :class="msgKind">{{ message }}</p>

    <!-- 角色间关系 -->
    <section class="glass-card">
      <h2 class="section-title"><span>🔗</span> 角色间关系</h2>
      <template v-if="relationList.length">
        <div class="rel-grid">
          <div v-for="r in relationList" :key="r.key" class="rel-card">
            <div class="rel-names">{{ r.from }} <span class="arrow">→</span> {{ r.to }}</div>
            <div class="rel-stats">
              <div class="rel-stat">
                <span>好感</span>
                <div class="bar"><i class="fill fav" :style="{ width: barWidth(r.rel.favorability) }"></i></div>
                <em>{{ r.rel.favorability ?? 50 }}</em>
              </div>
              <div class="rel-stat">
                <span>信任</span>
                <div class="bar"><i class="fill trust" :style="{ width: barWidth(r.rel.trust) }"></i></div>
                <em>{{ r.rel.trust ?? 50 }}</em>
              </div>
              <div class="rel-stat">
                <span>亲密</span>
                <div class="bar"><i class="fill intimacy" :style="{ width: barWidth(r.rel.intimacy) }"></i></div>
                <em>{{ r.rel.intimacy ?? 30 }}</em>
              </div>
            </div>
          </div>
        </div>
      </template>
      <p v-else class="empty-hint">暂无关系数据</p>
    </section>

    <!-- 群聊记录：一场互动 = 一个群聊会话 -->
    <section class="glass-card">
      <h2 class="section-title"><span>💬</span> 群聊记录</h2>

      <div v-if="!sessions.length" class="empty-hint">
        还没有群聊记录。点击右上角「触发一场群聊」，
        或等世界 tick 在世界事件驱动下自动模拟（每日最多一次）。
      </div>

      <article v-for="(s, i) in sessions" :key="i" class="session">
        <header class="session-head">
          <span class="session-time">{{ s.time || '—' }}</span>
          <p class="session-summary">{{ s.summary || '（无摘要）' }}</p>
        </header>

        <div v-if="s.dialogues?.length" class="bubble-list">
          <div v-for="(d, j) in s.dialogues" :key="j" class="bubble-row">
            <span
              class="avatar"
              :style="{ background: avatarColor(nameOf(d.speaker)) }"
              :aria-hidden="true"
            >{{ avatarText(nameOf(d.speaker)) }}</span>
            <div class="bubble">
              <span class="speaker">{{ nameOf(d.speaker) }}</span>
              <p class="content">{{ d.content }}</p>
            </div>
          </div>
        </div>
        <p v-else class="empty-hint small">这场没有对话内容</p>

        <p v-if="s.world_impact" class="impact">对世界的影响：{{ s.world_impact }}</p>
      </article>
    </section>

    <!-- 八卦传播 -->
    <section v-if="snapshot.gossip?.length" class="glass-card">
      <h2 class="section-title"><span>🗣️</span> 八卦传播</h2>
      <div v-for="(g, i) in snapshot.gossip" :key="i" class="gossip-item">
        <span class="time">{{ g.time }}</span>
        <span class="flow"><b>{{ nameOf(g.source) }}</b> → {{ nameOf(g.target || '') || '大家' }}</span>
        <span class="content">{{ g.content }}</span>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { getWorldInteractions, simulateWorldInteraction } from '@/api'
import { errorMessage } from '@/utils/error'
import type {
  NpcInteractionRecord,
  NpcRelationship,
  WorldInteractionsSnapshot,
} from '@/types/api'

const snapshot = ref<WorldInteractionsSnapshot>({})
const loading = ref(false)
const simulating = ref(false)
const message = ref('')
const msgKind = ref<'ok' | 'err'>('ok')

/** 最近的一场放最前面（后端是 append 顺序） */
const sessions = computed<NpcInteractionRecord[]>(() =>
  [...(snapshot.value.recent_interactions ?? [])].reverse(),
)

const relationList = computed(() => {
  const out: { key: string; from: string; to: string; rel: NpcRelationship }[] = []
  const rels = snapshot.value.relationships ?? {}
  const names = snapshot.value.characters ?? {}
  for (const [fromId, targets] of Object.entries(rels)) {
    for (const [toId, rel] of Object.entries(targets ?? {})) {
      out.push({ key: `${fromId}->${toId}`, from: names[fromId] ?? fromId, to: names[toId] ?? toId, rel })
    }
  }
  return out
})

const nameOf = (id?: string) => (id ? (snapshot.value.characters?.[id] ?? id) : '')

/** 同一个名字永远同一个颜色（用字符码做朴素 hash） */
const avatarColor = (name: string) => {
  let h = 0
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) % 360
  return `hsl(${h} 62% 42%)`
}
const avatarText = (name: string) => name.slice(0, 1) || '?'
const barWidth = (v?: number) => `${Math.max(0, Math.min(100, v ?? 0))}%`

async function load() {
  loading.value = true
  try {
    snapshot.value = await getWorldInteractions()
  } catch (e) {
    message.value = errorMessage(e, '加载群聊记录失败')
    msgKind.value = 'err'
  } finally {
    loading.value = false
  }
}

async function handleSimulate() {
  simulating.value = true
  message.value = ''
  try {
    const res = await simulateWorldInteraction()
    if (res.action === 'simulated') {
      message.value = '已模拟一场新的群聊'
      msgKind.value = 'ok'
    } else {
      message.value = res.reason || `未模拟（${res.action}）`
      msgKind.value = res.action === 'skipped' ? 'ok' : 'err'
    }
    await load()
  } catch (e) {
    message.value = errorMessage(e, '模拟失败')
    msgKind.value = 'err'
  } finally {
    simulating.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.npc-page {
  min-height: calc(100vh - 64px);
  padding: 32px 24px;
  max-width: 900px;
  margin: 0 auto;
  color: #e2e8f0;
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.npc-header {
  display: flex;
  gap: 16px;
  align-items: flex-start;
  justify-content: space-between;
  padding: 20px;
}
.npc-header h1 {
  font-size: 1.4rem;
  margin: 0 0 8px;
}
.subtitle {
  margin: 0;
  font-size: 0.86rem;
  color: #94a3b8;
  line-height: 1.6;
  max-width: 52ch;
}
.head-actions {
  flex: none;
}
.meta-line {
  margin: -8px 0 0;
  font-size: 0.78rem;
  color: #64748b;
}
.msg-line {
  margin: 0;
  font-size: 0.84rem;
  padding: 8px 12px;
  border-radius: 10px;
}
.msg-line.ok {
  color: #86efac;
  background: rgba(34, 197, 94, 0.1);
}
.msg-line.err {
  color: #fca5a5;
  background: rgba(239, 68, 68, 0.12);
}
.section-title {
  font-size: 1.02rem;
  margin: 0 0 14px;
}
.empty-hint {
  text-align: center;
  padding: 22px;
  color: #64748b;
  font-size: 0.86rem;
  line-height: 1.6;
}
.empty-hint.small {
  padding: 8px;
}

/* 关系 */
.rel-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 10px;
}
.rel-card {
  padding: 12px 14px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
}
.rel-names {
  font-size: 0.88rem;
  margin-bottom: 8px;
}
.rel-names .arrow {
  color: #94a3b8;
}
.rel-stat {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.76rem;
  margin-bottom: 4px;
}
.rel-stat span {
  width: 28px;
  color: #94a3b8;
}
.rel-stat em {
  font-style: normal;
  width: 30px;
  text-align: right;
  color: #cbd5e1;
}
.bar {
  flex: 1;
  height: 6px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.08);
  overflow: hidden;
}
.fill {
  display: block;
  height: 100%;
  border-radius: 999px;
}
.fill.fav { background: #f472b6; }
.fill.trust { background: #60a5fa; }
.fill.intimacy { background: #a78bfa; }

/* 群聊会话 */
.session {
  padding: 16px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
  margin-bottom: 12px;
}
.session-head {
  margin-bottom: 12px;
}
.session-time {
  font-size: 0.74rem;
  color: #64748b;
}
.session-summary {
  margin: 6px 0 0;
  font-size: 0.92rem;
  color: #e2e8f0;
}
.bubble-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.bubble-row {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}
.avatar {
  flex: none;
  width: 30px;
  height: 30px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  font-weight: 700;
  color: #fff;
  font-size: 0.86rem;
}
.bubble {
  flex: 1;
  padding: 8px 12px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.06);
}
.speaker {
  display: block;
  font-size: 0.74rem;
  color: #c8b6ff;
  margin-bottom: 2px;
}
.content {
  margin: 0;
  font-size: 0.88rem;
  line-height: 1.6;
  color: #cbd5e1;
  white-space: pre-wrap;
}
.impact {
  margin: 12px 0 0;
  font-size: 0.8rem;
  color: #94a3b8;
  padding-top: 10px;
  border-top: 1px dashed rgba(255, 255, 255, 0.1);
}

/* 八卦 */
.gossip-item {
  display: grid;
  grid-template-columns: auto auto 1fr;
  gap: 10px;
  align-items: baseline;
  font-size: 0.84rem;
  padding: 8px 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}
.gossip-item .time { color: #64748b; font-size: 0.74rem; }
.gossip-item .flow b { color: #c8b6ff; }
.gossip-item .content { color: #cbd5e1; }
</style>
