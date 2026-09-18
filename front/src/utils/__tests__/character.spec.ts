import { describe, it, expect } from 'vitest'
import {
  getCharacterInitial,
  getMoodEmoji,
  getEnergyColor,
  formatCurrentEvent,
} from '@/utils/character'

describe('formatCurrentEvent 当前事件归一化', () => {
  it('字符串形态原样返回（去掉首尾空格）', () => {
    expect(formatCurrentEvent('  她在雨里等你  ')).toEqual({
      title: '她在雨里等你',
      description: '',
    })
  })

  it('对象形态取 title / description', () => {
    expect(
      formatCurrentEvent({
        title: '深夜的便利店',
        description: '她买了两罐热咖啡',
        event_date: '2026-09-18',
        impact: -20,
      }),
    ).toEqual({ title: '深夜的便利店', description: '她买了两罐热咖啡' })
  })

  it('空对象不会产生脏字符串（关键：不能渲染成原始 JSON）', () => {
    const r = formatCurrentEvent({})
    expect(r.title).toBe('')
    expect(r.description).toBe('')
    // 模板里用 r.title || r.description 做 v-if，两个都空才会隐藏
    expect(r.title || r.description).toBeFalsy()
  })

  it('只有 description 时也能拿到文本', () => {
    expect(formatCurrentEvent({ description: '窗外在下雨' })).toEqual({
      title: '',
      description: '窗外在下雨',
    })
  })

  it('null / undefined 返回空，不抛异常', () => {
    expect(formatCurrentEvent(null)).toEqual({ title: '', description: '' })
    expect(formatCurrentEvent(undefined)).toEqual({ title: '', description: '' })
  })

  it('任何形态的返回值都是字符串（防止对象漏进模板）', () => {
    for (const input of ['x', {}, { title: 'a' }, null, undefined] as const) {
      const r = formatCurrentEvent(input)
      expect(typeof r.title).toBe('string')
      expect(typeof r.description).toBe('string')
    }
  })
})

describe('character 基础工具', () => {
  it('无名字时首字母回退为 ?', () => {
    expect(getCharacterInitial('')).toBe('?')
  })

  it('未知心情有兜底 emoji', () => {
    expect(getMoodEmoji('暴走')).toBe('💭')
    expect(getMoodEmoji(undefined)).toBe('💭')
  })

  it('精力分档取色', () => {
    expect(getEnergyColor(90)).toBe('#57ff93')
    expect(getEnergyColor(50)).toBe('#ffd93d')
    expect(getEnergyColor(10)).toBe('#ff6b6b')
  })
})
