import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/api/request', () => ({
  request: vi.fn(),
}))

import { request } from '@/api/request'
import { getStory, advanceStory } from '@/api/story'

describe('story API client', () => {
  beforeEach(() => vi.clearAllMocks())

  it('getStory 发 GET /story', async () => {
    vi.mocked(request).mockResolvedValue({ stories: [], story_history: [], story: {} })
    await getStory()
    expect(request).toHaveBeenCalledWith('/story')
  })

  it('advanceStory 发 POST /story/advance 带 story_id', async () => {
    vi.mocked(request).mockResolvedValue({ message: '已推进', story: {}, branch_created: false })
    await advanceStory('s1')
    expect(request).toHaveBeenCalledWith('/story/advance', {
      method: 'POST',
      body: JSON.stringify({ story_id: 's1' }),
    })
  })
})
