# E2 关系网可视化 + E4 关系时间线 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让"社交模拟"这个卖点**看得见** —— 关系网一眼看出小圈子/孤立者；关系时间线看出"你们怎么一路走到今天"。

**为什么一起做:** 两者都是"把已有数据变成可见"，都**零后端改动**（E2 用 `/world/interactions`，
E4 用 `/memory/full` 里已有的 `self_awareness`），都只改前端。

## Task 0: 数据源（**已完成，实测确认**）

### E2 —— `GET /world/interactions` 已返回

```jsonc
{
  "characters": {"linwan": "林婉", "maid": "小羽", "xiaomei": "小梅"},
  "relationships": {
    "linwan": {"maid": {"favorability": 50, "trust": 50, "intimacy": 30},
               "xiaomei": {"favorability": 51, "trust": 50, "intimacy": 30}},
    "maid":   {"xiaomei": {"favorability": 50, "trust": 50, "intimacy": 30}}
  }
}
```

**⚠️ 两个必须处理的数据特征：**
1. **有向存储、且不对称** —— 有 `linwan→maid` 却**没有** `maid→linwan`；
   也没有任何 `xiaomei→*`。画图时必须**去重成无向边**，否则要么画两条、要么漏边。
2. **可能为空** —— 用户 private 世界还没跑过互动时 `relationships` 是 `{}` → 必须有空态。

### E4 —— `GET /memory/full` 返回 `{memory: {...}}`（**整体透传**），已含：

| 字段 | 例子 | 说明 |
|---|---|---|
| `self_awareness.first_chat_date` | `"2026-10-12"` | 认识多少天的起点 |
| `self_awareness.milestones` | `[{date, from, to}]` | 关系等级变化轨迹（最多 8 条） |
| `self_awareness.fav_trail` | `[{date, value}]` | 好感快照（最多 10 条） |
| `self_awareness.peak_/min_favorability` | `50` | 峰值 / 低谷 |

**⚠️ `peak_fav_date` / `min_fav_date` 可能是空串**（实测就是这样）。
不是 bug —— 初始 `peak_favorability` 就是 50，好感从没超过 50 时 `favorability > peak` 为假，
日期自然不更新。**前端必须兜底**（不显示日期，别显示"最高好感 50（?）"）。

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `front/src/utils/forceGraph.ts` | **新增** | 力导向布局（**纯函数、确定性**，可单测） |
| `front/src/utils/__tests__/forceGraph.spec.ts` | **新增** | 布局断言（不重叠 / 在画布内 / 相连更近） |
| `front/src/components/RelationGraph.vue` | **新增** | SVG 渲染关系网 |
| `front/src/utils/relationship.ts` | **新增** | 关系数据 → 节点/边（**去重无向边**，可单测） |
| `front/src/utils/__tests__/relationship.spec.ts` | **新增** | 去重 / 空数据 / 名字兜底 |
| `front/src/views/NpcGroupChatView.vue` | 修改 | 顶部插入关系网 |
| `front/src/components/RelationshipTimeline.vue` | **新增** | 认识天数 + 里程碑 + 好感曲线 |
| `front/src/views/MemoryView.vue` | 修改 | 加「关系」Tab |

## Task 1: 关系数据 → 图（纯函数，先去重）

- [ ] `buildRelationGraph(snapshot) -> {nodes, edges}`
      - `nodes` 来自 `characters` 映射（**用显示名**）
      - `edges` **无向去重**：`(a,b)` 与 `(b,a)` 只留一条；权重取两者中较高的 favorability
      - **孤儿节点也要画**（没有任何关系的角色 = "被孤立"，这正是图要表达的）
      - 空 `relationships` → 只有节点、没有边（不崩）
- [ ] `relationLevel(favorability) -> {label, tone}`：分档（生疏/一般/不错/很好/亲密）

## Task 2: 力导向布局（纯函数、**确定性**）

- [ ] `layoutForceGraph(nodes, edges, {width, height, iterations})`
      - 初始位置：**按索引均分圆周**（不用随机 → 结果可复现、可测）
      - 迭代：节点间斥力 + 有边节点间弹簧力 + 向心力（防飞散）
      - 输出 clamp 在画布内（含 padding）
- [ ] **确定性是硬要求**：同一输入必须同一输出，否则测试 flaky 且每次刷新图都在跳

## Task 3: 渲染

- [ ] `RelationGraph.vue`：SVG，边用**粗细/透明度**表达好感，节点用圆 + 名字
      - 边的 `stroke-width` 随 favorability 变化；hover 高亮该节点的所有边
      - 空态："还没有关系数据 —— 世界还没跑过互动"
      - 节点少（≤2）时不画力导向（没意义），退回简单排布

## Task 4: 关系时间线

- [ ] `RelationshipTimeline.vue`：
      - 顶部大字：**"你们认识 N 天了"**（`first_chat_date` → 今天；无数据则不显示）
      - 里程碑列表（`milestones`，`from → to`）
      - 好感曲线（`fav_trail` → 迷你折线 SVG）
      - 峰值 / 低谷（**日期为空时只显示数值**）
- [ ] `MemoryView` 加 `relationship` Tab（「关系」）
- [ ] 天数计算用**本地日期**（不能用 UTC，否则晚上差一天 —— E1 踩过）

## Task 5: 测试

- [ ] `relationship.spec.ts`：**有向去重**（A→B + B→A 只出一条）/ 不对称数据
      （只有 A→B）/ 空 relationships / 孤儿节点保留 / 未知角色 id 用 id 兜底 / 权重取较大值
- [ ] `forceGraph.spec.ts`：**同输入同输出**（确定性）/ 所有节点在画布内 /
      节点不重叠（最小间距）/ 有边的节点比无边的近 / 空图不崩 / 单节点居中
- [ ] **验证"测试能失败"**：去掉去重 → 断言红；去掉确定性（加随机）→ 断言红

## 最终验收

- [ ] 前端 type-check / lint / vitest 全绿；后端不回归
- [ ] **端到端实测 + 截图**（关系图必须看到线，不是只有点）
- [ ] 空数据场景也要截图（验证空态，不是白屏）

## Self-Review

**1. Spec coverage**：E2 要"一眼看出谁和谁好、谁被孤立" → Task 1-3；
E4 要"看出怎么走到今天" → Task 4。✅
**2. 最大风险 = 有向去重**：数据不对称（实测），漏处理会画出重复边或漏边。
→ Task 1 单独做 + 专门测不对称。✅
**3. 零后端改动**：两个数据源都已存在。✅
**4. 确定性**：布局不用随机，否则测试 flaky + 每次刷新图跳动。✅
**5. 不过度设计**：不做拖拽/缩放/时间轴动画/导出。✅

## Known Issues（预期）

- 节点多时（>15）力导向可能拥挤 → 当前角色数是个位数，暂不处理
- `fav_trail` 只有 10 条（后端截断）→ 曲线只能看最近 10 天
- 不做实时更新（`/npc` 页已有"模拟互动"按钮，刷新即更新）
