<template>
  <div class="settings-page">
    <h1 class="page-title">个人设置</h1>

    <div class="settings-grid">
      <!-- 个人信息 -->
      <section class="card">
        <h2 class="card-title">👤 个人信息</h2>
        <div class="profile-row">
          <div class="avatar-wrap" @click="triggerAvatarUpload">
            <img v-if="avatarUrl" :src="avatarUrl" class="avatar-img" alt="头像" />
            <div v-else class="avatar-fallback">{{ avatarInitial }}</div>
            <div class="avatar-overlay">📷</div>
            <input ref="avatarInput" type="file" accept="image/*" hidden @change="onAvatarChange" />
          </div>
          <div class="profile-fields">
            <label class="field-label">昵称</label>
            <div class="input-row">
              <input v-model="nickname" class="input" placeholder="设置昵称" maxlength="50" />
              <button class="btn btn-sm" :disabled="savingProfile" @click="saveProfile">
                {{ savingProfile ? '保存中...' : '保存' }}
              </button>
            </div>
            <p class="field-hint">用户名：{{ auth.user?.username }}</p>
          </div>
        </div>
        <p v-if="profileMsg" class="msg" :class="profileOk ? 'msg-ok' : 'msg-err'">{{ profileMsg }}</p>
      </section>

      <!-- 修改密码 -->
      <section class="card">
        <h2 class="card-title">🔒 修改密码</h2>
        <div class="form-col">
          <input v-model="pwForm.old" type="password" class="input" placeholder="当前密码" />
          <input v-model="pwForm.new1" type="password" class="input" placeholder="新密码（至少4位）" />
          <input v-model="pwForm.new2" type="password" class="input" placeholder="确认新密码" />
          <button class="btn" :disabled="changingPw" @click="doChangePassword">
            {{ changingPw ? '修改中...' : '修改密码' }}
          </button>
        </div>
        <p v-if="pwMsg" class="msg" :class="pwOk ? 'msg-ok' : 'msg-err'">{{ pwMsg }}</p>
      </section>

      <!-- 消息通知 -->
      <section class="card">
        <h2 class="card-title">🔔 消息通知</h2>
        <div class="notif-row">
          <div>
            <p class="notif-desc">页面后台时收到 AI 回复，推送浏览器通知</p>
            <p class="notif-status">
              权限状态：<strong>{{ permText }}</strong>
            </p>
          </div>
          <div class="notif-actions">
            <button v-if="notifPerm === 'default'" class="btn btn-sm" @click="askNotifPerm">
              允许通知
            </button>
            <label class="toggle-label" v-if="notifPerm === 'granted'">
              <input type="checkbox" v-model="notifEnabled" @change="saveNotifSetting" />
              <span class="toggle-track"><span class="toggle-thumb" /></span>
              {{ notifEnabled ? '已开启' : '已关闭' }}
            </label>
          </div>
        </div>
      </section>

      <!-- 用量统计 -->
      <section class="card card-wide">
        <h2 class="card-title">📊 用量统计（最近 30 天）</h2>
        <div v-if="usageLoading" class="loading-text">加载中...</div>
        <div v-else-if="usage" class="usage-grid">
          <div class="stat-box">
            <span class="stat-num">{{ totalRequests }}</span>
            <span class="stat-label">总调用次数</span>
          </div>
          <div class="stat-box">
            <span class="stat-num">{{ totalTokensIn }}</span>
            <span class="stat-label">输入 Token</span>
          </div>
          <div class="stat-box">
            <span class="stat-num">{{ totalTokensOut }}</span>
            <span class="stat-label">输出 Token</span>
          </div>
        </div>
        <div v-if="endpointList.length" class="endpoint-list">
          <div v-for="ep in endpointList" :key="ep.name" class="endpoint-row">
            <span class="ep-name">{{ ep.name }}</span>
            <span class="ep-count">{{ ep.count }} 次</span>
            <div class="ep-bar">
              <div class="ep-bar-fill" :style="{ width: epPercent(ep.count) + '%' }"></div>
            </div>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useAuthStore } from '@/stores/authStore'
import { updateProfile, changePassword, uploadAvatar, getMyUsage } from '@/api/auth'
import {
  isNotificationSupported,
  getNotificationPermission,
  requestNotificationPermission,
  isNotificationEnabled,
  setNotificationEnabled,
} from '@/utils/notification'

const auth = useAuthStore()

// ---- 个人信息 ----
const nickname = ref(auth.user?.nickname || '')
const avatarUrl = ref<string | null>(auth.user?.avatar ? `${import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000'}${auth.user.avatar}` : null)
const avatarInput = ref<HTMLInputElement | null>(null)
const avatarInitial = computed(() => (auth.user?.nickname || auth.user?.username || '?')[0]?.toUpperCase())
const savingProfile = ref(false)
const profileMsg = ref('')
const profileOk = ref(false)

async function saveProfile() {
  savingProfile.value = true
  profileMsg.value = ''
  try {
    const res = await updateProfile({ nickname: nickname.value })
    auth.user = res.user
    profileMsg.value = '保存成功'
    profileOk.value = true
  } catch (e: any) {
    profileMsg.value = e.message || '保存失败'
    profileOk.value = false
  } finally {
    savingProfile.value = false
  }
}

function triggerAvatarUpload() {
  avatarInput.value?.click()
}

async function onAvatarChange(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file) return
  try {
    const res = await uploadAvatar(file)
    if (auth.user) auth.user.avatar = res.avatar
    const base = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000'
    avatarUrl.value = `${base}${res.avatar}`
    profileMsg.value = '头像上传成功'
    profileOk.value = true
  } catch {
    profileMsg.value = '头像上传失败'
    profileOk.value = false
  }
}

// ---- 修改密码 ----
const pwForm = ref({ old: '', new1: '', new2: '' })
const changingPw = ref(false)
const pwMsg = ref('')
const pwOk = ref(false)

async function doChangePassword() {
  pwMsg.value = ''
  if (pwForm.value.new1 !== pwForm.value.new2) {
    pwMsg.value = '两次输入的新密码不一致'
    pwOk.value = false
    return
  }
  changingPw.value = true
  try {
    await changePassword({ old_password: pwForm.value.old, new_password: pwForm.value.new1 })
    pwMsg.value = '密码修改成功'
    pwOk.value = true
    pwForm.value = { old: '', new1: '', new2: '' }
  } catch (e: any) {
    pwMsg.value = e.message || '修改失败'
    pwOk.value = false
  } finally {
    changingPw.value = false
  }
}

// ---- 通知 ----
const notifPerm = ref<NotificationPermission | 'unsupported'>(getNotificationPermission())
const notifEnabled = ref(isNotificationEnabled())

const permText = computed(() => {
  if (notifPerm.value === 'unsupported') return '浏览器不支持'
  if (notifPerm.value === 'granted') return '已允许'
  if (notifPerm.value === 'denied') return '已拒绝（需在浏览器设置中允许）'
  return '未授权'
})

async function askNotifPerm() {
  const p = await requestNotificationPermission()
  notifPerm.value = p
}

function saveNotifSetting() {
  setNotificationEnabled(notifEnabled.value)
}

// ---- 用量统计 ----
interface UsageEndpoint {
  count: number
  tokens_in: number
  tokens_out: number
}
interface UsageData {
  user_id: number
  days: number
  by_endpoint: Record<string, UsageEndpoint>
}

const usage = ref<UsageData | null>(null)
const usageLoading = ref(true)

const endpointList = computed(() => {
  if (!usage.value?.by_endpoint) return []
  return Object.entries(usage.value.by_endpoint).map(([name, data]) => ({
    name,
    count: data.count,
    tokens_in: data.tokens_in,
    tokens_out: data.tokens_out,
  }))
})

const totalRequests = computed(() => endpointList.value.reduce((s, e) => s + e.count, 0))
const totalTokensIn = computed(() => endpointList.value.reduce((s, e) => s + e.tokens_in, 0))
const totalTokensOut = computed(() => endpointList.value.reduce((s, e) => s + e.tokens_out, 0))

function epPercent(count: number): number {
  if (!totalRequests.value) return 0
  return Math.round((count / totalRequests.value) * 100)
}

onMounted(async () => {
  try {
    usage.value = await getMyUsage(30)
  } catch {
    /* ignore */
  } finally {
    usageLoading.value = false
  }
})
</script>

<style scoped>
.settings-page {
  max-width: 900px;
  margin: 0 auto;
  padding: 24px 16px;
}

.page-title {
  font-size: 24px;
  font-weight: 700;
  color: var(--color-text);
  margin-bottom: 24px;
}

.settings-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}

.card {
  background: var(--bg-secondary, #1a1a2e);
  border-radius: 14px;
  padding: 20px;
  border: 1px solid rgba(255,255,255,0.06);
}

.card-wide {
  grid-column: 1 / -1;
}

.card-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--color-text);
  margin-bottom: 16px;
}

/* 个人信息 */
.profile-row {
  display: flex;
  gap: 16px;
  align-items: flex-start;
}

.avatar-wrap {
  position: relative;
  width: 64px;
  height: 64px;
  border-radius: 16px;
  overflow: hidden;
  cursor: pointer;
  flex-shrink: 0;
}

.avatar-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.avatar-fallback {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 28px;
  font-weight: 700;
  color: #fff;
  background: linear-gradient(135deg, var(--accent-primary, #667eea), var(--accent-secondary, #764ba2));
}

.avatar-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0,0,0,0.5);
  opacity: 0;
  transition: opacity 0.2s;
  font-size: 20px;
}

.avatar-wrap:hover .avatar-overlay {
  opacity: 1;
}

.profile-fields {
  flex: 1;
}

.field-label {
  display: block;
  font-size: 13px;
  color: var(--color-text);
  opacity: 0.7;
  margin-bottom: 6px;
}

.input-row {
  display: flex;
  gap: 8px;
}

.input {
  flex: 1;
  padding: 8px 12px;
  border-radius: 8px;
  border: 1px solid rgba(255,255,255,0.12);
  background: rgba(0,0,0,0.2);
  color: var(--color-text);
  font-size: 14px;
  outline: none;
}

.input:focus {
  border-color: var(--accent-primary, #667eea);
}

.field-hint {
  font-size: 12px;
  color: var(--color-text);
  opacity: 0.5;
  margin-top: 6px;
}

/* 表单 */
.form-col {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.btn {
  padding: 8px 16px;
  border-radius: 8px;
  border: none;
  background: linear-gradient(135deg, var(--accent-primary, #667eea), var(--accent-secondary, #764ba2));
  color: #fff;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.2s;
}

.btn:hover { opacity: 0.9; }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-sm { padding: 6px 12px; font-size: 13px; }

/* 消息 */
.msg {
  margin-top: 10px;
  font-size: 13px;
  padding: 6px 10px;
  border-radius: 6px;
}

.msg-ok { color: #4ade80; background: rgba(74,222,128,0.1); }
.msg-err { color: #f87171; background: rgba(248,113,113,0.1); }

/* 通知 */
.notif-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
}

.notif-desc {
  font-size: 14px;
  color: var(--color-text);
  opacity: 0.8;
}

.notif-status {
  font-size: 12px;
  color: var(--color-text);
  opacity: 0.6;
  margin-top: 4px;
}

.toggle-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  color: var(--color-text);
  cursor: pointer;
}

.toggle-label input { display: none; }

.toggle-track {
  width: 40px;
  height: 22px;
  border-radius: 11px;
  background: rgba(255,255,255,0.15);
  position: relative;
  transition: background 0.2s;
}

.toggle-label input:checked + .toggle-track {
  background: var(--accent-primary, #667eea);
}

.toggle-thumb {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #fff;
  transition: transform 0.2s;
}

.toggle-label input:checked + .toggle-track .toggle-thumb {
  transform: translateX(18px);
}

/* 用量统计 */
.usage-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}

.stat-box {
  text-align: center;
  padding: 14px;
  border-radius: 10px;
  background: rgba(0,0,0,0.2);
}

.stat-num {
  display: block;
  font-size: 24px;
  font-weight: 700;
  color: var(--accent-primary, #667eea);
}

.stat-label {
  display: block;
  font-size: 12px;
  color: var(--color-text);
  opacity: 0.6;
  margin-top: 4px;
}

.endpoint-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.endpoint-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.ep-name {
  width: 120px;
  font-size: 13px;
  color: var(--color-text);
}

.ep-count {
  width: 60px;
  font-size: 13px;
  color: var(--color-text);
  opacity: 0.7;
  text-align: right;
}

.ep-bar {
  flex: 1;
  height: 8px;
  border-radius: 4px;
  background: rgba(255,255,255,0.08);
  overflow: hidden;
}

.ep-bar-fill {
  height: 100%;
  border-radius: 4px;
  background: linear-gradient(90deg, var(--accent-primary, #667eea), var(--accent-secondary, #764ba2));
  transition: width 0.3s;
}

.loading-text {
  color: var(--color-text);
  opacity: 0.5;
  font-size: 14px;
  text-align: center;
  padding: 20px;
}

@media (max-width: 768px) {
  .settings-grid {
    grid-template-columns: 1fr;
  }
  .usage-grid {
    grid-template-columns: 1fr;
  }
}
</style>
