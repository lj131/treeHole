import { createRouter, createWebHashHistory } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'
import HomeView from '../views/HomeView.vue'

const router = createRouter({
  history: createWebHashHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'home',
      component: HomeView,
    },
    {
      path: '/about',
      name: 'about',
      meta: { title: '系统设置' },
      component: () => import('../views/AboutView.vue'),
    },
    {
      path: '/chat',
      name: 'character-chat',
      meta: { fullscreen: true },
      component: () => import('../views/Chat.vue'),
    },
    {
      path: '/characters',
      name: 'characters',
      meta: { title: '角色管理' },
      component: () => import('../views/CharactersView.vue'),
    },
    {
      path: '/memory',
      name: 'memory',
      meta: { title: '记忆中心' },
      component: () => import('../views/MemoryView.vue'),
    },
    {
      path: '/story',
      name: 'story',
      meta: { title: '剧情' },
      component: () => import('../views/StoryView.vue'),
    },
    {
      path: '/widget',
      name: 'desktop-widget',
      meta: { fullscreen: true, title: '桌面挂件' },
      component: () => import('../views/DesktopWidget.vue'),
    },
    {
      path: '/settings',
      name: 'settings',
      meta: { title: '个人设置' },
      component: () => import('../views/SettingsView.vue'),
    },
    {
      path: '/admin',
      name: 'admin',
      meta: { title: '管理面板', adminOnly: true },
      component: () => import('../views/AdminView.vue'),
    },
    {
      path: '/poc-3d',
      name: 'poc-3d',
      meta: { title: 'LIVE3D PoC' },
      component: () => import('../views/PoC3DAvatar.vue'),
    },
  ],
})

// 路由守卫：仅管理员可进 /admin
router.beforeEach((to) => {
  if (to.meta.adminOnly) {
    const auth = useAuthStore()
    if (!auth.isAdmin) {
      return { name: 'home' }
    }
  }
})

export default router
