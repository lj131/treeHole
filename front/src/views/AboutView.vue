<template>
  <div class="settings-page">
    <div class="bg-orbs">
      <div class="orb orb-1"></div>
      <div class="orb orb-2"></div>
    </div>

    <div class="settings-container">
      <header class="page-header">
        <router-link to="/chat" class="back-link">← 返回聊天</router-link>
        <h1>世界与设置</h1>
        <p>世界观切换、角色头像、NPC 关系与系统工具（记忆与画像请前往「记忆中心」）</p>
      </header>

      <div class="settings-grid">
        <!-- 世界观 -->
        <section class="glass-card">
          <h2><span>🌍</span> 世界观设置</h2>
          <div v-if="currentWorld" class="current-world">
            <strong>{{ currentWorld.name }}</strong>
            <p>{{ currentWorld.description }}</p>
            <p v-if="currentWorld.background" class="world-bg">{{ currentWorld.background }}</p>
            <div v-if="currentWorld.world_event" class="world-event">
              当前事件：{{ currentWorld.world_event.title }}
              <span v-if="currentWorld.world_event.impact">
                (影响 {{ currentWorld.world_event.impact > 0 ? '+' : '' }}{{ currentWorld.world_event.impact }})
              </span>
            </div>
          </div>
          <div class="world-list">
            <button
              v-for="w in worlds"
              :key="w.id"
              class="world-btn"
              :class="{ active: currentWorld?.id === w.id }"
              :disabled="loadingWorld"
              @click="handleSwitchWorld(w.id)"
            >
              {{ w.name }}
            </button>
          </div>
        </section>

        <!-- 角色头像 -->
        <section class="glass-card">
          <h2><span>🖼️</span> 角色头像</h2>
          <div v-if="currentAvatar" class="avatar-preview">
            <img :src="currentAvatar" alt="当前头像" />
          </div>
          <div v-else class="avatar-placeholder">
            <span class="placeholder-icon">{{ currentCharacterName?.charAt(0) || '?' }}</span>
            <p>尚未设置头像</p>
          </div>
          <div class="avatar-actions">
            <label class="btn primary upload-label">
              {{ uploading ? '上传中...' : '选择图片上传' }}
              <input
                type="file"
                accept="image/png,image/jpeg,image/gif,image/webp"
                :disabled="uploading"
                hidden
                @change="handleAvatarUpload"
              />
            </label>
          </div>
          <p v-if="uploadMessage" class="upload-msg">{{ uploadMessage }}</p>
        </section>

        <!-- NPC 社交关系网 -->
        <section class="glass-card wide">
          <div class="section-head">
            <h2><span>🕸️</span> 角色社交关系网</h2>
            <div class="card-actions">
              <button class="btn sm" :disabled="loadingInteractions" @click="loadInteractions">
                {{ loadingInteractions ? '加载中...' : '刷新' }}
              </button>
              <button class="btn sm primary" :disabled="simulatingInteraction" @click="handleSimulateInteraction">
                {{ simulatingInteraction ? '模拟中...' : '触发互动模拟' }}
              </button>
            </div>
          </div>
          <p v-if="interactions.last_interaction_date" class="meta-line">
            上次自动模拟：{{ interactions.last_interaction_date }}（世界 tick 每日最多一次）
          </p>

          <div v-if="relationshipPairs.length" class="rel-grid">
            <div v-for="(pair, i) in relationshipPairs" :key="i" class="rel-card">
              <div class="rel-names">
                {{ pair.fromName }}
                <span class="rel-arrow">→</span>
                {{ pair.toName }}
              </div>
              <div class="rel-stats">
                <div class="rel-stat">
                  <span>好感</span>
                  <div class="mini-bar"><div class="mini-fill fav" :style="{ width: pair.rel.favorability + '%' }"></div></div>
                  <em>{{ pair.rel.favorability ?? 50 }}</em>
                </div>
                <div class="rel-stat">
                  <span>信任</span>
                  <div class="mini-bar"><div class="mini-fill trust" :style="{ width: pair.rel.trust + '%' }"></div></div>
                  <em>{{ pair.rel.trust ?? 50 }}</em>
                </div>
                <div class="rel-stat">
                  <span>亲密</span>
                  <div class="mini-bar"><div class="mini-fill intimacy" :style="{ width: pair.rel.intimacy + '%' }"></div></div>
                  <em>{{ pair.rel.intimacy ?? 30 }}</em>
                </div>
              </div>
            </div>
          </div>
          <p v-else class="empty-hint">暂无角色间关系数据，可点击「触发互动模拟」生成</p>

          <div v-if="interactions.recent_interactions?.length" class="interaction-block">
            <h3>近期互动</h3>
            <div v-for="(item, i) in interactions.recent_interactions" :key="i" class="interaction-item">
              <div class="interaction-head">
                <span class="event-time">{{ item.time }}</span>
                <span>{{ item.summary }}</span>
              </div>
              <div v-if="item.dialogues?.length" class="dialogue-list">
                <div v-for="(d, j) in item.dialogues" :key="j" class="dialogue-line">
                  <strong>{{ resolveCharName(d.speaker) }}：</strong>{{ d.content }}
                </div>
              </div>
              <p v-if="item.world_impact" class="impact-line">影响：{{ item.world_impact }}</p>
            </div>
          </div>

          <div v-if="interactions.gossip?.length" class="gossip-block">
            <h3>八卦传播</h3>
            <div v-for="(g, i) in interactions.gossip" :key="i" class="gossip-item">
              <span class="event-time">{{ g.time }}</span>
              <span>{{ resolveCharName(g.source) }} → {{ g.target || '大家' }}：{{ g.content }}</span>
            </div>
          </div>
        </section>

        <!-- 用户画像 / 剧情 / 记忆 / 事件 / 聊天摘要 已迁移到「记忆中心」(/memory) -->

        <!-- 管理面板入口（仅管理员可见） -->
        <section v-if="auth.isAdmin" class="glass-card">
          <h2><span>👥</span> 用户管理</h2>
          <p style="margin-bottom:16px;color:#8888aa;font-size:14px;">用户审批、配额管理、账号注销</p>
          <router-link to="/admin" class="btn primary" style="display:inline-block;text-decoration:none;">进入管理面板 →</router-link>
        </section>

        <!-- 系统工具 -->
        <section class="glass-card">
          <h2><span>🔧</span> 系统工具</h2>
          <div class="tool-buttons">
            <button class="btn" @click="fetchProactive">获取主动问候</button>
            <button class="btn" @click="fetchCaring">获取关心消息</button>
            <button class="btn danger" @click="handleClearMemory">清空对话历史</button>
          </div>
          <div v-if="toolMessage" class="tool-result">{{ toolMessage }}</div>
        </section>

        <!-- 缺失接口说明 -->
        <section class="glass-card wide api-gap">
          <h2><span>⚠️</span> 后端待补充接口</h2>
          <p class="gap-desc">以下接口在文档中提及但后端 <code>api.py</code> 尚未实现，前端已做兼容处理：</p>
          <ul class="gap-list">
            <li>
              <code>GET /messages</code> — 完整聊天历史（当前仅 <code>GET /history</code> 返回最近 10 条）
            </li>
            <li>
              <code>GET /character/name</code> — 获取角色名（已改用 <code>GET /character/current</code>）
            </li>
            <li>
              <code>POST /character/name</code> — 设置角色名
            </li>
            <li>角色头像 URL 字段 — 当前使用渐变色占位，建议后端角色 JSON 增加 <code>avatar</code> 字段</li>
            <li>WebSocket 流式回复 — 当前聊天为同步阻塞，建议后续支持 SSE/WebSocket 流式输出</li>
          </ul>
        </section>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { getCharacterAvatarUrl } from '@/utils/character'
import {
  getWorlds,
  getCurrentWorld,
  switchWorld,
  getWorldInteractions,
  simulateWorldInteraction,
  clearMemory,
  getProactiveMessage,
  getCaringMessage,
  getCurrentCharacter,
} from '@/api'
import { uploadCharacterAvatar } from '@/api/character'
import { useAuthStore } from '@/stores/authStore'
import type { World, WorldInteractionsSnapshot, NpcRelationship } from '@/types/api'

const worlds = ref<World[]>([])
const currentWorld = ref<World | null>(null)
const interactions = ref<WorldInteractionsSnapshot>({})
const auth = useAuthStore()
const currentAvatar = ref('')
const currentCharacterName = ref('')
const uploading = ref(false)
const uploadMessage = ref('')
const toolMessage = ref('')
const loadingWorld = ref(false)
const loadingInteractions = ref(false)
const simulatingInteraction = ref(false)

const relationshipPairs = computed(() => {
  const rels = interactions.value.relationships ?? {}
  const names = interactions.value.characters ?? {}
  const pairs: Array<{
    fromName: string
    toName: string
    rel: NpcRelationship
  }> = []

  for (const [fromId, targets] of Object.entries(rels)) {
    for (const [toId, rel] of Object.entries(targets)) {
      pairs.push({
        fromName: names[fromId] ?? fromId,
        toName: names[toId] ?? toId,
        rel,
      })
    }
  }
  return pairs
})

const resolveCharName = (idOrName?: string) => {
  if (!idOrName) return '未知'
  const names = interactions.value.characters ?? {}
  return names[idOrName] ?? idOrName
}

const loadInteractions = async () => {
  loadingInteractions.value = true
  try {
    interactions.value = await getWorldInteractions()
  } finally {
    loadingInteractions.value = false
  }
}

const handleSimulateInteraction = async () => {
  simulatingInteraction.value = true
  try {
    const res = await simulateWorldInteraction()
    if (res.action === 'simulated') {
      toolMessage.value = '多角色互动模拟已完成'
    } else {
      toolMessage.value = `模拟未执行：${res.reason ?? res.action}`
    }
    await loadInteractions()
  } finally {
    simulatingInteraction.value = false
  }
}

const loadAll = async () => {
  const [worldsRes, worldRes] = await Promise.all([
    getWorlds(),
    getCurrentWorld(),
  ])
  worlds.value = worldsRes.worlds ?? []
  currentWorld.value = worldRes.world
  await loadInteractions()
  await loadCharacterAvatar()
}

const loadCharacterAvatar = async () => {
  try {
    const { character } = await getCurrentCharacter()
    currentAvatar.value = getCharacterAvatarUrl(character.avatar)
    currentCharacterName.value = character.name
  } catch { /* ignore */ }
}

const handleAvatarUpload = async (e: Event) => {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return

  // 前端校验
  if (file.size > 5 * 1024 * 1024) {
    uploadMessage.value = '文件过大，请选择 5MB 以内的图片'
    return
  }

  uploading.value = true
  uploadMessage.value = ''
  try {
    const res = await uploadCharacterAvatar(file)
    currentAvatar.value = getCharacterAvatarUrl(res.avatar)
    uploadMessage.value = '头像上传成功！返回聊天页查看效果'
  } catch (err: any) {
    uploadMessage.value = `上传失败: ${err.message || err}`
  } finally {
    uploading.value = false
    input.value = ''  // 清空 input，允许重复上传同一文件
  }
}

const handleSwitchWorld = async (worldId: string) => {
  loadingWorld.value = true
  try {
    await switchWorld(worldId)
    const { world } = await getCurrentWorld()
    currentWorld.value = world
    toolMessage.value = `已切换到「${world.name}」世界观`
    await loadInteractions()
  } finally {
    loadingWorld.value = false
  }
}

const handleClearMemory = async () => {
  if (!confirm('确定清空所有对话历史？此操作不可撤销。')) return
  try {
    await clearMemory()
    toolMessage.value = '对话历史已清空，请返回聊天页刷新'
  } catch {
    toolMessage.value = '清空失败，请稍后重试'
  }
}

const fetchProactive = async () => {
  const { message } = await getProactiveMessage()
  toolMessage.value = message || '暂无主动问候消息'
}

const fetchCaring = async () => {
  const { message } = await getCaringMessage()
  toolMessage.value = message || '暂无关心消息'
}

onMounted(() => { loadAll() })
</script>

<style scoped>
.settings-page {
  min-height: 100vh;
  background: #0a0a14;
  color: #e8e8f0;
  position: relative;
  overflow-x: hidden;
}

.bg-orbs {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);
  opacity: 0.25;
}

.orb-1 {
  width: 400px;
  height: 400px;
  background: #7b5cff;
  top: -100px;
  right: -100px;
}

.orb-2 {
  width: 300px;
  height: 300px;
  background: #4facfe;
  bottom: -80px;
  left: 10%;
}

.settings-container {
  position: relative;
  z-index: 1;
  max-width: 1200px;
  margin: 0 auto;
  padding: 40px 24px 80px;
}

.page-header {
  margin-bottom: 40px;
}

.back-link {
  color: #8888aa;
  text-decoration: none;
  font-size: 14px;
  transition: color 0.2s;
}

.back-link:hover {
  color: #c8b6ff;
}

.page-header h1 {
  font-size: 32px;
  font-weight: 700;
  margin: 12px 0 8px;
  background: linear-gradient(135deg, #fff, #c8b6ff);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.page-header p {
  color: #666680;
  font-size: 15px;
}

.settings-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 20px;
}

.glass-card {
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 20px;
  backdrop-filter: blur(24px);
  padding: 24px;
}

.glass-card.wide {
  grid-column: 1 / -1;
}

.glass-card h2 {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 20px;
  display: flex;
  align-items: center;
  gap: 8px;
  color: #aaaacc;
}

.glass-card h2 span {
  font-size: 18px;
}

.current-world {
  margin-bottom: 16px;
  padding: 16px;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 14px;
}

.current-world strong {
  font-size: 18px;
  color: #c8b6ff;
}

.current-world p {
  margin-top: 8px;
  font-size: 13px;
  color: #8888aa;
  line-height: 1.6;
}

.world-bg {
  font-style: italic;
}

.world-event {
  margin-top: 10px;
  padding: 8px 12px;
  background: rgba(123, 92, 255, 0.1);
  border-radius: 10px;
  font-size: 13px;
  color: #c8b6ff;
}

.world-list {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.world-btn {
  padding: 8px 20px;
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.04);
  color: #aaaacc;
  cursor: pointer;
  transition: all 0.2s;
  font-size: 14px;
}

.world-btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.08);
}

.world-btn.active {
  background: rgba(123, 92, 255, 0.2);
  border-color: rgba(123, 92, 255, 0.5);
  color: #fff;
}

.btn {
  padding: 10px 20px;
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.04);
  color: #aaaacc;
  cursor: pointer;
  font-size: 14px;
  transition: all 0.2s;
}

.btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.08);
}

.btn.primary {
  background: linear-gradient(135deg, #7b5cff, #b06cff);
  border: none;
  color: #fff;
}

.btn.danger {
  border-color: rgba(255, 107, 107, 0.3);
  color: #ff6b6b;
}

.btn.danger:hover {
  background: rgba(255, 107, 107, 0.1);
}

.btn.sm {
  padding: 6px 12px;
  font-size: 12px;
}

.btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.tool-buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.tool-result {
  margin-top: 16px;
  padding: 14px;
  background: rgba(123, 92, 255, 0.08);
  border-radius: 12px;
  font-size: 13px;
  line-height: 1.6;
  color: #c8b6ff;
}

.empty-hint {
  color: #444460;
  font-size: 13px;
  text-align: center;
  padding: 16px 0;
}

.api-gap {
  border-color: rgba(255, 193, 7, 0.15);
}

.gap-desc {
  font-size: 13px;
  color: #8888aa;
  margin-bottom: 12px;
}

.gap-list {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.gap-list li {
  padding: 12px 16px;
  background: rgba(255, 193, 7, 0.05);
  border-radius: 12px;
  font-size: 13px;
  color: #aaaacc;
  line-height: 1.5;
}

.gap-list code {
  background: rgba(255, 255, 255, 0.06);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 12px;
  color: #ffd93d;
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}

.section-head h2 {
  margin-bottom: 0;
}

.meta-line {
  font-size: 12px;
  color: #666680;
  margin-bottom: 16px;
}

.rel-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 12px;
  margin-bottom: 20px;
}

.rel-card {
  padding: 14px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
}

.rel-names {
  font-size: 14px;
  font-weight: 600;
  color: #c8b6ff;
  margin-bottom: 12px;
}

.rel-arrow {
  margin: 0 6px;
  color: #555570;
  font-weight: 400;
}

.rel-stats {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.rel-stat {
  display: grid;
  grid-template-columns: 32px 1fr 28px;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: #666680;
}

.rel-stat em {
  font-style: normal;
  color: #aaaacc;
  text-align: right;
}

.mini-bar {
  height: 4px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.06);
  overflow: hidden;
}

.mini-fill {
  height: 100%;
  border-radius: 999px;
  transition: width 0.4s ease;
}

.mini-fill.fav {
  background: linear-gradient(90deg, #ff6b9d, #c8b6ff);
}

.mini-fill.trust {
  background: linear-gradient(90deg, #4facfe, #7b5cff);
}

.mini-fill.intimacy {
  background: linear-gradient(90deg, #ffd93d, #ff6b9d);
}

.interaction-block,
.gossip-block {
  margin-top: 20px;
}

.interaction-block h3,
.gossip-block h3 {
  font-size: 13px;
  color: #8888aa;
  margin-bottom: 10px;
  font-weight: 600;
}

.interaction-item,
.gossip-item {
  padding: 12px 14px;
  margin-bottom: 8px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.03);
  font-size: 13px;
  line-height: 1.55;
  color: #aaaacc;
}

.interaction-head {
  margin-bottom: 8px;
}

.dialogue-list {
  padding-left: 8px;
  border-left: 2px solid rgba(123, 92, 255, 0.25);
}

.dialogue-line {
  margin-bottom: 6px;
}

.dialogue-line strong {
  color: #c8b6ff;
  font-weight: 600;
}

.impact-line {
  margin-top: 8px;
  font-size: 12px;
  color: #666680;
  font-style: italic;
}

@media (max-width: 768px) {
  .settings-grid {
    grid-template-columns: 1fr;
  }

  .form-grid {
    grid-template-columns: 1fr;
  }
}

/* ── 头像上传 ── */
.avatar-preview {
  width: 140px;
  height: 180px;
  border-radius: 24px;
  overflow: hidden;
  margin: 0 auto 16px;
  box-shadow: 0 8px 32px rgba(123, 92, 255, 0.3);
}
.avatar-preview img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.avatar-placeholder {
  width: 140px;
  height: 180px;
  border-radius: 24px;
  margin: 0 auto 16px;
  background: rgba(255, 255, 255, 0.04);
  border: 2px dashed rgba(255, 255, 255, 0.15);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #555570;
}
.placeholder-icon {
  font-size: 48px;
  font-weight: 800;
  color: rgba(255, 255, 255, 0.3);
}
.avatar-actions {
  text-align: center;
}
.upload-label {
  display: inline-block;
  cursor: pointer;
}
.upload-label:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.upload-msg {
  text-align: center;
  font-size: 13px;
  color: #8888aa;
  margin-top: 8px;
}

/* 用户管理 */
.user-manage-list { display: flex; flex-direction: column; gap: 8px; }
.user-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 14px; border-radius: 10px; background: rgba(255,255,255,0.03); }
.user-info { display: flex; flex-direction: column; gap: 2px; }
.uname { font-size: 0.9rem; color: #cbd5e1; font-weight: 500; }
.utime { font-size: 0.72rem; color: #64748b; }
.user-actions { display: flex; gap: 6px; }
.empty-hint { text-align: center; padding: 20px; color: #64748b; font-size: 0.88rem; }

/* 配额管理 */
.sub-section { margin-top: 20px; }
.sub-section h3 { font-size: 13px; color: #8888aa; margin-bottom: 10px; font-weight: 600; }
.quota-table-wrap { overflow-x: auto; }
.quota-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.quota-table th { padding: 10px 12px; text-align: left; color: #8888aa; font-weight: 500; font-size: 12px; border-bottom: 1px solid rgba(255,255,255,0.06); white-space: nowrap; }
.quota-table td { padding: 10px 12px; color: #cbd5e1; border-bottom: 1px solid rgba(255,255,255,0.03); white-space: nowrap; }
.quota-table tr.is-admin td { opacity: 0.6; }
.quota-table tr:hover td { background: rgba(255,255,255,0.02); }
.quota-val { font-weight: 500; }
.quota-val.quota-warn { color: #fca5a5; }
.quota-input { width: 60px; padding: 4px 8px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.15); background: rgba(0,0,0,0.3); color: #e8e8f0; font-size: 13px; text-align: center; }
.quota-input:focus { outline: none; border-color: #7b5cff; }
.badge-admin { display: inline-block; margin-left: 6px; padding: 0 5px; border-radius: 4px; background: rgba(123,92,255,0.2); color: #c8b6ff; font-size: 10px; font-weight: 600; vertical-align: middle; }
.quota-actions .btn { font-size: 12px; padding: 4px 10px; }
.card-actions { display: flex; gap: 8px; align-items: center; }
</style>
