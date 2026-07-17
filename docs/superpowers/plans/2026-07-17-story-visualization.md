# 剧情可视化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增独立路由页 `/story`，以树状图可视化多剧情系统：主线脊柱（stages 各阶段）+ 在分支存档点处长出的侧枝（alt_direction 备选方向），含进行中/已完结分区。

**Architecture:** 纯前端新增，零后端改动（复用已有 `GET /story` / `POST /story/advance`）。数据模型澄清：`Story.stages[]` 是角色实际走过的线性主线；`Story.branch_points[]` 是各阶段的"备选方向存档"（`alt_direction` = 没走的那条路）。所以"树"= 垂直主线脊柱 + 在有分支点的阶段处长出的侧枝节点。用纯 CSS 实现树形（脊柱竖线 + 阶段圆点 + 侧枝缩进），不引入图布局库。组件化：`StoryTree.vue`（单剧情树）被 `StoryView.vue`（页面，加载 + 列出 active 树 + 已完结区）复用。

**Tech Stack:** Vue 3 `<script setup>` + TypeScript、Pinia 不需要（页面用 local refs）、vitest + jsdom + @vue/test-utils（TDD）、vue-router hash 路由。

---

## 前置基线（已验证 GREEN）

- 前端 `vue-tsc --build --force`：exit 0
- 前端 `vitest run`：`Test Files 2 passed (2)` / `Tests 4 passed (4)`
- 后端 `GET /story` 已存在（`api.py:982`），返回 `{stories, story_history, story}`
- 后端 `POST /story/advance` 已存在（`api.py:1005`），body `{story_id}`，返回 `{message, story, branch_created}` 或 `{error}`（HTTP 200）

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `front/src/api/story.ts` | 新建 | getStory / advanceStory 两个 API 函数（薄封装 request） |
| `front/src/api/index.ts` | 修改 | `export * from './story'` |
| `front/src/components/StoryTree.vue` | 新建 | 单剧情树可视化（主线脊柱 + 分支侧枝 + 状态/类型 badge） |
| `front/src/components/__tests__/StoryTree.spec.ts` | 新建 | StoryTree 渲染逻辑单测（TDD） |
| `front/src/views/StoryView.vue` | 新建 | /story 页面：加载剧情、列 active 树、已完结区、推进按钮 |
| `front/src/views/__tests__/StoryView.spec.ts` | 新建 | StoryView 加载/渲染/交互单测（TDD） |
| `front/src/api/__tests__/story.spec.ts` | 新建 | story API 客户端单测（TDD） |
| `front/src/router/index.ts` | 修改 | 新增 `/story` 路由 |
| `front/src/App.vue` | 修改 | 导航栏加"剧情"链接 |
| `front/CLAUDE.md` | 修改 | 文档同步新路由/视图/组件/API 模块（Working Agreement） |

**YAGNI 排除**：不实现 `branchStory`（手动建分支存档点）API 客户端 -- 可视化只读展示已有 `branch_points`，创建分支是另一个需求，暂不做。`storyStore` 也不建 -- 单页面用 local refs 足够。

---

## Task 1: story API 客户端（TDD）

**Files:**
- Create: `front/src/api/story.ts`
- Create: `front/src/api/__tests__/story.spec.ts`
- Modify: `front/src/api/index.ts`

- [ ] **Step 1: 写失败测试 `front/src/api/__tests__/story.spec.ts`**

```typescript
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
```

- [ ] **Step 2: 跑测试，确认 FAIL**

```bash
cd D:/amyproject/front
npx vitest run src/api/__tests__/story.spec.ts 2>&1 | tail -20
```

Expected: FAIL，原因含 `Failed to resolve import "@/api/story"` 或 `getStory is not a function`（模块不存在）。

- [ ] **Step 3: 实现 `front/src/api/story.ts`**

```typescript
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
```

> 注：`story.ts` 用 `from './request'`（与 `api/` 目录其它文件一致）。测试里 `vi.mock('@/api/request')` 经别名解析到同一文件，能拦截。

- [ ] **Step 4: 在 `front/src/api/index.ts` 末尾加一行导出**

把：
```typescript
export * from './auth'
```
改成：
```typescript
export * from './auth'
export * from './story'
```

- [ ] **Step 5: 跑测试，确认 GREEN**

```bash
cd D:/amyproject/front
npx vitest run src/api/__tests__/story.spec.ts 2>&1 | tail -10
```

Expected: `Test Files 1 passed` / `Tests 2 passed`。

- [ ] **Step 6: type-check 确认无类型错误**

```bash
cd D:/amyproject/front
node_modules/.bin/vue-tsc --build --force; echo "EXIT:$?"
```

Expected: `EXIT:0`。

- [ ] **Step 7: Commit**

```bash
cd D:/amyproject
git add front/src/api/story.ts front/src/api/index.ts front/src/api/__tests__/story.spec.ts
git commit -m "feat(front): 新增 story API 客户端 getStory/advanceStory

TDD：先写 story.spec.ts 看它 FAIL，再实现 story.ts。复用已有后端 /story 接口。
Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: StoryTree 组件（TDD 核心）

**Files:**
- Create: `front/src/components/StoryTree.vue`
- Create: `front/src/components/__tests__/StoryTree.spec.ts`

**渲染规约**：
- 阶段节点（主线脊柱）：每个 `stages[i]` 一个圆点 + 标签。`i < stage` => done（●）；`i === stage` 且非 completed => current（◉）+ "当前"标签；`i > stage` => future（○）；completed 状态全 done 且无"当前"标签。
- 未来未解锁阶段（`stage >= stages.length`）显示"未解锁"。
- 分支侧枝：`branch_points` 按 `stage` 分组，挂在该阶段行下，显示 alt_direction / reason / 好感。
- 头部：类型 badge（主线/支线）、标题、状态 badge（进行中/暂停/已完结）、进度 `stage+1 / total`。
- `stages` 为空 => "暂无阶段"。

- [ ] **Step 1: 写失败测试 `front/src/components/__tests__/StoryTree.spec.ts`**

```typescript
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
    expect(nodes[0].classes()).toContain('done')
    expect(nodes[2].classes()).toContain('current')
    expect(nodes[3].classes()).toContain('future')
  })

  it('仅当前阶段显示一个"当前"标签', () => {
    const w = mount(StoryTree, { props: { story: baseStory } })
    expect(w.findAll('.current-tag').length).toBe(1)
  })

  it('分支点渲染为侧枝，含 alt_direction / reason / 好感', () => {
    const w = mount(StoryTree, { props: { story: baseStory } })
    const branches = w.findAll('.branch-node')
    expect(branches.length).toBe(1)
    const txt = branches[0].text()
    expect(txt).toContain('冷淡收场')
    expect(txt).toContain('好感破80')
    expect(txt).toContain('好感82')
  })

  it('分支侧枝挂在对应 stage 行下', () => {
    const w = mount(StoryTree, { props: { story: baseStory } })
    const rows = w.findAll('.stage-row')
    expect(rows[1].findAll('.branch-node').length).toBe(1)
    expect(rows[0].findAll('.branch-node').length).toBe(0)
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
```

> **注（实测 2026-07-17）**：`tsconfig.app.json` 开了 `noUncheckedIndexedAccess`，测试文件也覆盖。spec 里 6 处数组下标访问（`nodes[0]`/`nodes[2]`/`nodes[3]`/`branches[0]`/`rows[1]`/`rows[0]`）需加非空断言 `!`（如 `nodes[0]!.classes()`），否则 vue-tsc 报 TS2532。实际提交的 spec 已带 `!`。Task 3 的 StoryView spec 未做下标访问，不受影响。

- [ ] **Step 2: 跑测试，确认 FAIL**

```bash
cd D:/amyproject/front
npx vitest run src/components/__tests__/StoryTree.spec.ts 2>&1 | tail -20
```

Expected: FAIL，`Failed to resolve import "@/components/StoryTree.vue"`。

- [ ] **Step 3: 实现 `front/src/components/StoryTree.vue`**

```vue
<template>
  <div class="story-tree" :class="`status-${status}`">
    <div class="story-tree-head">
      <span class="story-type-badge" :class="'type-' + (story.type || 'main')">
        {{ story.type === 'side' ? '支线' : '主线' }}
      </span>
      <b class="story-title">{{ story.title || '未命名剧情' }}</b>
      <span class="story-status-badge" :class="'status-' + status">{{ statusLabel }}</span>
      <span class="story-progress">{{ currentStage + 1 }} / {{ totalStages }} 阶段</span>
    </div>
    <p v-if="story.description" class="story-desc">{{ story.description }}</p>

    <div v-if="totalStages > 0 || currentStage > 0" class="stage-spine">
      <div v-for="(label, i) in stageNodes" :key="i" class="stage-row">
        <div class="stage-node" :class="stageClass(i)">
          <span class="node-dot">{{ dotSymbol(i) }}</span>
          <span class="node-label">{{ label }}</span>
          <span v-if="i === currentStage && !isCompleted" class="node-tag current-tag">当前</span>
        </div>
        <div
          v-for="(bp, j) in branchesAt(i)"
          :key="j"
          class="branch-node"
        >
          <span class="branch-pin">📌</span>
          <span class="branch-alt">{{ bp.alt_direction || '备选方向' }}</span>
          <span v-if="bp.reason" class="branch-reason">{{ bp.reason }}</span>
          <span v-if="bp.favorability != null" class="branch-fav">好感{{ bp.favorability }}</span>
        </div>
      </div>
    </div>
    <div v-else class="empty-hint">暂无阶段</div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { Story } from '@/types/api'

const props = defineProps<{ story: Story }>()

const status = computed(() => props.story.status || 'active')
const statusLabel = computed(
  () =>
    ({ active: '进行中', paused: '暂停', completed: '已完结' } as Record<string, string>)[
      status.value
    ] || '进行中',
)

const stages = computed(() => props.story.stages ?? [])
const totalStages = computed(() => stages.value.length)
const currentStage = computed(() => props.story.stage ?? 0)
const isCompleted = computed(() => status.value === 'completed')

// 阶段节点数组：长度取 max(stages 长度, currentStage+1)，超出部分补"未解锁"
const stageNodes = computed(() => {
  const n = Math.max(totalStages.value, currentStage.value + 1)
  const arr: string[] = []
  for (let i = 0; i < n; i++) arr.push(stages.value[i] || '未解锁')
  return arr
})

function stageClass(i: number): string {
  if (isCompleted.value) return 'done'
  if (i < currentStage.value) return 'done'
  if (i === currentStage.value) return 'current'
  return 'future'
}

function dotSymbol(i: number): string {
  const c = stageClass(i)
  if (c === 'done') return '●'
  if (c === 'current') return '◉'
  return '○'
}

function branchesAt(i: number) {
  return (props.story.branch_points ?? []).filter((bp) => (bp.stage ?? 0) === i)
}
</script>

<style scoped>
.story-tree {
  background: var(--bg-secondary, #1e1e2e);
  border: 1px solid var(--border-color, #33334a);
  border-radius: 12px;
  padding: 16px;
  margin-bottom: 16px;
}
.story-tree-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
.story-title {
  font-size: 1.05rem;
  color: var(--text-primary, #e4e4e7);
}
.story-progress {
  margin-left: auto;
  color: var(--text-secondary, #a0a0b8);
  font-size: 0.85rem;
}
.story-desc {
  color: var(--text-secondary, #a0a0b8);
  font-size: 0.9rem;
  margin: 0 0 12px;
}
.story-type-badge,
.story-status-badge {
  font-size: 0.75rem;
  padding: 2px 8px;
  border-radius: 8px;
}
.story-type-badge.type-main {
  background: rgba(102, 126, 234, 0.2);
  color: #93a4ff;
}
.story-type-badge.type-side {
  background: rgba(52, 211, 153, 0.2);
  color: #6ee7b7;
}
.story-status-badge.status-active {
  background: rgba(52, 211, 153, 0.15);
  color: #6ee7b7;
}
.story-status-badge.status-paused {
  background: rgba(251, 191, 36, 0.15);
  color: #fcd34d;
}
.story-status-badge.status-completed {
  background: rgba(148, 163, 184, 0.15);
  color: #cbd5e1;
}
.stage-spine {
  margin-top: 8px;
}
.stage-row {
  position: relative;
  padding-left: 20px;
}
.stage-row:not(:last-child) {
  border-left: 2px solid var(--border-color, #33334a);
  margin-left: 5px;
  padding-bottom: 14px;
}
.stage-node {
  display: flex;
  align-items: center;
  gap: 8px;
  position: relative;
  left: -15px;
  background: var(--bg-secondary, #1e1e2e);
  padding-right: 6px;
}
.node-dot {
  width: 14px;
  text-align: center;
}
.stage-node.done .node-dot {
  color: #6ee7b7;
}
.stage-node.current .node-dot {
  color: #93a4ff;
}
.stage-node.future .node-dot {
  color: var(--text-secondary, #6b6b80);
}
.node-label {
  color: var(--text-primary, #e4e4e7);
}
.stage-node.future .node-label {
  color: var(--text-secondary, #6b6b80);
}
.current-tag {
  font-size: 0.7rem;
  background: rgba(102, 126, 234, 0.2);
  color: #93a4ff;
  padding: 1px 6px;
  border-radius: 6px;
}
.branch-node {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin: 6px 0 6px 16px;
  padding: 6px 10px;
  background: rgba(251, 191, 36, 0.08);
  border-left: 3px solid #fcd34d;
  border-radius: 0 6px 6px 0;
  font-size: 0.82rem;
}
.branch-alt {
  color: #fcd34d;
}
.branch-reason {
  color: var(--text-secondary, #a0a0b8);
}
.branch-fav {
  color: #f0abfc;
  font-size: 0.75rem;
}
.empty-hint {
  color: var(--text-secondary, #6b6b80);
  padding: 12px 0;
}
</style>
```

- [ ] **Step 4: 跑测试，确认 GREEN**

```bash
cd D:/amyproject/front
npx vitest run src/components/__tests__/StoryTree.spec.ts 2>&1 | tail -15
```

Expected: `Test Files 1 passed` / `Tests 9 passed`。若有失败，看哪条断言、修组件（不要改测试去迁就错误实现）。

- [ ] **Step 5: type-check**

```bash
cd D:/amyproject/front
node_modules/.bin/vue-tsc --build --force; echo "EXIT:$?"
```

Expected: `EXIT:0`。

- [ ] **Step 6: Commit**

```bash
cd D:/amyproject
git add front/src/components/StoryTree.vue front/src/components/__tests__/StoryTree.spec.ts
git commit -m "feat(front): StoryTree 剧情树状图组件（主线脊柱+分支侧枝）

TDD：9 条渲染断言先 FAIL 再实现。主线 stages 为脊柱，branch_points 在对应阶段
长出 alt_direction 侧枝。纯 CSS 实现，不引入图布局库。
Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: StoryView 页面（TDD）

**Files:**
- Create: `front/src/views/StoryView.vue`
- Create: `front/src/views/__tests__/StoryView.spec.ts`

**页面规约**：
- onMounted 调 `getStory()` 加载；loading 中显示"加载中..."；出错显示 error；空数据显示"暂无剧情，多和角色聊聊吧"。
- 进行中（status=active）剧情：按主线优先排序，每个渲染一个 `<StoryTree>`，带"推进"按钮（调 `advanceStory(id)`，成功后重新 `getStory` 刷新；返回 `{error}` 时把 error 文案展示）。
- 已完结区：列出 `story_history`，每条显示类型 badge + 标题 + 阶段数。
- 推进中禁用按钮，防止重复点。

- [ ] **Step 1: 写失败测试 `front/src/views/__tests__/StoryView.spec.ts`**

```typescript
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
    expect(w.findAllComponents({ name: 'StoryTree' }).length).toBe(1)
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
    expect(w.text()).toContain('暂无剧情')
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
```

> 注：`findAllComponents({ name: 'StoryTree' })` 依赖组件名。`<script setup>` 组件名取文件名 `StoryTree`，需在 StoryView 里 `import StoryTree from '@/components/StoryTree.vue'`。若 name 解析不到，改用 `findAllComponents(StoryTree)`（import 进测试）。

- [ ] **Step 2: 跑测试，确认 FAIL**

```bash
cd D:/amyproject/front
npx vitest run src/views/__tests__/StoryView.spec.ts 2>&1 | tail -20
```

Expected: FAIL，`Failed to resolve import "@/views/StoryView.vue"`。

- [ ] **Step 3: 实现 `front/src/views/StoryView.vue`**

```vue
<template>
  <div class="story-page">
    <header class="page-head">
      <h2>📖 剧情可视化</h2>
      <button class="btn" :disabled="loading" @click="load">刷新</button>
    </header>

    <div v-if="loading && !stories.length" class="loading-hint">加载中...</div>
    <div v-else-if="error" class="error-hint">{{ error }}</div>
    <div
      v-else-if="!activeStories.length && !history.length"
      class="empty-hint"
    >
      暂无剧情，多和角色聊聊吧
    </div>
    <template v-else>
      <section v-if="activeStories.length" class="story-section">
        <h3>进行中</h3>
        <div v-for="s in activeStories" :key="s.id" class="story-item">
          <StoryTree :story="s" />
          <button
            class="btn sm advance-btn"
            :disabled="advancingId === s.id"
            @click="advance(s.id!)"
          >
            {{ advancingId === s.id ? '推进中…' : '推进剧情' }}
          </button>
        </div>
      </section>

      <section v-if="history.length" class="story-section">
        <h3>已完结</h3>
        <div v-for="h in history" :key="h.id" class="history-card">
          <span class="story-type-badge" :class="'type-' + (h.type || 'main')">
            {{ h.type === 'side' ? '支线' : '主线' }}
          </span>
          <b>{{ h.title || '未命名' }}</b>
          <span class="history-stages">{{ h.stages?.length ?? 0 }} 阶段</span>
        </div>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { getStory, advanceStory } from '@/api'
import type { Story, StoryHistoryItem } from '@/types/api'
import StoryTree from '@/components/StoryTree.vue'

const stories = ref<Story[]>([])
const history = ref<StoryHistoryItem[]>([])
const loading = ref(true)
const error = ref<string | null>(null)
const advancingId = ref<string | null>(null)

const activeStories = computed(() =>
  stories.value
    .filter((s) => s.status === 'active')
    .sort((a, b) => {
      if (a.type === 'main' && b.type !== 'main') return -1
      if (a.type !== 'main' && b.type === 'main') return 1
      return 0
    }),
)

async function load() {
  loading.value = true
  error.value = null
  try {
    const res = await getStory()
    stories.value = res.stories ?? []
    history.value = res.story_history ?? []
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

async function advance(storyId: string) {
  advancingId.value = storyId
  try {
    const res = await advanceStory(storyId)
    if ('error' in res) {
      error.value = res.error
    } else {
      error.value = null
      await load()
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : '推进失败'
  } finally {
    advancingId.value = null
  }
}

onMounted(load)
</script>

<style scoped>
.story-page {
  max-width: 900px;
  margin: 0 auto;
  padding: 20px;
}
.page-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.page-head h2 {
  margin: 0;
  color: var(--text-primary, #e4e4e7);
}
.story-section {
  margin-bottom: 24px;
}
.story-section h3 {
  color: var(--text-secondary, #a0a0b8);
  font-size: 0.95rem;
  margin: 0 0 12px;
}
.story-item {
  margin-bottom: 8px;
}
.advance-btn {
  margin-top: -8px;
  margin-bottom: 16px;
}
.history-card {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  background: var(--bg-secondary, #1e1e2e);
  border: 1px solid var(--border-color, #33334a);
  border-radius: 8px;
  margin-bottom: 8px;
}
.history-stages {
  margin-left: auto;
  color: var(--text-secondary, #a0a0b8);
  font-size: 0.85rem;
}
.loading-hint,
.empty-hint,
.error-hint {
  padding: 24px;
  text-align: center;
  color: var(--text-secondary, #a0a0b8);
}
.error-hint {
  color: #fca5a5;
}
</style>
```

> CSS 里 `.btn` / `.btn.sm` / `.story-type-badge` 复用全局样式（App.vue 全局有）。若全局无 `.btn.sm`，推进按钮仍可用（仅样式略差），不阻断功能。

- [ ] **Step 4: 跑测试，确认 GREEN**

```bash
cd D:/amyproject/front
npx vitest run src/views/__tests__/StoryView.spec.ts 2>&1 | tail -15
```

Expected: `Test Files 1 passed` / `Tests 5 passed`。

> 若 `findAllComponents({ name: 'StoryTree' })` 返回 0：把测试里那行改成 `import StoryTree from '@/components/StoryTree.vue'`（顶部），再用 `w.findAllComponents(StoryTree).length`。

- [ ] **Step 5: type-check + 全量单测**

```bash
cd D:/amyproject/front
node_modules/.bin/vue-tsc --build --force; echo "TYPE:$?"
npx vitest run 2>&1 | tail -6
```

Expected: `TYPE:0`；vitest 全量（含原有 2 文件 + 新 3 文件 = 5 文件）全过。

- [ ] **Step 6: Commit**

```bash
cd D:/amyproject
git add front/src/views/StoryView.vue front/src/views/__tests__/StoryView.spec.ts
git commit -m "feat(front): StoryView 剧情可视化页面（加载+树+已完结+推进）

TDD：5 条断言先 FAIL 再实现。onMounted 调 getStory，渲染进行中 StoryTree
与已完结归档，推进按钮调 advanceStory 并刷新。
Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: 路由 + 导航 + 文档同步 + 最终验收

**Files:**
- Modify: `front/src/router/index.ts`
- Modify: `front/src/App.vue`
- Modify: `front/CLAUDE.md`

- [ ] **Step 1: 加 `/story` 路由**

在 `front/src/router/index.ts` 的 routes 数组里，`/memory` 路由之后插入：

```typescript
    {
      path: '/story',
      name: 'story',
      meta: { title: '剧情' },
      component: () => import('../views/StoryView.vue'),
    },
```

- [ ] **Step 2: 导航栏加"剧情"链接**

在 `front/src/App.vue` 的 `.nav-links` 里，`/memory` 的 `<RouterLink>` 之后、`/settings` 之前插入：

```vue
        <RouterLink
          to="/story"
          class="nav-link"
          active-class="active"
        >
          <span class="link-icon">📖</span>
          <span class="link-text">剧情</span>
        </RouterLink>
```

- [ ] **Step 3: 同步 `front/CLAUDE.md`（Working Agreement）**

在 App Structure 节的 `views/` 列表里加一行（放在 `MemoryView.vue` 之后）：
```
│   ├── StoryView.vue           # 剧情可视化页（/story 路由，StoryTree 树状图）
```

在 `api/` 列表里加（放在 `memory.ts` 之后）：
```
│   ├── story.ts                # GET /story、POST /story/advance
```

在 `components/` 列表里加（放在 icons/ 之前）：
```
│   ├── StoryTree.vue          # 单剧情树状图（主线脊柱+分支侧枝）
```

在路由配置节，routes 数组里加：
```typescript
  { path: "/story", component: StoryView, meta: { title: "剧情" } },
```

在 Backend Integration 的 HTTP REST endpoints 列表确认已有 `GET /story`（有则不动）。

并在 Known Issues 加一条备忘（若该节存在）：无（保持简洁，不加）。

- [ ] **Step 4: 全量验证 -- type-check + vitest + 构建**

```bash
cd D:/amyproject/front
node_modules/.bin/vue-tsc --build --force; echo "TYPE:$?"
npx vitest run 2>&1 | tail -6
npm run build-only 2>&1 | tail -5
```

Expected: `TYPE:0`；vitest 全过；`build-only` 产出 `dist/` 无报错。

- [ ] **Step 5: 起前后端，手动验收可视化**

```bash
# Terminal 1（后端，已有 .venv）
cd D:/amyproject/backend && source .venv/Scripts/activate && uvicorn api.api:app --reload --port 8000
# Terminal 2（前端）
cd D:/amyproject/front && npm run dev
```

浏览器开 `http://localhost:5173`，登录后点导航"剧情"：
- 无数据时显示"暂无剧情，多和角色聊聊吧"。
- 与角色聊几轮触发剧情后，看到主线脊柱（done/current/future 圆点）+ 分支侧枝（alt_direction）。
- 点"推进剧情"按钮，树前进一阶段。
- 已完结剧情出现在"已完结"区。

> 若本地无真实 DeepSeek key 造不出剧情数据，至少确认页面加载不报错、空态正确、type-check 与单测全绿即可视为通过（数据层由后端测试覆盖）。

- [ ] **Step 6: Commit**

```bash
cd D:/amyproject
git add front/src/router/index.ts front/src/App.vue front/CLAUDE.md
git commit -m "feat(front): 接入 /story 路由与导航，同步 CLAUDE.md

新增剧情可视化入口（导航"📖 剧情" -> /story）。按 Working Agreement 同步
front/CLAUDE.md 的视图/组件/路由/API 清单。
Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## 最终验收清单

- [ ] `vue-tsc --build --force` exit 0
- [ ] `vitest run` 全过（原有 2 文件 + story/StoryTree/StoryView 3 文件新单测）
- [ ] `npm run build-only` 无报错
- [ ] 导航出现"📖 剧情"，点击进 `/story` 页
- [ ] 空态 / 加载态 / 错误态 / 有数据态均正常
- [ ] `front/CLAUDE.md` 已同步新视图/组件/路由/API

---

## Self-Review

**1. Spec coverage（用户诉求：剧情可视化，树状图，独立路由页）：**
- 树状图 -> Task 2 StoryTree（主线脊柱 + 分支侧枝）。✅
- 独立路由页 -> Task 3 StoryView + Task 4 `/story` 路由 + 导航。✅
- 数据来源 -> 复用后端 `GET /story`（Task 1 客户端）。✅
- 多剧情（主线+支线+历史）-> StoryView active 排序（主线优先）+ 已完结区。✅
- 分支点可视化 -> StoryTree `branch_points` 按 stage 挂侧枝，显示 alt_direction/reason/好感。✅

**2. Placeholder scan：** 无 TBD/TODO/"适当处理"。每个 step 含完整测试代码、实现代码、命令、expected。✅

**3. Type / 命名一致性：**
- `StoryBundle`（Task 1）在 StoryView（Task 3）通过 `getStory()` 返回值用，字段 `stories`/`story_history`/`story` 与后端 `api.py:994-998` 一致。✅
- `AdvanceStoryResult` 字段 `message`/`story`/`branch_created` 与后端 `api.py:1025-1029` 一致；`{error}` 分支与后端 `{"error": "..."}` 一致（Task 3 advance 用 `'error' in res` 判别）。✅
- `Story`/`StoryHistoryItem`/`StoryBranchPoint` 沿用 `types/api.ts`（Task 2/3 都 import）。✅
- `advanceStory(storyId)` Task 1 签名与 Task 3 调用一致。✅
- StoryTree props `story: Story` 与 StoryView `<StoryTree :story="s" />` 一致。✅
- StoryView 测试 mock `@/api` 的 `getStory`/`advanceStory` 与 Task 1 导出一致（经 `api/index.ts` re-export）。✅

**4. TDD 严格性：** 每个 Task 都是 RED（写测试看 FAIL）-> GREEN（实现看 PASS）-> commit。组件测试用真实组件 + @vue/test-utils，API 测试 mock request（薄封装不可避免 mock）。无"先写代码再补测试"。✅

**5. 提交粒度：** 4 个 Task 各独立 commit，feature 从 API -> 组件 -> 页面 -> 路由分层递进，每层可独立验证。✅

**6. Working Agreement：** 新增路由页 / 视图 / 组件 / API 模块属必须同步 CLAUDE.md 的范畴，Task 4 已纳入。✅
