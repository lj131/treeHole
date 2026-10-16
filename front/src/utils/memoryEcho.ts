/**
 * 记忆回响的文案（纯函数）。
 *
 * ⚠️ 措辞是**设计决策**不是文案：不说"她想起了你说过 XX" ——
 * 召回 ≠ 使用（注入 prompt 不等于模型采纳了它）。
 * 一旦用户发现"她说想起了 X 但我根本没说过 X"，信任就没了。
 * **诚实 > 煽情。**
 */
import type { MemoryEcho } from '@/types/api'

export interface MemoryEchoText {
  /** 标记上的短文案，如「参考了 3 条记忆」；空串 = 不显示标记 */
  label: string
  /** 展开后的分组标题 */
  groups: { collection: string; label: string; items: string[] }[]
}

/** collection → 人话（用户不该看到 "long_memory" 这种字段名） */
const COLLECTION_LABELS: Record<string, string> = {
  long_memory: '关于你',
  profile: '你的画像',
  events: '你们的事',
}

export function collectionLabel(collection: string): string {
  return COLLECTION_LABELS[collection] || collection || '记忆'
}

export function echoText(echoes: MemoryEcho[] | undefined): MemoryEchoText {
  if (!echoes || echoes.length === 0) {
    return { label: '', groups: [] }
  }

  // 按 collection 分组（保持后端给的顺序 = 相关度顺序）
  const byCollection = new Map<string, string[]>()
  for (const e of echoes) {
    const text = (e.text || '').trim()
    if (!text) continue
    const list = byCollection.get(e.collection)
    if (list) list.push(text)
    else byCollection.set(e.collection, [text])
  }

  const groups = [...byCollection.entries()].map(([collection, items]) => ({
    collection,
    label: collectionLabel(collection),
    items,
  }))

  const total = groups.reduce((sum, g) => sum + g.items.length, 0)
  return { label: total > 0 ? `参考了 ${total} 条记忆` : '', groups }
}
