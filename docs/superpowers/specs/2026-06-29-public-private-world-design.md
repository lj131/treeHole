# 公共世界 vs 私人世界 — 设计文档（方案 B：彻底解耦）

- 日期：2026-06-29
- 分支：`feature/public-private-world`
- 状态：已批准，待实施

## 1. 背景与目标

当前系统的"世界"在数据层已经是公共的：世界定义 `data/worlds/{world_id}.json` 和世界状态 `data/world_state/{world_id}.json` 都是全员共享的，所有用户在同一个世界里看到相同的天气/世界事件/NPC 关系。角色记忆/好感度/聊天历史则已经是 per-(user,character) 隔离的。

本功能引入显式的"公共世界 vs 私人世界"区分，让用户对任意世界可二选一：

- **公共世界**：所有用户共享同一份不断演化的活世界（事件、天气、NPC 关系随时间共同推进）。
- **私人世界**：用户独占一份会自己演化的 world_state，别人看不到也影响不了。

核心语义是**世界状态的隔离与演化归属**，不是世界定义的归属（世界定义统一由管理员创建，全员只读共享）。

## 2. 关键约束与产品决策

1. 世界定义由**管理员**创建（需要 admin 世界 CRUD）。普通用户不能自创世界设定。
2. 普通用户对任意世界可二选一：**加入公共实例**（共享演化）或 **开私人副本**（独立演化）。
3. 私人副本从**默认空状态**开始演化（不 copy 公共快照）。
4. 公共世界采用**方案 B 彻底解耦**：把 `tick()` 拆成"纯世界演化"与"角色影响"两层，公共世界每轮每 world 只演化一次，每个活跃用户对未见事件补影响。
5. 不做：用户自创世界定义、私人副本 copy 公共快照、跨世界角色共享、世界模板市场。

## 3. 概念分离

- **世界定义** `data/worlds/{world_id}.json`：静态设定（id/name/description/background/world_event/NPC）。管理员创建，全员只读共享。定义本身不分公私。
- **世界实例 = world_state**：演化的动态状态（事件/天气/NPC 关系）。公私区别在实例：
  - **公共实例**：`data/world_state/{world_id}.json`，全员共享同一份演化（保持现状路径）。
  - **私人实例**：`data/world_state/{user_id}/{world_id}.json`，每用户独立演化。
- 用户的当前选择记在 `User.current_world_mode`（`public` | `private`）。

## 4. 数据模型

### 4.1 User 表

新增列（走现有 `_migrate_user_columns()` 的 ALTER 机制，`backend/funcation/auth.py:219`）：

```python
current_world_mode = Column(String(20), nullable=False, default="public")  # "public" | "private"
```

并在 `_migrate_user_columns()` 的迁移列清单中加入 `("current_world_mode", "VARCHAR(20) NOT NULL DEFAULT 'public'")`。

### 4.2 world_state 路由

`MemoryCenter`（`backend/funcation/memory_center.py`）改造：

- `_get_world_state_path(world_id, user_id=None, mode="public")`：
  - `mode == "private"`（`user_id` 必填）→ `WORLD_STATE_DIR/{user_id}/{world_id}.json`
  - `mode == "public"` → `WORLD_STATE_DIR/{world_id}.json`（现状）
- `load_world_state(world_id, user_id=None, mode="public")`、`save_world_state(world_id, data, user_id=None, mode="public")`：透传 `user_id`/`mode`。
- 新增：
  - `fork_private_world(user_id, world_id)`：建空副本（`create_default_world_state(world_id)`）落盘到私人路径。
  - `get_user_world_mode(user_id)` / `set_user_world_mode(user_id, mode)`：读写 User 表。
  - `get_user_effective_world_state(user_id, world_id, mode)`：按 mode 路由的总入口（公共/私人 load 的统一调用点）。
  - `delete_private_world(user_id, world_id)`：删私人副本（admin 维护或"切回公共"可选）。

### 4.3 角色记忆新增字段（公共世界已读追踪）

`create_default_memory()`（`memory_center.py`）新增：

```python
"seen_world_event_ids": [],  # 该角色已感知过的世界事件 id，用于公共世界补影响去重
```

`_ensure_self_awareness`/`_migrate_*` 风格的懒补：旧 memory 文件无此字段时在 `load_memory()` 幂等补上。

## 5. tick() 解耦（方案 B 核心）

把 `world_event_agent.tick(memory_center, user_id, character, world_def, force=False)`（`backend/funcation/world_event_agent.py:513`）拆成两层：

### 5.1 `evolve_world(mc, world_def, user_id, mode, force=False) -> dict`

纯世界演化，**不碰角色**。搬现有 tick 的前半段：

1. `refresh_world_metadata(world_data)`
2. 推进 running 事件（+20），归档 finished
3. 必要时生成新事件
4. `runtime["last_tick_date"] = today`；**公共世界幂等**：`not force and last_tick == today` → `{"action":"skipped","reason":"already_ticked_today"}`（多用户同一天不重复演化）
5. `mc.save_world_state(world_id, world_data, user_id, mode)`
6. 仍可触发 `interaction_agent.run_interaction`（NPC 互动，纯世界层）
7. 返回 `{action, world_id, mode, notifications, current_events, world_state}`

签名带 `user_id`/`mode` 是为了路由 world_state 文件；公共世界演化时 `user_id` 仅作路由标识，演化结果全员共享。

### 5.2 `apply_world_impact_to_user(mc, user_id, character, world_def, notifications) -> dict`

搬现有 `process_notifications`（`world_event_agent.py:493`）：

- 对每条 notification：`apply_character_impact` + `link_story` + `mark_proactive_notice`
- **公共世界去重**：传入的 notifications 先用 `seen_world_event_ids` 过滤，只对未见事件补影响；处理完把事件 id 追加到 `seen_world_event_ids`（带容量上限，FIFO，保留最近 N 条，避免无限增长）。私人世界演化即影响，不做已读过滤。

### 5.3 兼容 shim

保留旧签名 `tick(mc, user_id, character, world_def, force=False)`：

- 读取 `User.current_world_mode` 决定 mode
- 调 `evolve_world(...)` → 取 notifications
- 调 `apply_world_impact_to_user(...)`
- 返回结构兼容旧调用方

这样 `/chat`、`/chat/stream`、调度器三处现有调用点可平滑切换，回归面可控。

## 6. 调用点改造

### 6.1 `/chat` & `/chat/stream`（`backend/api/api.py`）

原 `world_event_agent.tick(mc, user_id, character, world, ...)` → 仍走 shim（shim 内部按 mode 路由）。关键路径性能：公共世界首个触发者演化（可能调 LLM 生成事件），其他人当天命中幂等跳过 + 补未见影响。`/chat/stream` 的 `_bg_agents` 后台 task 同样走 shim。

### 6.2 后台调度器（`backend/funcation/world_tick_scheduler.py`）

- **公共世界**：每轮**每个 world_id 只 evolve 一次**（去重，修掉现有每活跃用户都 force-tick 共享文件的并发冗余）。限流按 world_id 的 `last_bg_tick_time`。
- **私人世界**：按 (user, world) evolve；限流按 (user,world)。
- **补影响**：所有活跃用户对各自当前 mode 的世界，补未见事件影响（公共世界共享事件，每个用户独立 seen 去重）。
- `_world_tick_due` / `_mark_world_ticked` 改为按 (world_id, mode, user_id) 路由 world_state。

### 6.3 既有端点行为

`GET /world`、`GET /world/events`、`GET /world/interactions`、`POST /world/interaction/simulate`、`POST /world/tick`、`POST /world/event/create`、`POST /world/event/update`：全部按当前用户的 `current_world_mode` 路由 world_state。

## 7. API 端点（`backend/api/api.py`）

| 端点 | 方法 | 鉴权 | 请求体 | 说明 |
|---|---|---|---|---|
| `/worlds` | GET | auth | — | 世界列表，每世界附 `forked_private: bool`（该用户是否已开私人副本） |
| `/world/current` | GET | auth | — | 返回 `{world, mode}` |
| `/world/join-public` | POST | approved | `{world_id}` | 设 current_world + mode=public |
| `/world/fork-private` | POST | approved | `{world_id}` | 建私人空副本 + mode=private |
| `/world` `/world/events` `/world/interactions` | GET | auth | — | 按 mode 路由 |
| `/world/interaction/simulate` `/world/tick` `/world/event/create` `/world/event/update` | POST | approved | 各自 body | 按 mode 路由 |
| `/admin/world/create` | POST | admin | `{id,name,description,background,world_event?}` | 创建世界定义 |
| `/admin/world/update` | PUT | admin | `{id,...}` | 更新世界定义 |
| `/admin/world/delete` | DELETE | admin | `{world_id}` | 删除世界定义（连带清理其公共/私人 world_state） |

旧 `POST /world/switch` 保留为 `join-public` 别名，前端旧调用兼容。

## 8. 前端

- `front/src/types/api.ts`：新增 `WorldMode = 'public' | 'private'`；`/world/current` 返回 `{world, mode}`。
- `front/src/api/world.ts`：新增 `joinPublicWorld(worldId)`、`forkPrivateWorld(worldId)`、admin `createWorld/updateWorld/deleteWorld`。
- `front/src/views/AboutView.vue` 世界切换 UI：每世界卡片两个操作按钮「🌐加入公共」+「🔒开私人副本」，当前选中高亮并标 mode；私人态可「切回公共」。
- `front/src/views/AdminView.vue`：admin 世界管理（id/name/description/background/world_event 表单 + 列表 + 删除）。
- `front/src/views/Chat.vue`：可选显示 mode 角标。
- `front/src/stores/widgetStore` / chatStore：`refreshAll` 顺带拉 world mode。

## 9. 迁移

1. User 表 ALTER 加 `current_world_mode`（默认 `public`）。现有用户行为完全不变，无数据丢失。
2. 现有 `data/world_state/{campus,cyberpunk}.json` 保留为公共实例，不动。
3. 旧 memory 文件懒补 `seen_world_event_ids: []`（`load_memory` 幂等）。
4. 旧 `POST /world/switch` 调用仍可用（join-public 别名）。

## 10. 验证

### 后端

- `py_compile` 全源文件（含新增/改动的 agent 与 api）
- TestClient：`/chat` 走通
- 真实 `/chat/stream`：首 token 正常，后台 `_bg_agents` 走 shim 不报错
- 关键场景：
  1. 两用户同 public world：A 触发演化，B 当天命中幂等跳过、上线看到同一事件且角色补影响（seen 去重）
  2. fork private 后私人独立演化，不污染公共 world_state
  3. admin 创建/更新/删除世界
  4. 公共世界调度器每轮每 world 只演化一次

### 前端

- `npm run build`（type-check + build）通过

### 文档同步

按"改完代码就改 CLAUDE.md"同步 `CLAUDE.md`、`backend/CLAUDE.md`、`front/CLAUDE.md`、`ROADMAP.md`。

## 11. 不做（YAGNI）

- 用户自创世界定义
- 私人副本 copy 公共快照
- 跨世界角色共享
- 世界模板市场
