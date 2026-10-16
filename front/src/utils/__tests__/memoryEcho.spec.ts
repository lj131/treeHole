import { describe, it, expect } from 'vitest'
import { echoText, collectionLabel } from '@/utils/memoryEcho'

describe('echoText', () => {
  it('空 → 空标签（前端据此不显示标记）', () => {
    expect(echoText(undefined).label).toBe('')
    expect(echoText([]).label).toBe('')
    expect(echoText(undefined).groups).toEqual([])
  })

  it('正常给出「参考了 N 条记忆」', () => {
    const t = echoText([{ text: '你喜欢喝美式', collection: 'long_memory' }])
    expect(t.label).toBe('参考了 1 条记忆')
    expect(t.groups).toHaveLength(1)
    expect(t.groups[0]!.label).toBe('关于你')
  })

  it('多条合并计数', () => {
    const t = echoText([
      { text: '你喜欢喝美式', collection: 'long_memory' },
      { text: '你讨厌开会', collection: 'long_memory' },
      { text: '关系从普通变成朋友', collection: 'events' },
    ])
    expect(t.label).toBe('参考了 3 条记忆')
    expect(t.groups).toHaveLength(2)
  })

  it('按 collection 分组且保持顺序', () => {
    const t = echoText([
      { text: '第一条关于你的', collection: 'long_memory' },
      { text: '一条事件', collection: 'events' },
      { text: '第二条关于你的', collection: 'long_memory' },
    ])
    expect(t.groups[0]!.label).toBe('关于你')
    expect(t.groups[0]!.items).toHaveLength(2)
    expect(t.groups[1]!.label).toBe('你们的事')
  })

  it('空文本被跳过（不凑数）', () => {
    const t = echoText([
      { text: '', collection: 'long_memory' },
      { text: '   ', collection: 'long_memory' },
      { text: '真的内容', collection: 'long_memory' },
    ])
    expect(t.label).toBe('参考了 1 条记忆')
  })

  it('全部为空文本 → 不显示标记', () => {
    expect(echoText([{ text: '', collection: 'long_memory' }]).label).toBe('')
  })

  it('未知 collection 也有兜底', () => {
    const t = echoText([{ text: '内容够长的一条', collection: 'brand_new' }])
    expect(t.groups[0]!.label).toBe('brand_new')
  })
})

describe('collectionLabel', () => {
  it('字段名翻成人话', () => {
    expect(collectionLabel('long_memory')).toBe('关于你')
    expect(collectionLabel('profile')).toBe('你的画像')
    expect(collectionLabel('events')).toBe('你们的事')
  })

  it('空值不显示空标题', () => {
    expect(collectionLabel('')).toBe('记忆')
  })
})
