// src/api/request.ts

const API_BASE_URL = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000'

export async function request<T>(url: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${url}`, {
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
    ...options,
  })

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`API Error ${res.status}: ${errorText}`)
  }

  return res.json()
}
