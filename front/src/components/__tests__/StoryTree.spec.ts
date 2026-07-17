import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import StoryTree from '@/components/StoryTree.vue'
import type { Story } from '@/types/api'

const baseStory: Story = {
  id: 's1',
  title: '林婉的心结',
  type: 'main',
  status: 'active',
  stage: 2,
  stages: ['相遇', '初识', '动摇', '当前阶段', '结局'],
  branch_points: [
    { stage: 1, reason: '好感破80', alt_direction: '冷淡收场', favorability: 82 },
  ],
}

describe('StoryTree', () => {
  it('渲染所有阶段标签', () => {
    const w = mount(StoryTree, { props: { story: baseStory } })
    expect(w.findAll('.node-label').map((n) => n.text())).toEqual([
      '相遇', '初识', '动摇', '当前阶段', '结局',
    ])
  })

  it('当前阶段(stage=2)标 current，之前 done，之后 future', () => {
    const w = mount(StoryTree, { props: { story: baseStory } })
    const nodes = w.findAll('.stage-node')
    expect(nodes[0]!.classes()).toContain('done')
    expect(nodes[2]!.classes()).toContain('current')
    expect(nodes[3]!.classes()).toContain('future')
  })

  it('仅当前阶段显示一个"当前"标签', () => {
    const w = mount(StoryTree, { props: { story: baseStory } })
    expect(w.findAll('.current-tag').length).toBe(1)
  })

  it('分支点渲染为侧枝，含 alt_direction / reason / 好感', () => {
    const w = mount(StoryTree, { props: { story: baseStory } })
    const branches = w.findAll('.branch-node')
    expect(branches.length).toBe(1)
    const txt = branches[0]!.text()
    expect(txt).toContain('冷淡收场')
    expect(txt).toContain('好感破80')
    expect(txt).toContain('好感82')
  })

  it('分支侧枝挂在对应 stage 行下', () => {
    const w = mount(StoryTree, { props: { story: baseStory } })
    const rows = w.findAll('.stage-row')
    expect(rows[1]!.findAll('.branch-node').length).toBe(1)
    expect(rows[0]!.findAll('.branch-node').length).toBe(0)
  })

  it('主线/支线 badge 与状态 badge 正确', () => {
    const w = mount(StoryTree, { props: { story: baseStory } })
    expect(w.find('.story-type-badge').classes()).toContain('type-main')
    expect(w.find('.story-status-badge').text()).toBe('进行中')
  })

  it('completed 状态：全 done、无"当前"标签、状态显示"已完结"', () => {
    const w = mount(StoryTree, {
      props: { story: { ...baseStory, status: 'completed', stage: 4 } },
    })
    expect(w.findAll('.current-tag').length).toBe(0)
    expect(w.find('.story-status-badge').text()).toBe('已完结')
  })

  it('stages 为空时显示"暂无阶段"', () => {
    const w = mount(StoryTree, {
      props: { story: { id: 's', title: '空', stages: [] } },
    })
    expect(w.text()).toContain('暂无阶段')
  })

  it('stage 超出 stages 长度时，多余未来阶段显示"未解锁"', () => {
    const w = mount(StoryTree, {
      props: { story: { id: 's', title: 't', stage: 2, stages: ['相遇', '初识'] } },
    })
    expect(w.findAll('.node-label').map((n) => n.text())).toEqual(['相遇', '初识', '未解锁'])
  })
})
