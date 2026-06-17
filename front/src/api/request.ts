// src/api/request.ts

const API_BASE_URL = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000'

export async function request<T>(url: string, options: RequestInit = {}): Promise<T> {
  // 自动携带 JWT Token
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> || {}),
  }
  try {
    const token = localStorage.getItem('auth_token')
    if (token) {
      headers['Authorization'] = `Bearer ${token}`
    }
  } catch {
    // localStorage 不可用（SSR 等场景），忽略
  }

  const res = await fetch(`${API_BASE_URL}${url}`, {
    ...options,
    headers,
  })

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`API Error ${res.status}: ${errorText}`)
  }

  return res.json()
}
