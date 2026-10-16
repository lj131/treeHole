import { describe, it, expect } from 'vitest'
import { groupByDate, dateLabel, yesterdayOf, timeOf, localToday, kindMeta, daysBetween } from '@/utils/digest'
import type { DigestEntry } from '@/types/api'

function e(date: string, at: string, kind = 'world_event'): DigestEntry {
  return { at, date, kind: kind as DigestEntry['kind'], title: 't', detail: '', actors: [] }
}

/** 下标取元素：noUncheckedIndexedAccess 下 `arr[0]` 是 `T | undefined`，
 *  测试里到处写 `!` 或判空太吵，用这个收窄一次。 */
function at<T>(arr: T[], i: number): T {
  const v = arr[i]
  if (v === undefined) throw new Error(`索引 ${i} 越界（长度 ${arr.length}）`)
  return v
}

describe('groupByDate', () => {
  it('把相邻同日的条目聚成一组，组间保持传入顺序', () => {
    const groups = groupByDate(
      [
        e('2026-10-16', '2026-10-16T09:30'),
        e('2026-10-16', '2026-10-16T08:00'),
        e('2026-10-15', '2026-10-15T21:00'),
      ],
      '2026-10-16',
    )
    expect(groups).toHaveLength(2)
    expect(at(groups, 0).date).toBe('2026-10-16')
    expect(at(groups, 0).entries).toHaveLength(2)
    expect(at(groups, 1).date).toBe('2026-10-15')
  })

  it('同一天的多条保持传入顺序（不重新排序，信任后端）', () => {
    const groups = groupByDate(
      [e('2026-10-16', '2026-10-16T09:30'), e('2026-10-16', '2026-10-16T08:00')],
      '2026-10-16',
    )
    expect(at(groups, 0).entries.map((x) => x.at)).toEqual([
      '2026-10-16T09:30',
      '2026-10-16T08:00',
    ])
  })

  it('空列表 → 空分组', () => {
    expect(groupByDate([], '2026-10-16')).toEqual([])
  })
})

describe('dateLabel', () => {
  it('今天 / 昨天 / 更早', () => {
    expect(dateLabel('2026-10-16', '2026-10-16')).toBe('今天')
    expect(dateLabel('2026-10-15', '2026-10-16')).toBe('昨天')
    expect(dateLabel('2026-10-14', '2026-10-16')).toBe('10月14日')
  })

  it('跨月时"昨天"要正确（10-01 的昨天是 09-30）', () => {
    expect(yesterdayOf('2026-10-01')).toBe('2026-09-30')
    expect(dateLabel('2026-09-30', '2026-10-01')).toBe('昨天')
  })

  it('跨年时"昨天"要正确', () => {
    expect(yesterdayOf('2026-01-01')).toBe('2025-12-31')
  })

  it('闰年 3-01 的昨天是 2-29', () => {
    expect(yesterdayOf('2028-03-01')).toBe('2028-02-29')
  })

  it('非法日期不崩', () => {
    expect(yesterdayOf('bad')).toBe('')
    expect(dateLabel('bad', '2026-10-16')).toBe('bad')
  })
})

describe('timeOf', () => {
  it('取 HH:MM', () => {
    expect(timeOf('2026-10-16T09:30')).toBe('09:30')
    expect(timeOf('2026-10-16T09:30:45')).toBe('09:30')
  })

  it('没有 T 时原样返回（不崩）', () => {
    expect(timeOf('2026-10-16')).toBe('2026-10-16')
  })
})

describe('localToday', () => {
  it('用本地时间而不是 UTC（否则晚上会差一天）', () => {
    // 本地时间 2026-10-16 23:30，UTC 可能已经是 17 号
    expect(localToday(new Date(2026, 9, 16, 23, 30))).toBe('2026-10-16')
    expect(localToday(new Date(2026, 0, 1, 0, 5))).toBe('2026-01-01')
  })
})

describe('kindMeta', () => {
  it('已知 kind 返回图标与标签', () => {
    expect(kindMeta('dream').icon).toBe('🌙')
    expect(kindMeta('milestone').label).toBe('关系里程碑')
  })

  it('**未知 kind 有兜底** —— 后端加新类别时前端不该崩或留白', () => {
    expect(kindMeta('brand_new_kind').icon).toBe('•')
    expect(kindMeta('brand_new_kind').label).toBe('事件')
  })
})


describe('daysBetween', () => {
  it('同一天 = 0', () => {
    expect(daysBetween('2026-10-16', '2026-10-16')).toBe(0)
  })

  it('普通跨天', () => {
    expect(daysBetween('2026-10-12', '2026-10-16')).toBe(4)
  })

  it('跨月', () => {
    expect(daysBetween('2026-09-30', '2026-10-02')).toBe(2)
  })

  it('跨年', () => {
    expect(daysBetween('2025-12-31', '2026-01-01')).toBe(1)
  })

  it('闰年 2-29 存在（2028 是闰年）', () => {
    expect(daysBetween('2028-02-28', '2028-03-01')).toBe(2)
  })

  it('平年 2-29 不存在时也能算', () => {
    // 2026 不是闰年，2-28 → 3-01 是 1 天
    expect(daysBetween('2026-02-28', '2026-03-01')).toBe(1)
  })

  it('**不受本地时区影响**（UTC 构造，跨夏令时也不会差一天）', () => {
    expect(daysBetween('2026-03-07', '2026-03-09')).toBe(2)
    expect(daysBetween('2026-11-01', '2026-11-03')).toBe(2)
  })

  it('反向为负', () => {
    expect(daysBetween('2026-10-16', '2026-10-12')).toBe(-4)
  })

  it('非法输入返回 null（不崩）', () => {
    expect(daysBetween('bad', '2026-10-16')).toBeNull()
    expect(daysBetween('2026-10-16', '')).toBeNull()
    expect(daysBetween('2026/10/16', '2026-10-16')).toBeNull()
  })
})
