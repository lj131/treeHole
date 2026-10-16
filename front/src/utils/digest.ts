/**
 * 世界日报的展示逻辑（纯函数）。
 *
 * 抽出来是为了能单测：分组、日期标签、类别元数据都有真实分支，
 * 而 DigestView 挂载成本高（要 mock API + authStore）。
 */
import type { DigestEntry, DigestKind } from '@/types/api'

/** 每种条目的图标与配色 class。顺序即前端展示优先级参考。 */
export const KIND_META: Record<DigestKind, { icon: string; label: string; tone: string }> = {
  world_event: { icon: '🌍', label: '世界事件', tone: 'tone-world' },
  npc_interaction: { icon: '👥', label: 'NPC 互动', tone: 'tone-npc' },
  gossip: { icon: '🗣️', label: '八卦', tone: 'tone-gossip' },
  world_impact: { icon: '🌊', label: '世界影响', tone: 'tone-impact' },
  story: { icon: '📖', label: '剧情', tone: 'tone-story' },
  dream: { icon: '🌙', label: '梦境', tone: 'tone-dream' },
  proactive: { icon: '💬', label: '主动消息', tone: 'tone-proactive' },
  milestone: { icon: '✨', label: '关系里程碑', tone: 'tone-milestone' },
  memory_event: { icon: '🧠', label: '记忆', tone: 'tone-memory' },
}

/** 未知 kind 的兜底（后端新增类别时前端不该崩，也不该显示空白） */
export const UNKNOWN_META = { icon: '•', label: '事件', tone: 'tone-default' }

export function kindMeta(kind: string) {
  return KIND_META[kind as DigestKind] ?? UNKNOWN_META
}

export interface DigestGroup {
  /** "2026-10-16" */
  date: string
  /** "今天" / "昨天" / "10月14日 周三" */
  label: string
  entries: DigestEntry[]
}

/**
 * 按日期分组，**组间最新的在前**。
 *
 * 依赖后端已经排好序（entries 是倒序的），这里只做相邻聚合 ——
 * 不重新排序，避免"后端排一次、前端再排一次"两套顺序逻辑不一致。
 */
export function groupByDate(entries: DigestEntry[], today: string): DigestGroup[] {
  const groups: DigestGroup[] = []
  for (const entry of entries) {
    const last = groups[groups.length - 1]
    if (last && last.date === entry.date) {
      last.entries.push(entry)
    } else {
      groups.push({ date: entry.date, label: dateLabel(entry.date, today), entries: [entry] })
    }
  }
  return groups
}

/** "今天" / "昨天" / "10月14日" */
export function dateLabel(date: string, today: string): string {
  if (date === today) return '今天'
  if (date === yesterdayOf(today)) return '昨天'
  const [, m, d] = date.split('-')
  if (!m || !d) return date
  return `${Number(m)}月${Number(d)}日`
}

/** 给定 "YYYY-MM-DD" 返回前一天。用 Date 做减法，避免手写月份进位。 */
export function yesterdayOf(date: string): string {
  const parts = date.split('-').map(Number)
  const [y, m, d] = parts
  if (!y || !m || !d) return ''
  const dt = new Date(y, m - 1, d)
  dt.setDate(dt.getDate() - 1)
  const mm = String(dt.getMonth() + 1).padStart(2, '0')
  const dd = String(dt.getDate()).padStart(2, '0')
  return `${dt.getFullYear()}-${mm}-${dd}`
}

/** "09:30" —— 只取时间部分。日期已经在分组标题里了。 */
export function timeOf(at: string): string {
  const idx = at.indexOf('T')
  return idx >= 0 ? at.slice(idx + 1, idx + 6) : at
}

/** 本地"今天"的 YYYY-MM-DD（不能用 toISOString，那是 UTC，会差一天） */
export function localToday(now: Date = new Date()): string {
  const mm = String(now.getMonth() + 1).padStart(2, '0')
  const dd = String(now.getDate()).padStart(2, '0')
  return `${now.getFullYear()}-${mm}-${dd}`
}

/**
 * 两个 "YYYY-MM-DD" 之间相差多少天（`to - from`）。解析不了返回 `null`。
 *
 * 用 `Date.UTC` 构造再相减 —— 直接 `new Date("2026-10-16")` 在部分环境按 UTC 解析，
 * 和本地时区混用会出现"差一天"。统一走 UTC 就与本地时区无关了。
 */
export function daysBetween(from: string, to: string): number | null {
  const a = parseYmd(from)
  const b = parseYmd(to)
  if (a === null || b === null) return null
  return Math.round((b - a) / 86400000)
}

function parseYmd(s: string): number | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s)
  if (!m) return null
  const y = Number(m[1])
  const mo = Number(m[2])
  const d = Number(m[3])
  if (!y || !mo || !d) return null
  return Date.UTC(y, mo - 1, d)
}
