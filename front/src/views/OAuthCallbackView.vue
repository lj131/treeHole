<template>
  <div class="oauth-callback-page">
    <div class="oauth-card">
      <div v-if="loading" class="oauth-state">
        <div class="spinner" aria-hidden="true"></div>
        <h2>正在完成登录…</h2>
        <p>请稍候，正在校验登录状态</p>
      </div>

      <div v-else-if="error" class="oauth-state">
        <div class="oauth-icon oauth-icon--error">!</div>
        <h2>登录未完成</h2>
        <p class="oauth-error">{{ error }}</p>
        <button class="oauth-btn" @click="backToLogin">返回登录</button>
      </div>

      <div v-else class="oauth-state">
        <div class="oauth-icon oauth-icon--ok">✓</div>
        <h2>登录成功</h2>
        <p>{{ pending ? '账号待管理员审批通过后即可使用' : '正在进入…' }}</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const loading = ref(true)
const error = ref('')
const pending = ref(false)

function clearTokenFromUrl() {
  // 后端把 token 放在 `#` 之后的 query 里（fragment 不会发给服务器），
  // 但会留在浏览器地址栏/历史里 —— 落地后立刻擦掉。
  try {
    const hash = window.location.hash.split('?')[0]
    window.history.replaceState(null, '', window.location.pathname + window.location.search + hash)
  } catch {
    // 某些环境禁用 replaceState，忽略即可（不影响登录结果）
  }
}

function backToLogin() {
  router.replace('/')
  // 等路由落地再开弹窗，避免被首页的初始化关掉
  window.setTimeout(() => auth.openAuth(), 0)
}

onMounted(async () => {
  const token = String(route.query.token || '')
  const failure = String(route.query.error || '')
  clearTokenFromUrl()

  if (failure) {
    error.value = failure
    loading.value = false
    return
  }
  if (!token) {
    error.value = '缺少登录凭证，请重新发起'
    loading.value = false
    return
  }

  const fail = await auth.applyOAuthToken(token)
  if (fail) {
    error.value = fail
    loading.value = false
    return
  }

  loading.value = false
  pending.value = auth.isPending
  if (!pending.value) {
    router.replace('/chat')
  }
})
</script>

<style scoped>
.oauth-callback-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: radial-gradient(circle at 50% 30%, #1e293b 0%, #0f172a 70%);
  color: var(--text-body);
  font-family: inherit;
}
.oauth-card {
  width: min(90vw, 380px);
  padding: 36px 28px;
  border-radius: var(--radius-xl);
  border: 1px solid rgba(148, 163, 184, 0.18);
  background: rgba(30, 41, 59, 0.78);
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.35);
  text-align: center;
}
.oauth-state h2 { margin: 14px 0 8px; font-size: 1.2rem; font-weight: 600; }
.oauth-state p { margin: 0; color: var(--text-muted); font-size: var(--text-sm); line-height: 1.6; }
.oauth-error { color: #fca5a5 !important; }
.oauth-icon {
  width: 46px; height: 46px; margin: 0 auto;
  border-radius: 50%; display: grid; place-items: center;
  font-size: 1.4rem; font-weight: 700;
}
.oauth-icon--ok { background: rgba(34, 197, 94, 0.16); color: #4ade80; }
.oauth-icon--error { background: rgba(239, 68, 68, 0.16); color: #f87171; }
.spinner {
  width: 34px; height: 34px; margin: 0 auto;
  border: 3px solid rgba(148, 163, 184, 0.25);
  border-top-color: #818cf8;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
.oauth-btn {
  margin-top: 22px; padding: 9px 22px;
  border: 1px solid rgba(129, 140, 248, 0.5);
  border-radius: var(--radius-md); background: rgba(99, 102, 241, 0.18);
  color: #c7d2fe; cursor: pointer; font-size: 0.9rem;
}
.oauth-btn:hover { background: rgba(99, 102, 241, 0.32); }
</style>
