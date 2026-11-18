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
          <span class="logo-icon">🌳</span>
          <span class="brand-name">树洞</span>
          <span class="brand-sub">treeHole</span>
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
          to="/digest"
          class="nav-link"
          active-class="active"
        >
          <span class="link-icon">📰</span>
          <span class="link-text">世界日报</span>
        </RouterLink>

        <RouterLink
          to="/npc"
          class="nav-link"
          active-class="active"
        >
          <span class="link-icon">👥</span>
          <span class="link-text">群聊旁观</span>
        </RouterLink>

        <RouterLink
          to="/story"
          class="nav-link"
          active-class="active"
        >
          <span class="link-icon">📖</span>
          <span class="link-text">剧情</span>
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
  /* ── 设计 token（2026-11-17 建立 / 11-18 补全并铺开）────────
     全站结构样式的唯一锚点。迁移规则与例外清单见
     docs/superpowers/plans/2026-11-18-design-system.md。
     ⚠️ 只放"结构"值（圆角/边框/底色/字阶/文字色层级）；
     语义色（错误红/成功绿/警告橙/品牌紫渐变）刻意不进这里。 */
  --radius-card: 16px;        /* 兼容别名 = --radius-xl */
  --radius-btn: 10px;         /* 兼容别名 = --radius-md */
  --radius-xs: 6px;           /* 徽章/小标签 */
  --radius-sm: 8px;           /* 小按钮/输入框 */
  --radius-md: 10px;          /* 常规按钮/控件 */
  --radius-lg: 14px;          /* 中等卡片 */
  --radius-xl: 20px;          /* 大卡片/弹窗 */
  --radius-pill: 999px;       /* 胶囊/圆头像 */
  --card-bg: rgba(255, 255, 255, 0.04);
  --card-border: rgba(255, 255, 255, 0.08);
  --border-subtle: rgba(255, 255, 255, 0.06);  /* 分隔线/表格行 */
  --text-muted: #94a3b8;      /* 次要说明（统一掉 #8888aa 那套） */
  --text-subtle: #64748b;     /* 三级文字 */
  --text-body: #e2e8f0;       /* 正文强调 */
  --text-xs: 0.75rem;
  --text-sm: 0.85rem;
  --text-base: 1rem;
  --text-lg: 1.25rem;
  --text-xl: 1.5rem;
  --text-2xl: 2rem;
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
  --card-bg: rgba(0, 0, 0, 0.02);
  --card-border: rgba(0, 0, 0, 0.08);
  --border-subtle: rgba(0, 0, 0, 0.06);
  --text-muted: #64748b;
  --text-subtle: #94a3b8;
  --text-body: #1e293b;
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
  gap: 8px;
  font-size: 1.4rem;
  font-weight: 700;
  flex-shrink: 0;
  background: linear-gradient(135deg, var(--accent-primary) 0%, var(--accent-secondary) 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.logo-icon {
  font-size: 1.7rem;
  /* emoji 不走 background-clip，单独还原颜色 */
  -webkit-text-fill-color: initial;
}

.brand-sub {
  font-size: 0.72rem;
  font-weight: 500;
  letter-spacing: 0.5px;
  opacity: 0.7;
  padding-left: 8px;
  border-left: 1px solid var(--border-color);
}

.nav-links {
  display: flex;
  gap: 0.25rem;
  align-items: center;
  min-width: 0;              /* 允许在空间不足时收缩 */
  overflow-x: auto;          /* 极端窄屏横向滚动，而不是把文字挤成竖排 */
  scrollbar-width: none;     /* 隐藏滚动条，视觉更干净 */
}
.nav-links::-webkit-scrollbar {
  display: none;
}

.nav-link {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 9px 12px;
  text-decoration: none;
  color: var(--text-secondary);
  border-radius: 10px;
  transition: var(--transition);
  position: relative;
  font-weight: 500;
  /* 关键：不换行。1440px 下 8 个导航项 + 用户区本来就紧，
     不锁 nowrap 的话「角色聊天」「世界日报」会被挤成竖排两行。 */
  white-space: nowrap;
  flex-shrink: 0;
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
  bottom: -24px;
  left: 50%;
  transform: translateX(-50%);
  width: 24px;
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
  gap: 6px;
  margin-left: auto;
  flex-shrink: 0;
  white-space: nowrap;
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
  white-space: nowrap;
  /* 1440px 下 8 个导航项已经很满，昵称可省（头像+徽章足够表意） */
  display: none;
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
  padding: 6px 12px;
  border-radius: 8px;
  border: none;
  font-size: 0.82rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  /* 1024px 下"管理"曾被挤成竖排"管/理" */
  white-space: nowrap;
  flex-shrink: 0;
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
/* 中等屏：1440px 以下逐个收，避免文字折行 */
@media (max-width: 1280px) {
  .nav-link {
    padding: 9px 9px;
    gap: 5px;
  }
  .link-text {
    font-size: 0.9rem;
  }
  .brand-sub {
    display: none;
  }
}

@media (max-width: 1080px) {
  .nav-link {
    padding: 8px 8px;
  }
  .link-icon {
    font-size: 1rem;
  }
  .user-badge {
    display: none;
  }
}

@media (max-width: 768px) {
  .navbar {
    padding: 0 1rem;
  }

  .nav-links {
    gap: 0.25rem;
  }

  .nav-link {
    padding: 8px 10px;
    gap: 5px;
  }

  .link-text {
    display: none;
  }

  .brand-name,
  .brand-sub {
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
