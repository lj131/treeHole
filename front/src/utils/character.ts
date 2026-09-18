/** 根据角色 ID 生成稳定的渐变色 */
export function getCharacterGradient(id: string): string {
  const palettes = [
    ['#667eea', '#764ba2'],
    ['#f093fb', '#f5576c'],
    ['#4facfe', '#00f2fe'],
    ['#43e97b', '#38f9d7'],
    ['#fa709a', '#fee140'],
    ['#a18cd1', '#fbc2eb'],
  ]
  let hash = 0
  for (let i = 0; i < id.length; i++) {
    hash = id.charCodeAt(i) + ((hash << 5) - hash)
  }
  const palette = palettes[Math.abs(hash) % palettes.length]!
  return `linear-gradient(135deg, ${palette[0]}, ${palette[1]})`
}

export function getCharacterInitial(name: string): string {
  return name.charAt(0) || '?'
}

const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000'

/** 获取角色头像完整 URL，无头像时返回空字符串 */
export function getCharacterAvatarUrl(avatar?: string): string {
  if (!avatar) return ''
  if (avatar.startsWith('http')) return avatar
  return `${API_BASE}${avatar}`
}

export function getMoodEmoji(mood?: string): string {
  const map: Record<string, string> = {
    开心: '😊',
    平静: '😌',
    冷淡: '😐',
    生气: '😤',
    害羞: '😳',
    困: '😴',
    兴奋: '🤩',
    难过: '😢',
  }
  return map[mood ?? ''] ?? '💭'
}

export function getEnergyColor(energy: number): string {
  if (energy >= 70) return '#57ff93'
  if (energy >= 40) return '#ffd93d'
  return '#ff6b6b'
}

/** `character_state.current_event` 的两种形态（后端两种都发过） */
export type CurrentEvent =
  | string
  | {
      title?: string
      description?: string
      event_date?: string
      start_time?: string
      impact?: number
    }
  | null
  | undefined

/**
 * 归一化 `current_event`。
 *
 * 后端这个字段既可能是纯字符串，也可能是 `{ title, description, ... }` 对象。
 * 直接在模板里插值对象会渲染成 `{"title":"",...}` 这种原始 JSON（Chat 左栏就踩过），
 * 所以统一走这里取文本。
 */
export function formatCurrentEvent(ce: CurrentEvent): { title: string; description: string } {
  if (!ce) return { title: '', description: '' }
  if (typeof ce === 'string') return { title: ce.trim(), description: '' }
  return {
    title: (ce.title ?? '').trim(),
    description: (ce.description ?? '').trim(),
  }
}
