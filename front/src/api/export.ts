export type ExportFormat = 'markdown' | 'json'

/** token 存在哪（和 `api/request.ts` 同一份约定，那边没导出 getter） */
const TOKEN_KEY = 'auth_token'

/** 从 Content-Disposition 里取后端给的文件名（带角色名和日期） */
function filenameFromDisposition(disposition: string, fallback: string): string {
  // RFC 5987：filename*=UTF-8''<urlencoded>（中文名必须走这个，否则乱码）
  const starred = /filename\*=UTF-8''([^;]+)/i.exec(disposition)
  if (starred?.[1]) {
    try {
      return decodeURIComponent(starred[1])
    } catch {
      /* 解码失败就用兜底名 */
    }
  }
  const plain = /filename="([^"]+)"/i.exec(disposition)
  return plain?.[1] || fallback
}

/**
 * 导出我的数据（E11）并触发浏览器下载。
 *
 * 走 Blob 而不是 `window.open` —— 后者会被弹窗拦截，
 * 而且拿不到后端在 Content-Disposition 里给的文件名。
 */
export const downloadExport = async (format: ExportFormat): Promise<string> => {
  const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000'
  const token = localStorage.getItem(TOKEN_KEY)

  const res = await fetch(`${API_BASE}/export?format=${format}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!res.ok) {
    throw new Error(`导出失败（${res.status}）`)
  }

  const blob = await res.blob()
  const fallback = `treeHole-export.${format === 'markdown' ? 'md' : 'json'}`
  const filename = filenameFromDisposition(res.headers.get('content-disposition') || '', fallback)

  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  // 必须 revoke，否则每个导出的 Blob 都留在内存里
  URL.revokeObjectURL(url)
  return filename
}
