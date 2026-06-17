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
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { listUsers, updateQuota } from '@/api/auth'
import { request } from '@/api/request'
import type { User } from '@/types/api'

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
  } catch (e: any) {
    loadError.value = e.message || '加载失败'
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
  } catch (e: any) {
    loadError.value = e.message || '保存失败'
  }
}

const formatDate = (s?: string) => {
  if (!s) return ''
  try { return new Date(s).toLocaleDateString('zh-CN') } catch { return s }
}

onMounted(loadAll)
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
</style>
