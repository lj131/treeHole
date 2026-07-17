import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import StoryView from '@/views/StoryView.vue'

const getStoryMock = vi.fn()
const advanceStoryMock = vi.fn()

vi.mock('@/api', () => ({
  getStory: (...args: unknown[]) => getStoryMock(...args),
  advanceStory: (...args: unknown[]) => advanceStoryMock(...args),
}))

describe('StoryView', () => {
  beforeEach(() => {
    getStoryMock.mockReset()
    advanceStoryMock.mockReset()
  })

  it('挂载后调 getStory，加载完渲染进行中剧情的 StoryTree', async () => {
    getStoryMock.mockResolvedValue({
      stories: [
        { id: 's1', title: '主线A', type: 'main', status: 'active', stage: 0, stages: ['相遇'] },
      ],
      story_history: [],
      story: {},
    })
    const w = mount(StoryView)
    expect(w.text()).toContain('加载中')
    await flushPromises()
    expect(getStoryMock).toHaveBeenCalled()
    // 检查有进行中 section 且 StoryTree 被渲染
    expect(w.text()).toContain('进行中')
    expect(w.find('.story-tree').exists()).toBe(true)
  })

  it('加载失败显示 error 文案', async () => {
    getStoryMock.mockRejectedValue(new Error('网络错误'))
    const w = mount(StoryView)
    await flushPromises()
    expect(w.text()).toContain('网络错误')
  })

  it('无数据时显示空提示', async () => {
    getStoryMock.mockResolvedValue({ stories: [], story_history: [], story: {} })
    const w = mount(StoryView)
    await flushPromises()
    expect(w.text()).toContain('暂无剧情，多和角色聊聊吧')
  })

  it('已完结区列出 story_history 标题与阶段数', async () => {
    getStoryMock.mockResolvedValue({
      stories: [],
      story_history: [
        { id: 'h1', title: '旧主线', type: 'main', stages: ['a', 'b', 'c'], total_stages: 3 },
      ],
      story: {},
    })
    const w = mount(StoryView)
    await flushPromises()
    expect(w.text()).toContain('旧主线')
    expect(w.text()).toContain('3 阶段')
    expect(w.text()).toContain('已完结')
  })

  it('点推进按钮调 advanceStory 并刷新 getStory', async () => {
    getStoryMock.mockResolvedValue({
      stories: [
        { id: 's1', title: '主线A', type: 'main', status: 'active', stage: 0, stages: ['相遇', '初识'] },
      ],
      story_history: [],
      story: {},
    })
    advanceStoryMock.mockResolvedValue({ message: '已推进', story: {}, branch_created: false })
    const w = mount(StoryView)
    await flushPromises()
    getStoryMock.mockClear()
    await w.find('.advance-btn').trigger('click')
    await flushPromises()
    expect(advanceStoryMock).toHaveBeenCalledWith('s1')
    expect(getStoryMock).toHaveBeenCalled() // 刷新
  })
})
