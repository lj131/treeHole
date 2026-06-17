/**
 * 用户认证状态管理
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export interface AuthUser {
  id: number
  username: string
  role: string
  status: string // "pending" | "approved" | "rejected"
}

const TOKEN_KEY = 'auth_token'

function _getStoredToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

function _setStoredToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    // ignore
  }
}

export const useAuthStore = defineStore('auth', () => {
  const user = ref<AuthUser | null>(null)
  const token = ref<string | null>(_getStoredToken())
  const loading = ref(false)
  const showAuthModal = ref(false)

  const isLoggedIn = computed(() => !!user.value && !!token.value)
  const isAdmin = computed(() => user.value?.role === 'admin')
  const isApproved = computed(() => user.value?.status === 'approved' || isAdmin.value)
  const isPending = computed(() => user.value?.status === 'pending')

  const setUser = (u: AuthUser | null, t: string | null) => {
    user.value = u
    token.value = t
    _setStoredToken(t)
  }

  const fetchMe = async () => {
    const t = _getStoredToken()
    if (!t) return
    try {
      const { request } = await import('@/api/request')
      const res = await request<{ user: AuthUser }>('/auth/me', {
        headers: { Authorization: `Bearer ${t}` },
      })
      user.value = res.user
      token.value = t
    } catch {
      // token 已过期或无效
      setUser(null, null)
    }
  }

  const login = async (username: string, password: string): Promise<string | null> => {
    loading.value = true
    try {
      const { request } = await import('@/api/request')
      const res = await request<{ token: string; user: AuthUser }>('/auth/login', {
        method: 'POST',
        body: JSON.stringify({ username, password }),
      })
      setUser(res.user, res.token)
      showAuthModal.value = false
      return null // null = 成功
    } catch (e: any) {
      return e.message || '登录失败'
    } finally {
      loading.value = false
    }
  }

  const register = async (username: string, password: string): Promise<string | null> => {
    loading.value = true
    try {
      const { request } = await import('@/api/request')
      await request<{ message: string }>('/auth/register', {
        method: 'POST',
        body: JSON.stringify({ username, password }),
      })
      return null // null = 成功
    } catch (e: any) {
      return e.message || '注册失败'
    } finally {
      loading.value = false
    }
  }

  const logout = () => {
    setUser(null, null)
  }

  const openAuth = () => {
    showAuthModal.value = true
  }

  const closeAuth = () => {
    showAuthModal.value = false
  }

  return {
    user,
    token,
    loading,
    showAuthModal,
    isLoggedIn,
    isAdmin,
    isApproved,
    isPending,
    fetchMe,
    login,
    register,
    logout,
    openAuth,
    closeAuth,
  }
})
