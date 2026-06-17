<template>
  <div v-if="store.showAuthModal" class="auth-mask" @click.self="store.closeAuth()">
    <div class="auth-modal glass-card">
      <!-- 关闭按钮 -->
      <button class="close-btn" @click="store.closeAuth()" :disabled="store.loading">×</button>

      <!-- Tab 切换 -->
      <div class="tabs">
        <button
          class="tab-btn"
          :class="{ active: tab === 'login' }"
          @click="tab = 'login'"
        >登录</button>
        <button
          class="tab-btn"
          :class="{ active: tab === 'register' }"
          @click="tab = 'register'"
        >注册</button>
      </div>

      <!-- 登录 -->
      <template v-if="tab === 'login'">
        <h2 class="modal-title">欢迎回来</h2>
        <p class="modal-tip">登录以使用全部功能</p>

        <div class="form-group">
          <label>用户名</label>
          <input
            v-model="username"
            class="form-input"
            placeholder="请输入用户名"
            :disabled="store.loading"
            @keydown.enter="handleLogin"
          />
        </div>
        <div class="form-group">
          <label>密码</label>
          <input
            v-model="password"
            class="form-input"
            type="password"
            placeholder="请输入密码"
            :disabled="store.loading"
            @keydown.enter="handleLogin"
          />
        </div>

        <p v-if="error" class="error-msg">{{ error }}</p>
        <p v-if="successMsg" class="success-msg">{{ successMsg }}</p>

        <button
          class="submit-btn"
          :disabled="!username.trim() || !password || store.loading"
          @click="handleLogin"
        >
          <span v-if="store.loading">登录中...</span>
          <span v-else>登 录</span>
        </button>
      </template>

      <!-- 注册 -->
      <template v-if="tab === 'register'">
        <h2 class="modal-title">创建账号</h2>
        <p class="modal-tip">注册后需等待管理员审批</p>

        <div class="form-group">
          <label>用户名 <span class="hint">（2-20 个字符）</span></label>
          <input
            v-model="username"
            class="form-input"
            placeholder="请输入用户名"
            :disabled="store.loading"
            @keydown.enter="handleRegister"
          />
        </div>
        <div class="form-group">
          <label>密码 <span class="hint">（至少 4 个字符）</span></label>
          <input
            v-model="password"
            class="form-input"
            type="password"
            placeholder="请输入密码"
            :disabled="store.loading"
            @keydown.enter="handleRegister"
          />
        </div>
        <div class="form-group">
          <label>确认密码</label>
          <input
            v-model="password2"
            class="form-input"
            type="password"
            placeholder="再次输入密码"
            :disabled="store.loading"
            @keydown.enter="handleRegister"
          />
        </div>

        <p v-if="error" class="error-msg">{{ error }}</p>
        <p v-if="successMsg" class="success-msg">{{ successMsg }}</p>

        <button
          class="submit-btn"
          :disabled="!username.trim() || !password || store.loading"
          @click="handleRegister"
        >
          <span v-if="store.loading">注册中...</span>
          <span v-else>注 册</span>
        </button>
      </template>

      <!-- 第三方登录预留 -->
      <div class="oauth-hint">
        <span class="divider">— 或 —</span>
        <p class="oauth-placeholder">第三方登录即将支持（Google / GitHub）</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useAuthStore } from '@/stores/authStore'

const store = useAuthStore()

const tab = ref<'login' | 'register'>('login')
const username = ref('')
const password = ref('')
const password2 = ref('')
const error = ref('')
const successMsg = ref('')

// 切换 tab 时清空表单
function switchTab(t: 'login' | 'register') {
  tab.value = t
  username.value = ''
  password.value = ''
  password2.value = ''
  error.value = ''
  successMsg.value = ''
}

// 用 watch 简单处理
import { watch } from 'vue'
watch(tab, () => {
  error.value = ''
  successMsg.value = ''
})

async function handleLogin() {
  error.value = ''
  successMsg.value = ''
  const err = await store.login(username.value.trim(), password.value)
  if (err) {
    error.value = err
  } else {
    username.value = ''
    password.value = ''
  }
}

async function handleRegister() {
  error.value = ''
  successMsg.value = ''
  if (password.value !== password2.value) {
    error.value = '两次密码不一致'
    return
  }
  if (password.value.length < 4) {
    error.value = '密码至少 4 个字符'
    return
  }
  const err = await store.register(username.value.trim(), password.value)
  if (err) {
    error.value = err
  } else {
    successMsg.value = '注册成功！请等待管理员审批通过后登录。'
    username.value = ''
    password.value = ''
    password2.value = ''
    // 3 秒后切回登录
    setTimeout(() => {
      tab.value = 'login'
      successMsg.value = ''
    }, 4000)
  }
}

// 在导出前定义 switchTab 引用
const _switchTab = switchTab
</script>

<style scoped>
.auth-mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2000;
  padding: 20px;
}

.glass-card {
  background: rgba(30, 30, 50, 0.95);
  backdrop-filter: blur(16px);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 20px;
}

.auth-modal {
  width: 100%;
  max-width: 400px;
  padding: 32px;
  position: relative;
}

.close-btn {
  position: absolute;
  top: 14px;
  right: 16px;
  border: none;
  background: transparent;
  color: #94a3b8;
  font-size: 22px;
  cursor: pointer;
  line-height: 1;
  padding: 4px 8px;
  border-radius: 8px;
  transition: all 0.2s ease;
}
.close-btn:hover:not(:disabled) {
  background: rgba(255,255,255,0.06);
  color: #fff;
}

.tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 20px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  padding-bottom: 12px;
}
.tab-btn {
  flex: 1;
  padding: 8px 0;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: #94a3b8;
  font-size: 0.95rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}
.tab-btn:hover { color: #e2e8f0; }
.tab-btn.active {
  background: rgba(123, 92, 255, 0.15);
  color: #c4b5fd;
}

.modal-title {
  font-size: 1.3rem;
  font-weight: 700;
  color: #f1f5f9;
  margin: 0 0 6px;
}
.modal-tip {
  margin: 0 0 20px;
  color: #94a3b8;
  font-size: 0.88rem;
}

.form-group {
  margin-bottom: 16px;
}
.form-group label {
  display: block;
  margin-bottom: 6px;
  font-size: 0.85rem;
  font-weight: 600;
  color: #cbd5e1;
}
.hint { color: #64748b; font-weight: 400; font-size: 0.78rem; }

.form-input {
  width: 100%;
  padding: 10px 14px;
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(255, 255, 255, 0.04);
  color: #e2e8f0;
  font-size: 0.92rem;
  font-family: inherit;
  box-sizing: border-box;
  transition: border-color 0.2s ease;
}
.form-input:focus { outline: none; border-color: rgba(123, 92, 255, 0.6); }
.form-input::placeholder { color: #64748b; }

.error-msg {
  margin: 0 0 12px;
  padding: 10px 14px;
  border-radius: 10px;
  background: rgba(248, 113, 113, 0.12);
  border: 1px solid rgba(248, 113, 113, 0.3);
  color: #fca5a5;
  font-size: 0.85rem;
}
.success-msg {
  margin: 0 0 12px;
  padding: 10px 14px;
  border-radius: 10px;
  background: rgba(52, 211, 153, 0.12);
  border: 1px solid rgba(52, 211, 153, 0.3);
  color: #6ee7b7;
  font-size: 0.85rem;
}

.submit-btn {
  width: 100%;
  padding: 12px;
  border-radius: 12px;
  border: none;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  font-weight: 600;
  font-size: 0.95rem;
  cursor: pointer;
  transition: all 0.25s ease;
  margin-bottom: 20px;
}
.submit-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 14px rgba(102, 126, 234, 0.5);
}
.submit-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.oauth-hint { text-align: center; }
.divider {
  display: block;
  margin-bottom: 10px;
  color: #64748b;
  font-size: 0.82rem;
}
.oauth-placeholder {
  margin: 0;
  color: #475569;
  font-size: 0.78rem;
}
</style>
