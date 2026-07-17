import { request } from './request'
import type { Story, StoryHistoryItem } from '@/types/api'

export interface StoryBundle {
  stories: Story[]
  story_history: StoryHistoryItem[]
  story: Story
}

export interface AdvanceStoryResult {
  message: string
  story: Story
  branch_created: boolean
}

/** 获取当前所有剧情（主线 + 支线 + 历史归档） */
export const getStory = () => request<StoryBundle>('/story')

/** 手动推进指定剧情的当前阶段 */
export const advanceStory = (storyId: string) =>
  request<AdvanceStoryResult | { error: string }>('/story/advance', {
    method: 'POST',
    body: JSON.stringify({ story_id: storyId }),
  })
