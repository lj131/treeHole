<template>
  <div class="admin-page">
    <div class="bg-orbs">
      <div class="orb orb-1"></div>
      <div class="orb orb-2"></div>
    </div>

    <div class="admin-container">
      <header class="page-header">
        <router-link to="/chat" class="back-link">← 返回聊天</router-link>
        <h1>管理面板</h1>
        <p>用户审批、配额管理、账号注销</p>
      </header>

      <div class="admin-grid">
        <!-- 待审批 -->
        <section v-if="pendingUsers.length > 0" class="glass-card wide">
          <div class="section-head">
            <h2><span>⏳</span> 待审批用户 ({{ pendingUsers.length }})</h2>
            <button class="btn sm" :disabled="loading" @click="loadAll">刷新</button>
          </div>
          <div class="user-manage-list">
            <div v-for="u in pendingUsers" :key="u.id" class="user-row">
              <div class="user-info">
                <span class="uname">{{ u.username }}</span>
                <span class="utime">{{ formatDate(u.created_at) }}</span>
              </div>
              <div class="user-actions">
                <button class="btn sm primary" :disabled="actingId === u.id" @click="handleApprove(u.id)">通过</button>
                <button class="btn sm danger" :disabled="actingId === u.id" @click="handleReject(u.id)">拒绝</button>
              </div>
            </div>
          </div>
        </section>

        <!-- 全部用户 -->
        <section class="glass-card wide">
          <div class="section-head">
            <h2><span>👥</span> 全部用户 ({{ allUsers.length }})</h2>
            <button class="btn sm" :disabled="loading" @click="loadAll">{{ loading ? '加载中...' : '刷新' }}</button>
          </div>

          <div v-if="allUsers.length === 0 && !loading" class="empty-hint">暂无用户</div>

          <div v-else class="quota-table-wrap">
            <table class="quota-table">
              <thead>
                <tr>
                  <th>用户名</th>
                  <th>角色</th>
                  <th>状态</th>
                  <th>每日 Chat</th>
                  <th>今日已用</th>
                  <th>角色上限</th>
                  <th>已有角色</th>
                  <th>配额</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="u in allUsers" :key="u.id" :class="{ 'row-dim': u.status === 'deactivated', 'row-admin': u.role === 'admin' }">
                  <!-- 用户名 -->
                  <td>
                    <span class="uname">{{ u.username }}</span>
                    <span v-if="u.role === 'admin'" class="badge badge-admin">admin</span>
                  </td>
                  <!-- 角色 -->
                  <td>{{ u.role === 'admin' ? '管理员' : '用户' }}</td>
                  <!-- 状态 -->
                  <td>
                    <span class="status-tag" :class="'status-' + u.status">
                      {{ statusLabel(u.status) }}
                    </span>
                  </td>
                  <!-- 每日 Chat -->
                  <td>
                    <template v-if="editingId === u.id">
                      <input v-model="editDailyLimit" type="number" min="0" class="quota-input" @keyup.enter="saveQuota(u.id)" />
                    </template>
                    <template v-else>
                      <span class="quota-val">{{ u.daily_chat_limit === 0 ? '不限' : u.daily_chat_limit }}</span>
                    </template>
                  </td>
                  <!-- 今日已用 -->
                  <td>
                    <span class="quota-val" :class="{ 'quota-warn': (u.today_chat_count ?? 0) >= (u.daily_chat_limit || 999) }">
                      {{ u.today_chat_count ?? 0 }}
                    </span>
                  </td>
                  <!-- 角色上限 -->
                  <td>
                    <template v-if="editingId === u.id">
                      <input v-model="editCharLimit" type="number" min="0" class="quota-input" @keyup.enter="saveQuota(u.id)" />
                    </template>
                    <template v-else>
                      <span class="quota-val">{{ u.character_limit }}</span>
                    </template>
                  </td>
                  <!-- 已有角色 -->
                  <td>{{ u.character_count ?? 0 }}</td>
                  <!-- 配额编辑 -->
                  <td>
                    <template v-if="editingId === u.id">
                      <button class="btn xs primary" @click="saveQuota(u.id)">保存</button>
                      <button class="btn xs" @click="cancelEdit">取消</button>
                    </template>
                    <template v-else>
                      <button class="btn xs" @click="startEdit(u)">改配额</button>
                    </template>
                  </td>
                  <!-- 操作：注销 / 激活 -->
                  <td>
                    <template v-if="u.role === 'admin'">
                      <span class="hint-text">—</span>
                    </template>
                    <template v-else-if="u.status === 'deactivated'">
                      <button class="btn xs success" :disabled="actingId === u.id" @click="handleReactivate(u.id)">激活</button>
                    </template>
                    <template v-else>
                      <button class="btn xs danger" :disabled="actingId === u.id" @click="handleDeactivate(u.id)">注销</button>
                    </template>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <p v-if="loadError" class="error-msg">{{ loadError }}</p>
        </section>

        <!-- 系统配置 -->
        <section class="glass-card wide">
          <div class="section-head">
            <h2><span>⚙️</span> 系统配置</h2>
            <div class="cfg-actions">
              <button
                class="btn xs"
                :disabled="cfgSaving || !cfgDirty"
                @click="saveConfig"
              >
                {{ cfgSaving ? '保存中…' : '保存' }}
              </button>
              <button class="btn xs ghost" :disabled="cfgSaving || !cfgDirty" @click="discardConfig">
                放弃修改
              </button>
            </div>
          </div>

          <p class="cfg-note">
            改这里不用动 <code>.env</code> 也不用重启（标「需重启」的除外）。
            优先级：此处配置 &gt; 环境变量 &gt; 代码默认值。
            <br />
            <strong>密钥类配置不在这里</strong>（JWT 密钥、默认管理员密码、各家 API key）——
            在界面上改密钥有安全风险，也会让现有登录全部失效，请直接编辑 <code>.env</code>。
          </p>

          <p v-if="cfgLoading" class="cfg-note">加载中…</p>
          <p v-else-if="cfgError" class="error-msg">{{ cfgError }}</p>

          <div v-else class="cfg-groups">
            <div v-for="group in cfgGroups" :key="group" class="cfg-group">
              <h3 class="cfg-group-title">{{ group }}</h3>
              <div
                v-for="f in fieldsOfGroup(group)"
                :key="f.key"
                class="cfg-row"
              >
                <div class="cfg-label">
                  <span class="cfg-name">{{ f.label }}</span>
                  <span v-if="f.restart_required" class="cfg-badge">需重启</span>
                  <span v-if="isDirty(f.key)" class="cfg-badge cfg-badge-dirty">未保存</span>
                  <p v-if="f.hint" class="cfg-hint">{{ f.hint }}</p>
                </div>

                <div class="cfg-control">
                  <select
                    v-if="f.choices.length"
                    v-model="cfgDraft[f.key]"
                    class="cfg-input"
                  >
                    <option v-for="c in f.choices" :key="c" :value="c">{{ c }}</option>
                  </select>
                  <input
                    v-else-if="f.kind === 'string'"
                    v-model="cfgDraft[f.key]"
                    class="cfg-input"
                  />
                  <input
                    v-else
                    v-model.number="cfgDraft[f.key]"
                    type="number"
                    class="cfg-input"
                    :min="f.minimum ?? undefined"
                    :max="f.maximum ?? undefined"
                    :step="f.step ?? undefined"
                  />
                  <span class="cfg-default">默认 {{ f.default }}</span>
                  <button
                    v-if="isDirty(f.key)"
                    class="cfg-revert"
                    :title="`恢复默认（${f.default}）`"
                    @click="revertField(f)"
                  >
                    恢复默认
                  </button>
                </div>
              </div>
            </div>
          </div>

          <p v-if="cfgMsg" class="msg" :class="cfgMsgOk ? 'msg-ok' : 'msg-err'">{{ cfgMsg }}</p>
        </section>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { errorMessage } from '@/utils/error'
import { listUsers, updateQuota } from '@/api/auth'
import { getSystemConfig, updateSystemConfig } from '@/api/admin'
import { request } from '@/api/request'
import type { SystemConfigField, User } from '@/types/api'

const allUsers = ref<User[]>([])
const loading = ref(false)
const loadError = ref('')
const actingId = ref<number | null>(null)
const editingId = ref<number | null>(null)
const editDailyLimit = ref(100)
const editCharLimit = ref(10)

const pendingUsers = ref<User[]>([])

const statusLabel = (s: string) => {
  const map: Record<string, string> = {
    pending: '待审批',
    approved: '已认证',
    rejected: '已拒绝',
    deactivated: '已注销',
  }
  return map[s] ?? s
}

const loadAll = async () => {
  loading.value = true
  loadError.value = ''
  try {
    const res = await listUsers()
    const users = res.users || []
    pendingUsers.value = users.filter(u => u.status === 'pending')
    allUsers.value = users
  } catch (e) {
    loadError.value = errorMessage(e, '加载失败')
  } finally {
    loading.value = false
  }
}

// ---- 审批 ----
const callAdminApi = async (path: string, uid: number) => {
  actingId.value = uid
  try {
    await request(path, { method: 'POST' })
    await loadAll()
  } finally {
    actingId.value = null
  }
}

const handleApprove = (uid: number) => callAdminApi(`/auth/admin/approve/${uid}`, uid)
const handleReject = (uid: number) => callAdminApi(`/auth/admin/reject/${uid}`, uid)
const handleDeactivate = (uid: number) => {
  if (!confirm('确定要注销该用户吗？注销后用户无法登录，但数据保留。')) return
  callAdminApi(`/auth/admin/deactivate/${uid}`, uid)
}
const handleReactivate = (uid: number) => callAdminApi(`/auth/admin/reactivate/${uid}`, uid)

// ---- 配额 ----
const startEdit = (u: User) => {
  editingId.value = u.id
  editDailyLimit.value = u.daily_chat_limit
  editCharLimit.value = u.character_limit
}
const cancelEdit = () => { editingId.value = null }

const saveQuota = async (uid: number) => {
  try {
    await updateQuota(uid, {
      daily_chat_limit: editDailyLimit.value,
      character_limit: editCharLimit.value,
    })
    editingId.value = null
    await loadAll()
  } catch (e) {
    loadError.value = errorMessage(e, '保存失败')
  }
}

const formatDate = (s?: string) => {
  if (!s) return ''
  try { return new Date(s).toLocaleDateString('zh-CN') } catch { return s }
}

// ============================================================
// 系统配置
//
// **按后端 schema 渲染**，不写死表单 —— 后端加一个字段，这里自动出现。
// ============================================================

const cfgLoading = ref(false)
const cfgSaving = ref(false)
const cfgError = ref('')
const cfgMsg = ref('')
const cfgMsgOk = ref(false)

const cfgGroups = ref<string[]>([])
const cfgFields = ref<SystemConfigField[]>([])
/** 编辑中的值（key → 值）。保存时只提交与后端不同的项。 */
const cfgDraft = ref<Record<string, string | number>>({})

const fieldsOfGroup = (group: string) => cfgFields.value.filter((f) => f.group === group)

/** 该字段的编辑值是否与后端当前值不同 */
const isDirty = (key: string) => {
  const field = cfgFields.value.find((f) => f.key === key)
  return field ? cfgDraft.value[key] !== field.value : false
}

const cfgDirty = computed(() => cfgFields.value.some((f) => isDirty(f.key)))

function applyConfig(res: { groups: string[]; fields: SystemConfigField[] }) {
  cfgGroups.value = res.groups || []
  cfgFields.value = res.fields || []
  const draft: Record<string, string | number> = {}
  for (const f of cfgFields.value) draft[f.key] = f.value
  cfgDraft.value = draft
}

async function loadConfig() {
  cfgLoading.value = true
  cfgError.value = ''
  try {
    applyConfig(await getSystemConfig())
  } catch (e) {
    cfgError.value = errorMessage(e, '系统配置加载失败')
  } finally {
    cfgLoading.value = false
  }
}

/** 把某项恢复成「默认值」—— 本地先改，保存时才真正提交 null */
function revertField(f: SystemConfigField) {
  cfgDraft.value[f.key] = f.default
}

function discardConfig() {
  applyConfig({ groups: cfgGroups.value, fields: cfgFields.value })
  cfgMsg.value = ''
}

async function saveConfig() {
  // 只提交真正改过的项：提交全量会把没动过的值也写成覆盖，
  // 以后改代码默认值就对这里失效了
  const values: Record<string, string | number | null> = {}
  for (const f of cfgFields.value) {
    if (!isDirty(f.key)) continue
    const next = cfgDraft.value[f.key]
    if (next === undefined) continue
    values[f.key] = next === f.default ? null : next
  }
  if (Object.keys(values).length === 0) {
    cfgMsg.value = '没有需要保存的修改'
    cfgMsgOk.value = true
    return
  }

  cfgSaving.value = true
  cfgMsg.value = ''
  try {
    applyConfig(await updateSystemConfig({ values }))
    const needsRestart = cfgFields.value.some(
      (f) => f.restart_required && values[f.key] !== undefined,
    )
    cfgMsg.value = needsRestart
      ? '已保存。标了「需重启」的项要重启后端进程才生效。'
      : '已保存并生效。'
    cfgMsgOk.value = true
  } catch (e) {
    // 后端是「全批校验、有非法值就整批不写」，所以失败时本地改动保留，让用户改完再存
    cfgMsg.value = errorMessage(e, '保存失败')
    cfgMsgOk.value = false
  } finally {
    cfgSaving.value = false
  }
}

onMounted(() => {
  loadAll()
  loadConfig()
})
</script>

<style scoped>
.admin-page {
  min-height: 100vh;
  background: #0a0a14;
  color: #e8e8f0;
  position: relative;
  overflow-x: hidden;
}

.bg-orbs { position: absolute; inset: 0; pointer-events: none; }
.orb { position: absolute; border-radius: 50%; filter: blur(80px); opacity: 0.25; }
.orb-1 { width: 400px; height: 400px; background: #7b5cff; top: -100px; right: -100px; }
.orb-2 { width: 300px; height: 300px; background: #4facfe; bottom: -80px; left: 10%; }

.admin-container {
  position: relative; z-index: 1;
  max-width: 1200px; margin: 0 auto; padding: 40px 24px 80px;
}

.page-header { margin-bottom: 32px; }
.back-link { color: #8888aa; text-decoration: none; font-size: 14px; transition: color 0.2s; }
.back-link:hover { color: #c8b6ff; }
.page-header h1 { font-size: 32px; font-weight: 700; margin: 12px 0 4px;
  background: linear-gradient(135deg, #fff, #c8b6ff);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }
.page-header p { color: #666680; font-size: 15px; }

.admin-grid { display: flex; flex-direction: column; gap: 20px; }

.glass-card {
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 20px; backdrop-filter: blur(24px); padding: 24px;
}
.glass-card.wide { grid-column: 1 / -1; }
.glass-card h2 { font-size: 16px; font-weight: 600; margin-bottom: 4px;
  display: flex; align-items: center; gap: 8px; color: #aaaacc; }
.glass-card h2 span { font-size: 18px; }

.section-head {
  display: flex; align-items: center; justify-content: space-between;
  gap: 12px; margin-bottom: 16px;
}
.section-head h2 { margin-bottom: 0; }

/* 用户行 */
.user-manage-list { display: flex; flex-direction: column; gap: 8px; }
.user-row {
  display: flex; align-items: center; justify-content: space-between;
  gap: 12px; padding: 10px 14px; border-radius: 10px;
  background: rgba(255,255,255,0.03);
}
.user-info { display: flex; flex-direction: column; gap: 2px; }
.uname { font-size: 0.9rem; color: #cbd5e1; font-weight: 500; }
.utime { font-size: 0.72rem; color: #64748b; }
.user-actions { display: flex; gap: 6px; }

/* 表格 */
.quota-table-wrap { overflow-x: auto; }
.quota-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.quota-table th {
  padding: 10px 12px; text-align: left; color: #8888aa;
  font-weight: 500; font-size: 12px; border-bottom: 1px solid rgba(255,255,255,0.06);
  white-space: nowrap;
}
.quota-table td {
  padding: 10px 12px; color: #cbd5e1;
  border-bottom: 1px solid rgba(255,255,255,0.03); white-space: nowrap;
}
.quota-table tr:hover td { background: rgba(255,255,255,0.02); }
.quota-table tr.row-dim td { opacity: 0.5; }
.quota-table tr.row-dim:hover td { opacity: 0.7; }

.quota-val { font-weight: 500; }
.quota-val.quota-warn { color: #fca5a5; }
.quota-input {
  width: 60px; padding: 4px 8px; border-radius: 6px;
  border: 1px solid rgba(255,255,255,0.15);
  background: rgba(0,0,0,0.3); color: #e8e8f0; font-size: 13px; text-align: center;
}
.quota-input:focus { outline: none; border-color: #7b5cff; }

.status-tag {
  display: inline-block; padding: 1px 8px; border-radius: 8px;
  font-size: 0.72rem; font-weight: 600;
}
.status-pending { background: rgba(251,146,60,0.2); color: #fdba74; }
.status-approved { background: rgba(52,211,153,0.2); color: #6ee7b7; }
.status-rejected { background: rgba(248,113,113,0.15); color: #fca5a5; }
.status-deactivated { background: rgba(148,163,184,0.15); color: #94a3b8; }

.badge { display: inline-block; margin-left: 6px; padding: 0 5px; border-radius: 4px; font-size: 10px; font-weight: 600; vertical-align: middle; }
.badge-admin { background: rgba(123,92,255,0.2); color: #c8b6ff; }

/* 按钮 */
.btn { padding: 10px 20px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.1); background: rgba(255,255,255,0.04); color: #aaaacc; cursor: pointer; font-size: 14px; transition: all 0.2s; }
.btn:hover:not(:disabled) { background: rgba(255,255,255,0.08); }
.btn.sm { padding: 6px 12px; font-size: 12px; }
.btn.xs { padding: 3px 10px; font-size: 11px; border-radius: 6px; }
.btn.primary { background: linear-gradient(135deg, #7b5cff, #b06cff); border: none; color: #fff; }
.btn.danger { border-color: rgba(255,107,107,0.3); color: #ff6b6b; }
.btn.danger:hover { background: rgba(255,107,107,0.1); }
.btn.success { border-color: rgba(52,211,153,0.3); color: #6ee7b7; }
.btn.success:hover { background: rgba(52,211,153,0.1); }
.btn:disabled { opacity: 0.4; cursor: not-allowed; }

.empty-hint { text-align: center; padding: 20px; color: #64748b; font-size: 0.88rem; }
.error-msg { text-align: center; padding: 12px; color: #fca5a5; font-size: 0.85rem; margin-top: 12px; }
.hint-text { color: #555; font-size: 0.8rem; }

/* ============ 系统配置 ============ */

.btn.ghost { background: transparent; border-color: rgba(255, 255, 255, 0.12); color: #8888aa; }

.cfg-actions { display: flex; gap: 8px; }

.cfg-note {
  font-size: 0.82rem;
  line-height: 1.7;
  color: #8888aa;
  margin-bottom: 18px;
}

.cfg-note code {
  padding: 1px 5px;
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.08);
  font-size: 0.95em;
}

.cfg-note strong { color: #c8c8e0; }

.cfg-groups { display: flex; flex-direction: column; gap: 22px; }

.cfg-group-title {
  font-size: 0.85rem;
  font-weight: 500;
  color: #7b7b9c;
  margin-bottom: 10px;
  padding-bottom: 6px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.cfg-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  padding: 9px 0;
}

.cfg-label { flex: 1; min-width: 0; }

.cfg-name { font-size: 0.88rem; color: var(--text-primary, #e8e8f0); }

.cfg-badge {
  display: inline-block;
  margin-left: 6px;
  padding: 1px 7px;
  border-radius: 999px;
  font-size: 0.7rem;
  color: #fbbf24;
  background: rgba(251, 191, 36, 0.14);
  border: 1px solid rgba(251, 191, 36, 0.3);
}

.cfg-badge-dirty {
  color: #7b5cff;
  background: rgba(123, 92, 255, 0.16);
  border-color: rgba(123, 92, 255, 0.4);
}

.cfg-hint {
  margin-top: 4px;
  font-size: 0.76rem;
  line-height: 1.6;
  color: #6b6b88;
}

.cfg-control {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.cfg-input {
  width: 200px;
  padding: 6px 10px;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.15);
  background: rgba(0, 0, 0, 0.3);
  color: var(--text-primary, #e8e8f0);
  font-size: 0.85rem;
}

.cfg-input:focus { outline: none; border-color: #7b5cff; }

.cfg-default {
  font-size: 0.75rem;
  color: #5a5a78;
  white-space: nowrap;
}

.cfg-revert {
  border: none;
  background: none;
  padding: 0;
  font-size: 0.75rem;
  color: #7b5cff;
  cursor: pointer;
  text-decoration: underline;
  white-space: nowrap;
}

.msg {
  margin-top: 16px;
  padding: 8px 12px;
  border-radius: 8px;
  font-size: 0.82rem;
}

.msg-ok { color: #6ee7b7; background: rgba(52, 211, 153, 0.1); }
.msg-err { color: #fca5a5; background: rgba(255, 107, 107, 0.1); }

@media (max-width: 720px) {
  .cfg-row { flex-direction: column; align-items: stretch; gap: 8px; }
  .cfg-input { width: 100%; }
}
</style>
