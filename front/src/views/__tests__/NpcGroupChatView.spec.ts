import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import NpcGroupChatView from '@/views/NpcGroupChatView.vue'

const getInteractionsMock = vi.fn<(...args: unknown[]) => unknown>()
const simulateMock = vi.fn<(...args: unknown[]) => unknown>()

vi.mock('@/api', () => ({
  getWorldInteractions: (...args: unknown[]) => getInteractionsMock(...args),
  simulateWorldInteraction: (...args: unknown[]) => simulateMock(...args),
}))

function makeSnapshot() {
  return {
    world_id: 'campus',
    characters: { linwan: '林婉', xiaoyu: '小羽' },
    relationships: {
      linwan: { xiaoyu: { favorability: 70, trust: 60, intimacy: 45 } },
    },
    recent_interactions: [
      {
        time: '2026-10-14 20:00',
        summary: '两人在图书馆吵了一架',
        dialogues: [
          { speaker: 'linwan', content: '你凭什么替她说话？' },
          { speaker: 'xiaoyu', content: '我只是在陈述事实。' },
        ],
        world_impact: '筹备委员会气氛变僵',
        event_id: 'e1',
      },
    ],
    gossip: [{ time: '2026-10-14 21:00', source: 'xiaoyu', target: 'linwan', content: '她把名额标准问出来了' }],
    world_impacts: [],
    last_interaction_date: '2026-10-14',
  }
}

describe('NpcGroupChatView', () => {
  beforeEach(() => {
    getInteractionsMock.mockReset()
    simulateMock.mockReset()
    getInteractionsMock.mockResolvedValue(makeSnapshot())
  })

  it('挂载后拉取快照，并把对话渲染成气泡（speaker 解析成名字）', async () => {
    const w = mount(NpcGroupChatView)
    await flushPromises()

    expect(getInteractionsMock).toHaveBeenCalledTimes(1)

    const bubbles = w.findAll('.bubble')
    expect(bubbles).toHaveLength(2)
    // findAll 的下标在严格模式下是可能 undefined 的，先收窄再用
    const [first, second] = bubbles
    expect(first).toBeDefined()
    expect(second).toBeDefined()
    if (!first || !second) return

    expect(first.find('.speaker').text()).toBe('林婉')
    expect(first.find('.content').text()).toContain('你凭什么替她说话')
    expect(second.find('.speaker').text()).toBe('小羽')

    // 摘要和世界影响也要在
    expect(w.find('.session-summary').text()).toContain('图书馆吵了一架')
    expect(w.find('.impact').text()).toContain('气氛变僵')
  })

  it('关系条渲染三条数值，八卦渲染 source→target', async () => {
    const w = mount(NpcGroupChatView)
    await flushPromises()

    expect(w.findAll('.rel-card')).toHaveLength(1)
    expect(w.find('.rel-names').text()).toContain('林婉')
    expect(w.find('.rel-names').text()).toContain('小羽')
    expect(w.findAll('.rel-stat')).toHaveLength(3)

    const gossip = w.find('.gossip-item')
    expect(gossip.text()).toContain('小羽')
    expect(gossip.text()).toContain('林婉')
    expect(gossip.text()).toContain('名额标准')
  })

  it('点「触发一场群聊」→ 调 simulate，成功后重新拉快照', async () => {
    simulateMock.mockResolvedValue({ action: 'simulated' })
    const w = mount(NpcGroupChatView)
    await flushPromises()
    expect(getInteractionsMock).toHaveBeenCalledTimes(1)

    await w.find('.head-actions .btn').trigger('click')
    await flushPromises()

    expect(simulateMock).toHaveBeenCalledTimes(1)
    expect(getInteractionsMock).toHaveBeenCalledTimes(2)   // 模拟后刷新
    expect(w.find('.msg-line').text()).toContain('已模拟')
  })

  it('模拟被后端拒绝（skipped）时给原因，不报错样式', async () => {
    simulateMock.mockResolvedValue({ action: 'skipped', reason: '今天已模拟过' })
    const w = mount(NpcGroupChatView)
    await flushPromises()

    await w.find('.head-actions .btn').trigger('click')
    await flushPromises()

    const msg = w.find('.msg-line')
    expect(msg.text()).toContain('今天已模拟过')
    expect(msg.classes()).toContain('ok')
  })

  it('空快照 → 显示引导文案，不崩', async () => {
    getInteractionsMock.mockResolvedValue({})
    const w = mount(NpcGroupChatView)
    await flushPromises()

    expect(w.findAll('.session')).toHaveLength(0)
    // 群聊区与关系区各有自己的空态文案
    const hints = w.findAll('.empty-hint').map((n) => n.text())
    expect(hints.some((t) => t.includes('还没有群聊记录'))).toBe(true)
    expect(hints.some((t) => t.includes('暂无关系数据'))).toBe(true)
  })

  it('加载失败 → 显示错误信息（不白屏）', async () => {
    getInteractionsMock.mockRejectedValue(new Error('网络炸了'))
    const w = mount(NpcGroupChatView)
    await flushPromises()

    const msg = w.find('.msg-line')
    expect(msg.classes()).toContain('err')
    expect(msg.text()).toContain('网络炸了')
  })
})
