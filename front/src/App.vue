<script setup lang="ts">
import { RouterLink, RouterView, useRoute } from 'vue-router'
import { onMounted, ref, computed } from 'vue'
import { useAuthStore } from '@/stores/authStore'
import AuthModal from '@/components/AuthModal.vue'

const auth = useAuthStore()
const route = useRoute()
const isFullscreen = computed(() => route.meta.fullscreen === true)

const isDark = ref(true)

const avatarSrc = computed(() => {
  const base = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000'
  return auth.user?.avatar ? `${base}${auth.user.avatar}` : ''
})

const toggleTheme = () => {
  const html = document.documentElement
  const currentTheme = html.getAttribute('data-theme')
  const newTheme = currentTheme === 'dark' ? 'light' : 'dark'
  html.setAttribute('data-theme', newTheme)
  isDark.value = newTheme === 'dark'
  localStorage.setItem('theme', newTheme)
}

// Initialize theme + auth
onMounted(async () => {
  const savedTheme = localStorage.getItem('theme') || 'dark'
  document.documentElement.setAttribute('data-theme', savedTheme)
  isDark.value = savedTheme === 'dark'
  await auth.fetchMe()
})
</script>

<template>
  <div class="app" :class="{ fullscreen: isFullscreen }">
    <!-- Navigation -->
    <nav v-if="!isFullscreen" class="navbar">
      <div class="nav-brand">
        <div class="brand-logo">
          <span class="logo-icon">🤖</span>
          <span class="brand-name">AI Test</span>
        </div>
      </div>

      <div class="nav-links">
        <RouterLink
          to="/"
          class="nav-link"
          active-class="active"
        >
          <span class="link-icon">🏠</span>
          <span class="link-text">首页</span>
        </RouterLink>

        <RouterLink
          to="/chat"
          class="nav-link"
          active-class="active"
        >
          <span class="link-icon">💬</span>
          <span class="link-text">角色聊天</span>
        </RouterLink>

        <RouterLink
          to="/characters"
          class="nav-link"
          active-class="active"
        >
          <span class="link-icon">🎭</span>
          <span class="link-text">角色</span>
        </RouterLink>

        <RouterLink
          to="/memory"
          class="nav-link"
          active-class="active"
        >
          <span class="link-icon">🧠</span>
          <span class="link-text">记忆</span>
        </RouterLink>

        <RouterLink
          to="/settings"
          class="nav-link"
          active-class="active"
        >
          <span class="link-icon">⚙️</span>
          <span class="link-text">设置</span>
        </RouterLink>
      </div>

      <div class="nav-actions">
        <button class="theme-toggle" @click="toggleTheme">
          <span class="theme-icon">{{ isDark ? '☀️' : '🌙' }}</span>
        </button>
      </div>

      <!-- 用户区 -->
      <div class="nav-user">
        <template v-if="!auth.isLoggedIn">
          <button class="user-btn login-btn" @click="auth.openAuth()">登录</button>
        </template>
        <template v-else>
          <router-link to="/settings" class="user-avatar-link">
            <img v-if="auth.user?.avatar" :src="avatarSrc" class="user-avatar-sm" alt="头像" />
            <span v-else class="user-avatar-fallback">{{ (auth.user?.nickname || auth.user?.username || '?')[0]?.toUpperCase() }}</span>
          </router-link>
          <span class="user-name">{{ auth.user?.nickname || auth.user?.username }}</span>
          <span v-if="auth.isPending" class="user-badge pending">待审批</span>
          <span v-else-if="auth.isApproved" class="user-badge approved">已认证</span>
          <router-link v-if="auth.isAdmin" to="/admin" class="user-btn admin-btn">管理</router-link>
          <button class="user-btn logout-btn" @click="auth.logout()">退出</button>
        </template>
      </div>
    </nav>

    <!-- Auth Modal -->
    <AuthModal />

    <!-- Main Content -->
    <main class="main-content">
      <RouterView v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </RouterView>
    </main>
  </div>
</template>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

:root {
  --bg-primary: #0f0f23;
  --bg-secondary: #1a1a2e;
  --bg-tertiary: #16213e;
  --text-primary: #ffffff;
  --text-secondary: #a1a1aa;
  --accent-primary: #667eea;
  --accent-secondary: #764ba2;
  --border-color: rgba(255, 255, 255, 0.1);
  --shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
  --transition: all 0.3s ease;
}

[data-theme="light"] {
  --bg-primary: #ffffff;
  --bg-secondary: #f8fafc;
  --bg-tertiary: #f1f5f9;
  --text-primary: #1e293b;
  --text-secondary: #64748b;
  --accent-primary: #3b82f6;
  --accent-secondary: #8b5cf6;
  --border-color: rgba(0, 0, 0, 0.1);
  --shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
}

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  background-color: var(--bg-primary);
  color: var(--text-primary);
  transition: var(--transition);
}

.app {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.app.fullscreen {
  width: 100%;
  min-height: 100vh;
}

.app.fullscreen .main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  width: 100%;
  min-width: 0;
  overflow: hidden;
}

/* Navigation */
.navbar {
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border-color);
  padding: 0 2rem;
  height: 70px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  position: sticky;
  top: 0;
  z-index: 100;
  backdrop-filter: blur(10px);
  background: rgba(26, 26, 46, 0.8);
}

.nav-brand {
  display: flex;
  align-items: center;
  gap: 12px;
}

.brand-logo {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 1.5rem;
  font-weight: 700;
  background: linear-gradient(135deg, var(--accent-primary) 0%, var(--accent-secondary) 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.logo-icon {
  font-size: 2rem;
}

.nav-links {
  display: flex;
  gap: 2rem;
  align-items: center;
}

.nav-link {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  text-decoration: none;
  color: var(--text-secondary);
  border-radius: 12px;
  transition: var(--transition);
  position: relative;
  font-weight: 500;
}

.nav-link:hover {
  color: var(--text-primary);
  background: rgba(255, 255, 255, 0.05);
}

.nav-link.active {
  color: var(--text-primary);
  background: rgba(102, 126, 234, 0.1);
}

.nav-link.active::before {
  content: '';
  position: absolute;
  bottom: -20px;
  left: 50%;
  transform: translateX(-50%);
  width: 30px;
  height: 3px;
  background: linear-gradient(135deg, var(--accent-primary) 0%, var(--accent-secondary) 100%);
  border-radius: 2px;
}

.link-icon {
  font-size: 1.2rem;
}

.link-text {
  font-size: 1rem;
}

.nav-actions {
  display: flex;
  align-items: center;
}

.theme-toggle {
  background: transparent;
  border: 1px solid var(--border-color);
  color: var(--text-primary);
  width: 45px;
  height: 45px;
  border-radius: 12px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: var(--transition);
  font-size: 1.2rem;
}

.theme-toggle:hover {
  background: rgba(255, 255, 255, 0.05);
  transform: rotate(180deg);
}

/* 用户区 */
.nav-user {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}
.user-avatar-link {
  display: flex;
  text-decoration: none;
}
.user-avatar-sm {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  object-fit: cover;
}
.user-avatar-fallback {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 700;
  color: #fff;
  background: linear-gradient(135deg, var(--accent-primary, #667eea), var(--accent-secondary, #764ba2));
}
.user-name {
  font-size: 0.85rem;
  color: #cbd5e1;
  font-weight: 500;
}
.user-badge {
  padding: 2px 8px;
  border-radius: 8px;
  font-size: 0.7rem;
  font-weight: 600;
}
.user-badge.pending {
  background: rgba(251, 146, 60, 0.2);
  color: #fdba74;
}
.user-badge.approved {
  background: rgba(52, 211, 153, 0.2);
  color: #6ee7b7;
}
.user-btn {
  padding: 6px 14px;
  border-radius: 8px;
  border: none;
  font-size: 0.82rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
}
.login-btn {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: #fff;
}
.login-btn:hover { opacity: 0.9; transform: translateY(-1px); }
.logout-btn {
  background: transparent;
  color: #94a3b8;
  border: 1px solid rgba(255,255,255,0.1);
}
.logout-btn:hover { background: rgba(248,113,113,0.12); color: #fca5a5; border-color: rgba(248,113,113,0.3); }
.admin-btn {
  background: rgba(251, 146, 60, 0.15);
  color: #fdba74;
  border: 1px solid rgba(251,146,60,0.3);
}
.admin-btn:hover { background: rgba(251,146,60,0.25); }

/* Main Content */
.main-content {
  flex: 1;
  width: 100%;
}

/* Page Transitions */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease, transform 0.3s ease;
}

.fade-enter-from {
  opacity: 0;
  transform: translateY(10px);
}

.fade-leave-to {
  opacity: 0;
  transform: translateY(-10px);
}

/* Responsive Design */
@media (max-width: 768px) {
  .navbar {
    padding: 0 1rem;
  }

  .nav-links {
    gap: 1rem;
  }

  .nav-link {
    padding: 8px 12px;
    gap: 6px;
  }

  .link-text {
    display: none;
  }

  .brand-name {
    display: none;
  }

  .logo-icon {
    font-size: 1.5rem;
  }
}

@media (max-width: 480px) {
  .nav-links {
    gap: 0.5rem;
  }

  .nav-link {
    padding: 8px;
  }

  .link-icon {
    font-size: 1rem;
  }
}
</style>
