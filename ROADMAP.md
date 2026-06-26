# 系统发展路线图

> 创建于 2026-06-22。基于当前 master 分支(commit `77cca50` 之后)的代码现状梳理。
> 状态约定:🔥 强推荐 / ⏳ 视用户量决定 / ❄️ 不急

## 当前系统定位

**单机为主、单角色为单位的 AI 陪伴系统**:
- 数据全在文件 + SQLite + ChromaDB(本地)
- 每个用户和每个角色独立存档(profile / favorability / 长期记忆 / 剧情)
- 已具备:世界 + NPC 社交 + 剧情推进 + 主动消息 + 语音通话(WebRTC)

---

## 方向 A:深化"陪伴拟真" — 让 AI 更像真人

> **目标**:用户聊一周后觉得"这个角色真的认识我"。

### 🔥 A1. 后台 world tick — 角色不聊天时也活着 [P0] ✅ 已完成

**问题**:`world_event_agent.tick()` 必须由 `/chat` 触发才推进,角色不聊天就是死的。

**已实现** (commit 待提交):
- `funcation/world_tick_scheduler.py` 在 lifespan 启动 asyncio 后台循环
- 每 30min(可配)为活跃用户(`last_chat_time < 7 天`)的当前世界 tick 一次
- world_state 加 `last_bg_tick_time` 字段,独立于 `/chat` 触发的 `last_tick_date`
- `RUN_BACKGROUND_TICK=0` 可完全禁用
- 验证:11 个 approved 用户、5s 循环测试,后台 tick 真实触发 4 次 DeepSeek 调用,关闭优雅
- 详见 CLAUDE.md "后台 World Tick (P0)" 一节

---

### 🔥 A2. 多模态记忆 — 不只是文字

- 图片上传 → Claude/GPT-4V 描述 → 入 RAG
- 用户语音备忘录 → STT → 角色记得
- "上周你给我看的那张猫的照片记得吗?" 真能记得

**预计**:1 周。新增视觉模型 API,改 RAG schema。

---

### A3. 长期"剧情线"系统升级 ✅ 已完成

**现状**:`story_agent` 5 阶段单线剧情。

**已实现** (待提交):
- `memory_data["story"]` → `memory_data["stories"]` 多剧情数组（主线 + 支线）
- `MemoryCenter._migrate_story_format()` 懒迁移旧数据
- 主线推进 + 好感度/心情变化触发分支存档 (`branch_points`)
- `world_event_agent.link_story()` 联动生成支线（`trigger_side_story`，最多 3 条 active side）
- prompt 展示多剧情 + 分支点提示
- MemoryView 剧情 Tab 显示多线卡片
- 兼容 shim (`check_story` / `sync_story_to_state` 委托新函数)
- 新增 `POST /story/advance` / `POST /story/branch` API
- 详见 CLAUDE.md "多剧情系统 (A3)" 一节

**预计**:1-2 周。实际完成 ~4 小时。

---

### 🔥 A4. 角色"自我意识"细节 [P1] ✅ 已完成

基于现有数据,改 prompt 就有,**ROI 极高**:
- 角色记得自己的人格变化("以前我可凶你了,现在好像没那么凶了")
- 对 NPC 有自己看法,主动谈论("今天看到小梅又在抢风头")
- 偶尔反思过去聊天("上周你提到加班那次,我后来一直在想...")

**已实现** (待提交):
- `memory_data["self_awareness"]` 轨迹（milestones / peak·min favorability / fav_trail）,`_ensure_self_awareness` 懒补字段
- `update_state_unified` 算完好感后调 `_track_self_awareness`,**零新增 LLM 调用**
- `prompt._build_self_awareness_section` 渲染"自我觉察"段(关系演变 + 升温/冷却 + 峰值回落怀念) + 规则 #9
- `interaction_agent` 加 `_npc_attitude` + "你对ta们的看法"段(挑好感最高/最低 NPC)
- 详见 CLAUDE.md "角色自我意识 (A4)" 一节

**预计**:2-3 天。实际完成 ~1 小时。

---

## 方向 B:做成"可分享/可发现"的产品

> **目标**:从"我自己玩"到"创作者经济"。

### 🔥 B1. 角色市场

**现状**:`POST /character/create` 已支持 AI 生成,但只能自己看。

**改进**:
- 用户可发布角色到公共市场,带封面/标签/介绍
- 其他用户"领养"角色(各自独立记忆,不串档)
- 评分 / 收藏 / 热度排行
- 创作者收益(后期)

**预计**:2 周。前端 + 后端 + 审核流程。

---

### B2. 角色"克隆"与变体

- 基于现有角色 fork 出变体("林婉,但是赛博朋克版")
- 系统自动 diff 出差异点提交 LLM 改写人设

**预计**:3-5 天。

---

### B3. 公共世界 vs 私人世界

- 校园/赛博朋克世界做成"服务器",所有人共享 world_state
- 跨用户的真实 NPC 互动
- ⚠️ 数据竞争 / 内容审核风险大

**预计**:1 个月+。

---

## 方向 C:做大做稳 — 工程化

> **目标**:扛住 100→1000→10000 用户。

### ⏳ C1. 数据层迁移 PostgreSQL

**现状**:用户表 SQLite,记忆全是 JSON 文件,ChromaDB 本地。
**问题**:多副本部署冲突、横向扩展难、备份难。

**改进**:
- 用户表 SQLite → PostgreSQL
- 记忆 JSON → JSONB 字段
- ChromaDB → **pgvector**(同一个 Postgres,省一套基础设施)

**预计**:1-2 周。当前用户量下不急。

---

### 🔥 C2. Request-scoped cache [P1]

**现状**:`MemoryCenter` 每个方法都 `load_memory → 改 → save_memory`,一次 `/chat` 加载 8-10 次同一文件。

**改进**:
- 一次请求内只 load 一次,结束时统一 save
- 或用 Redis 作为热数据层

**预计**:3-5 天。改完体感明显,但要小心多 agent 并发安全。

---

### ⏳ C3. 计量与计费

**现状**:`usage.record_usage` 在记 token,但没暴露给用户。

**改进**:
- 用户后台看 token/字数/请求次数
- 套餐分级(免费 100 次/天 / Pro 不限 / 企业)
- Stripe / 微信支付集成
- 配额超限自动降级模型

**预计**:1-2 周。

---

### ⏳ C4. 监控 / 日志

- Sentry 收集前端错误
- 后端日志 → Loki / ELK
- DeepSeek 延迟/失败率追踪
- 用户活跃度 dashboard

**预计**:3-5 天。

---

### C5. CI/CD + 测试

**现状**:没有 pytest,前端 Playwright 已配但没用。

**改进**:
- 后端 pytest:agent 单测 + API 集成测试
- 前端 Playwright e2e
- GitHub Actions 自动跑测试 + 部署

**预计**:1 周。

---

## 方向 D:体验创新

### D1. 视频通话 / Live2D

- 每个角色配 Live2D 模型,语音通话时表情同步
- 心情对应不同表情
- VRM 模型支持

**预计**:2-4 周。依赖 Live2D Cubism SDK / Three.js。

---

### D2. 角色"梦境/日记"模式

- 每天凌晨 LLM 帮角色"睡前总结"
- 第二天主动说"我昨晚梦到..."
- 高级版 `chat_summary` + 主动消息

**预计**:2-3 天。

---

### D3. 桌面挂件 / 浏览器扩展 ✅ Electron MVP 已实现

- Electron 桌面小窗：透明、无边框、置顶，可拖拽
- `/widget` 专用路由：compact 头像气泡 + expanded 迷你聊天
- 复用现有 auth/chat/proactive API，不新增后端接口
- 主动冒泡轮询 + 流式聊天

**后续增强**：系统托盘、开机自启、Live2D/VRM、浏览器扩展版。

**预计**:2-4 周。MVP 实际完成 ~半天。

---

### D4. NPC 群聊旁观

- `interaction_agent` 已有 NPC 关系
- 让用户旁观/客串 NPC 之间的对话

**预计**:1 周。

---

## 推进优先级(按 ROI 排序)

| 优先级 | 任务 | 工作量 | 状态 |
|---|---|---|---|
| 🥇 P0 | **A1. 后台 tick + APScheduler** | 3-5 天 | **进行中** |
| 🥈 P1 | C2. Request-scoped cache | 3-5 天 | 待定 |
| 🥈 P1 | A4. 角色自我意识细节 | 2-3 天 | ✅ 已完成 |
| 🥉 P2 | B1. 角色市场 | 2 周 | 待定 |
| 🥉 P2 | A2. 多模态记忆 | 1 周 | 待定 |
| 🥉 P2 | C1. Postgres + pgvector | 1-2 周 | 等用户量上来 |
| - | C3 计费 / C4 监控 / D1 Live2D | 视用户量 | 后期 |

---

## 三个核心选择题(备忘)

如果只能选一个方向 all-in:

1. **高品质陪伴**(深度) → A1 + A4 + A3
2. **创作者平台**(广度) → B1 + B2,先做最简版本验证
3. **工程精品**(技术) → C1 + C2 + C5
