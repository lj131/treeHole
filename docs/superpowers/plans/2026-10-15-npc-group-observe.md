# D4 NPC 群聊旁观 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户能**旁观 NPC 之间的群聊**（它们背着用户聊了什么）。

**Architecture:** 后端 100% 已有，本轮只补"出口"。
`interaction_agent.apply_interaction_result` 早就在往 `world_state` 写
`npc_registry.recent_interactions`（含 `dialogues`），
`GET /world/interactions` / `POST /world/interaction/simulate` 也早就存在。
所以：新建一个独立页面 + 把社交数据从"系统设置"页搬走。

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `front/src/views/NpcGroupChatView.vue` | **新增** | 旁观页（气泡 / 关系 / 八卦） |
| `front/src/views/__tests__/NpcGroupChatView.spec.ts` | **新增** | 6 条测试 |
| `front/src/router/index.ts` | 修改 | `/npc` 路由 |
| `front/src/App.vue` | 修改 | 导航入口 |
| `front/src/views/AboutView.vue` | 修改 | 社交区搬走 → 入口卡片，清死代码 |

---

## Task 0: 先摸清能复用多少

- [x] `interaction_agent`：`gather_interaction_context`（拉角色人设 + 记忆 + NPC 关系）、
      `simulate_interaction`（一次 DeepSeek 调用）、`apply_interaction_result`
      （落 `recent_interactions`，含 `dialogues`，裁剪到 `MAX_INTERACTION_LOG`）
- [x] API：`GET /world/interactions` → snapshot（characters / relationships /
      recent_interactions / gossip / world_impacts）
- [x] 前端 `AboutView` 已有一个紧凑只读列表
- [x] **结论**：和 D2 同一个模式 —— 投入已付大半，差最后一截

## Task 1: 旁观页

- [x] 群聊记录按"一场互动 = 一张会话卡"：时间 / 摘要 / 气泡列表 / 世界影响
- [x] 对话**气泡**：彩色头像（同名字恒同色）+ 说话人名 + 内容
- [x] 关系区：好感 / 信任 / 亲密三条数值条
- [x] 八卦区：source → target
- [x] "触发一场群聊"按钮：
      - 后端 `action === "simulated"` → 提示成功 + **重新拉快照**
      - `action === "skipped"` → 显示 `reason`（今天已模拟过），**不渲染成错误**
      - 接口异常 → 错误文案
- [x] 空态 / 加载失败兜底，不白屏
- [x] 路由 `/npc` + 导航"👥 群聊旁观"

## Task 2: 从 AboutView 搬走

- [x] AboutView 的 `meta.title` 是"**系统设置**"——堆社交关系网文不对题
      （之前"记忆中心"也是这么迁走的），改成入口卡片 + `RouterLink`
- [x] **清掉 1268 字节死代码**：删模板不删 script 就是留垃圾。
      `relationshipPairs` / `resolveCharName` / `loadInteractions` /
      `handleSimulateInteraction` + `interactions` ref + 相关 import
- [x] `computed` import 也一并清（lint unused-vars 抓到的）

## Task 3: 测试（6 条）

- [x] 挂载拉快照 + 气泡渲染 + speaker 解析成中文名
- [x] 关系三条数值 + 八卦渲染
- [x] 点触发 → 调接口 → **成功后重新拉快照**（这条是交互闭环）
- [x] `skipped` 时显示原因且**不是错误样式**（别把冷却提示当故障）
- [x] 空快照空态（**有两个 `.empty-hint`，`find()` 会炸 → 必须 `findAll`**）
- [x] 加载失败显示错误不白屏

## 最终验收

- [x] 前端 type-check 0 / lint 0 / vitest 144
- [x] **浏览器实测 + 截图**：真 token 注入后 `/npc` 渲染出 2 场群聊 / 11 气泡 /
      3 关系 / 2 八卦；点触发后 3 场 / 20 气泡
- [x] 验证过测试能失败（把气泡内容改成"[已屏蔽]"→ 断言立刻红）

## Self-Review

**1. Spec coverage**：D4 要"用户旁观 NPC 之间对话"，Task 1-3 完整覆盖。✅
**2. 最大风险 = 白屏 / 误导性报错**：未登录/接口失败/空快照都有兜底；
   `skipped` 后端语义与 `error` 做了区分（今天已模拟过 ≠ 故障）。✅
**3. 复用而非重造**：后端零改动。若另建一套模拟逻辑就会有两份真相。✅
**4. 顺带清死代码**（1268 字节）而不是只加不改。✅
**5. 不过度设计**：没做实时推送（WebSocket）、没做消息分页、没做气泡左右交替。
   本轮只做"看得见的旁观"。✅

---

## 执行结果（2026-10-15）

4 个 Task 全部完成，6 条测试全过，浏览器实测通过。

### 核心结论：后端 100% 已有

| 层 | 状态 |
|---|---|
| 数据 | `interaction_agent.apply_interaction_result` 早就在写 `recent_interactions`（含 dialogues） |
| 接口 | `GET /world/interactions`、`POST /world/interaction/simulate` 早就存在 |
| 前端 | AboutView 有个紧凑只读列表（且放错了页面） |

**D4 和 D2 完全同一个模式：投入已付大半，差最后一截。**

### 实测数据

登录后访问 `/npc`：
- 2 场群聊 / 11 条气泡 / 3 条关系 / 2 条八卦（种子数据）
- 点"触发一场群聊" → "已模拟一场新的群聊" → 3 场 / 20 条
- 截图 `3d-verify/npc-observe.png`

### 踩的坑

1. **本机 `http_proxy`**：`curl http://127.0.0.1:5173` → **502**，
   `http://localhost:5173` → 200。node `fetch` 同样被代理拦。
   **必须 `--noproxy '*'` 或改用 localhost。**
2. **front 是 `"type": "module"`**：`.js` 脚本里不能 `require()`，要 `.cjs`
3. **node `spawnSync('bash')` 在 Windows 失败** → 不折腾，用 curl 预取 token 写文件再读
4. **`find()` 要求唯一元素**：页面上有两个 `.empty-hint`（关系区 + 群聊区），
   测试必须用 `findAll`
5. **冒烟改了被跟踪的种子数据**：`backend/data/world_state/campus.json` 是 git 跟踪的，
   点"触发群聊"会改关系数值。**已 `git checkout` 还原。**

## Known Issues

- **无实时推送**：要等下次进页面/触发才刷新。做 WebSocket 是单独的活
- **气泡统一左对齐**：没做左右交替（当前更像"聊天记录"而不是"群聊"）
- `MAX_INTERACTION_LOG` 上限由后端定，前端没做分页
