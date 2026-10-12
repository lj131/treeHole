import { describe, it, expect, beforeEach } from 'vitest'
import {
  cleanTextForSpeech,
  truncateForSpeech,
  isReadAloudEnabled,
  setReadAloudEnabled,
} from '@/utils/readAloud'

describe('cleanTextForSpeech', () => {
  it('去掉 markdown 强调符号，别念出"星号"', () => {
    expect(cleanTextForSpeech('**你好**呀')).toBe('你好呀')
    expect(cleanTextForSpeech('这是*重点*')).toBe('这是重点')
  })

  it('去掉标题井号与列表符号', () => {
    expect(cleanTextForSpeech('## 标题')).toBe('标题')
    expect(cleanTextForSpeech('- 第一项')).toBe('第一项')
    expect(cleanTextForSpeech('1. 第一项')).toBe('第一项')
  })

  it('去掉行内代码反引号但保留内容', () => {
    expect(cleanTextForSpeech('运行 `npm test` 即可')).toBe('运行 npm test 即可')
  })

  it('代码块整体不念', () => {
    expect(cleanTextForSpeech('看这段：\n```js\nconst a = 1\n```\n就这些')).toBe('看这段： 就这些')
  })

  it('链接只保留可读文字，不念 URL', () => {
    expect(cleanTextForSpeech('见[文档](https://example.com/a/b)')).toBe('见文档')
  })

  it('图片整段不念', () => {
    expect(cleanTextForSpeech('看图 ![照片](https://x.com/a.png) 好看')).toBe('看图 好看')
  })

  it('表情符号不念', () => {
    expect(cleanTextForSpeech('好开心 😊🎉')).toBe('好开心')
  })

  it('压缩多余空白与换行', () => {
    expect(cleanTextForSpeech('第一行\n\n第二行   结束')).toBe('第一行 第二行 结束')
  })

  it('空输入返回空串，不抛异常', () => {
    expect(cleanTextForSpeech('')).toBe('')
    expect(cleanTextForSpeech('   ')).toBe('')
    expect(cleanTextForSpeech('***')).toBe('')
  })

  it('引用与分隔线不念', () => {
    expect(cleanTextForSpeech('> 引用一句')).toBe('引用一句')
    expect(cleanTextForSpeech('上面\n---\n下面')).toBe('上面 下面')
  })
})

describe('truncateForSpeech', () => {
  it('不超上限时原样返回', () => {
    expect(truncateForSpeech('短句', 10)).toBe('短句')
  })

  it('超上限时截断，并在句末收尾（半句话听起来像被打断）', () => {
    const out = truncateForSpeech('第一句。第二句。第三句。', 8)
    expect(out.length).toBeLessThanOrEqual(8)
    expect(out.endsWith('。')).toBe(true)
  })

  it('没有句读时硬截断', () => {
    expect(truncateForSpeech('啊'.repeat(20), 5)).toHaveLength(5)
  })

  it('默认上限与后端 MAX_SYNTH_CHARS 一致（600）', () => {
    const long = '字'.repeat(700)
    expect(truncateForSpeech(long)).toHaveLength(600)
  })
})

describe('朗读开关持久化', () => {
  beforeEach(() => localStorage.clear())

  it('默认关闭', () => {
    expect(isReadAloudEnabled()).toBe(false)
  })

  it('能存能读', () => {
    setReadAloudEnabled(true)
    expect(isReadAloudEnabled()).toBe(true)
    setReadAloudEnabled(false)
    expect(isReadAloudEnabled()).toBe(false)
  })
})
