/**
 * 语音包 API 客户端。
 *
 * 全部接口都是**管理员专用**（后端 `require_admin`）：语音包是全局资源，
 * 改动会影响所有角色和所有用户。
 *
 * 这里没有复用 `request.ts`：它强制 `Content-Type: application/json` 且只认 JSON 响应，
 * 而本模块要传 `FormData`（上传参考音频，Content-Type 必须留给浏览器带 boundary）
 * 和收 `Blob`（试听返回音频字节）。顺带把后端的 `detail` 提取成可读错误信息。
 */
import type {
  VoiceOptionsResponse,
  VoicePack,
  VoicePackInput,
  VoicePacksResponse,
  VoicePreviewInput,
} from '@/types/api'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000'

function authHeaders(json = true): Record<string, string> {
  const headers: Record<string, string> = {}
  if (json) headers['Content-Type'] = 'application/json'
  try {
    const token = localStorage.getItem('auth_token')
    if (token) headers['Authorization'] = `Bearer ${token}`
  } catch {
    // localStorage 不可用（SSR / 隐私模式），忽略
  }
  return headers
}

/** 从错误响应里挖出后端给的 `detail`，拿不到就退回状态码文案 */
async function toError(res: Response, fallback: string): Promise<Error> {
  let detail = ''
  try {
    const body = await res.json()
    detail = body?.detail || body?.error || ''
  } catch {
    // 响应不是 JSON（比如网关返回的 HTML），忽略
  }
  return new Error(detail || `${fallback}（HTTP ${res.status}）`)
}

async function voiceRequest<T>(url: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_BASE}${url}`, {
    ...options,
    headers: { ...authHeaders(), ...(options.headers as Record<string, string>) },
  })
  if (!res.ok) throw await toError(res, '请求失败')
  return res.json() as Promise<T>
}

/** 可选音色目录 + 引擎可用状态 */
export const getVoiceOptions = () => {
  return voiceRequest<VoiceOptionsResponse>('/voice/voices')
}

/** 语音包库 + 每个角色当前生效的音色 */
export const getVoicePacks = () => {
  return voiceRequest<VoicePacksResponse>('/voice/packs')
}

export const createVoicePack = (payload: VoicePackInput) => {
  return voiceRequest<{ message: string; pack: VoicePack }>('/voice/packs', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

/** 局部更新：只传要改的字段 */
export const updateVoicePack = (packId: string, payload: VoicePackInput) => {
  return voiceRequest<{ message: string; pack: VoicePack }>(`/voice/packs/${encodeURIComponent(packId)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export const deleteVoicePack = (packId: string) => {
  return voiceRequest<{ message: string; unbound?: string[]; warning?: string }>(
    `/voice/packs/${encodeURIComponent(packId)}`,
    { method: 'DELETE' },
  )
}

/** 上传参考音频（给将来的音色克隆引擎用） */
export const uploadVoiceReference = async (packId: string, file: File) => {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(`${API_BASE}/voice/packs/${encodeURIComponent(packId)}/reference`, {
    method: 'POST',
    // 不要手写 Content-Type：必须让浏览器自己带上 multipart 的 boundary
    headers: authHeaders(false),
    body: form,
  })
  if (!res.ok) throw await toError(res, '参考音频上传失败')
  return (await res.json()) as { message: string; pack: VoicePack; size_kb: number }
}

export const deleteVoiceReference = (packId: string) => {
  return voiceRequest<{ message: string; pack: VoicePack; warning?: string }>(
    `/voice/packs/${encodeURIComponent(packId)}/reference`,
    { method: 'DELETE' },
  )
}

/** 试听：返回音频 Blob，调用方自行 `URL.createObjectURL` 播放并记得 revoke */
export const previewVoice = async (payload: VoicePreviewInput): Promise<Blob> => {
  const res = await fetch(`${API_BASE}/voice/preview`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw await toError(res, '试听失败')
  return res.blob()
}

/** 给角色指定语音包；`packId=null` 表示解绑（回退内置默认音色） */
export const bindVoicePack = (characterId: string, packId: string | null) => {
  return voiceRequest<{ message: string; character_id: string }>('/voice/bindings', {
    method: 'POST',
    body: JSON.stringify({ character_id: characterId, pack_id: packId }),
  })
}
