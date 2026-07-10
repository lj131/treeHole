# 公共世界 vs 私人世界 实施计划（方案 B 彻底解耦）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户对任意世界可二选一「加入公共实例（共享演化）」或「开私人副本（独立演化）」，并把 `world_event_agent.tick()` 拆成「纯世界演化」+「角色影响」两层，使公共世界每轮每 world 只演化一次、各用户对未见事件补影响。

**Architecture:** world_state 按 (user, mode) 路由：public → `data/world_state/{world_id}.json`（现状），private → `data/world_state/{user_id}/{world_id}.json`。`tick()` 解耦为 `evolve_world()`（纯世界演化，公共幂等）+ `apply_world_impact_to_user()`（per-user 角色影响，公共世界用角色 memory 的 `seen_world_event_ids` 去重）。旧 `tick()` 签名保留为 shim 自动按 mode 路由。管理员通过 `/admin/world/*` CRUD 世界定义。

**Tech Stack:** Python FastAPI + SQLAlchemy(SQLite) + DeepSeek（后端）；Vue 3 + TS + Pinia（前端）。

**设计文档：** `docs/superpowers/specs/2026-06-29-public-private-world-design.md`

---

## 文件结构

### 后端修改

- `backend/funcation/auth.py` — User 模型加 `current_world_mode` 列 + `_migrate_user_columns()` 追加该列。
- `backend/funcation/memory_center.py` — world_state 路由按 (user,mode)；新增 `fork_private_world` / `get_user_world_mode` / `set_user_world_mode` / `get_user_effective_world_state` / `delete_private_world`；角色 memory 加 `seen_world_event_ids`。
- `backend/funcation/world_event_agent.py` — `tick()` 拆成 `evolve_world()` + `apply_world_impact_to_user()`；`tick()` 保留为 shim；`create_event`/`update_event`/`get_world_snapshot` 透传 (user,mode)。
- `backend/funcation/world_tick_scheduler.py` — 公共世界每轮每 world_id 只演化一次；私人按 (user,world)；所有活跃用户补未见影响。
- `backend/api/api.py` — 新增 `/world/join-public` `/world/fork-private` `/admin/world/{create,update,delete}`；现有 `/world*` 端点透传 mode。

### 前端修改

- `front/src/types/api.ts` — 加 `WorldMode`；`/world/current` 返回 `{world, mode}`。
- `front/src/api/world.ts` — 加 `joinPublicWorld` / `forkPrivateWorld` / admin CRUD。
- `front/src/views/AboutView.vue` — 世界卡片「🌐加入公共」+「🔒开私人副本」按钮，标 mode。
- `front/src/views/AdminView.vue` — admin 世界管理表单。
- `front/src/stores/chatStore.ts` — `refreshAll` 拉 world mode（可选，见 Task 12）。

### 文档同步（每个相关 Task 完成后或最后统一）

- `CLAUDE.md` / `backend/CLAUDE.md` / `front/CLAUDE.md` / `ROADMAP.md`

---

## Task 1: User 模型加 `current_world_mode` 列

**Files:**
- Modify: `backend/funcation/auth.py:71`（User 模型，在 `current_world_id` 后加列）
- Modify: `backend/funcation/auth.py:225-232`（`_migrate_user_columns()` 的 `new_cols`）

- [ ] **Step 1: 加列定义**

在 `backend/funcation/auth.py:71` 的 `current_world_id = Column(...)` 行之后加：

```python
    current_world_id = Column(String(50), nullable=True)
    # 当前世界的模式："public"（共享演化）| "private"（私人副本独立演化）
    current_world_mode = Column(String(20), nullable=False, default="public")
```

- [ ] **Step 2: 迁移清单追加该列**

在 `backend/funcation/auth.py` 的 `_migrate_user_columns()` 的 `new_cols` 列表末尾（`("avatar", ...)` 之后）追加：

```python
    new_cols = [
        ("daily_chat_limit",     "INTEGER NOT NULL DEFAULT 100"),
        ("character_limit",      "INTEGER NOT NULL DEFAULT 10"),
        ("current_character_id", "VARCHAR(50)"),
        ("current_world_id",     "VARCHAR(50)"),
        ("nickname",             "VARCHAR(50)"),
        ("avatar",               "VARCHAR(255)"),
        ("current_world_mode",   "VARCHAR(20) NOT NULL DEFAULT 'public'"),
    ]
```

- [ ] **Step 3: 语法检查**

Run: `cd backend && python -c "import py_compile; py_compile.compile('funcation/auth.py', doraise=True); print('OK')"`
Expected: `OK`

- [ ] **Step 4: 启动验证列已加（首次启动自动 ALTER）**

Run: `cd backend && source .venv/Scripts/activate && python -c "from funcation.auth import engine; from sqlalchemy import text; r=engine.connect().execute(text('PRAGMA table_info(users)')).fetchall(); print([row[1] for row in r])"`
Expected: 列表包含 `current_world_mode`

- [ ] **Step 5: Commit**

```bash
git add backend/funcation/auth.py
git commit -m "feat(world): User 表新增 current_world_mode 列

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: world_state 路由按 (user, mode)

**Files:**
- Modify: `backend/funcation/memory_center.py:748-788`（`_get_world_state_path` / `load_world_state` / `save_world_state` / `get_current_events` / `get_history_events` / `get_world_runtime_state`）

- [ ] **Step 1: 改 `_get_world_state_path` 支持 private 路径**

把 `backend/funcation/memory_center.py:748-749` 的：

```python
    def _get_world_state_path(self, world_id):
        return os.path.join(WORLD_STATE_DIR, f"{world_id}.json")
```

改为：

```python
    def _get_world_state_path(self, world_id, user_id=None, mode="public"):
        """公共：data/world_state/{world_id}.json
        私人：data/world_state/{user_id}/{world_id}.json"""
        if mode == "private" and user_id is not None:
            return os.path.join(WORLD_STATE_DIR, str(user_id), f"{world_id}.json")
        return os.path.join(WORLD_STATE_DIR, f"{world_id}.json")
```

- [ ] **Step 2: 改 `load_world_state` / `save_world_state` 透传 (user,mode)**

把 `memory_center.py:751-773` 的 `load_world_state` 和 `save_world_state` 改为：

```python
    def load_world_state(self, world_id=None, user_id=None, mode="public"):
        """加载世界的动态状态（事件、环境等）。
        mode='private' + user_id → 该用户的私人副本；
        mode='public'（默认）→ 全员共享的公共实例。"""
        if world_id is None:
            world_id = "campus"

        path = self._get_world_state_path(world_id, user_id, mode)
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            default = create_default_world_state(world_id)
            self.save_world_state(world_id, default, user_id, mode)
            return default

    def save_world_state(self, world_id, data, user_id=None, mode="public"):
        """保存世界动态状态"""
        path = self._get_world_state_path(world_id, user_id, mode)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data["world_id"] = world_id
        data.setdefault("meta", {})
        data["meta"]["updated_at"] = datetime.now().isoformat()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
```

注意：`save_world_state` 原来用 `os.makedirs(WORLD_STATE_DIR, exist_ok=True)`，改为 `os.makedirs(os.path.dirname(path), exist_ok=True)` 以同时覆盖私人子目录。

- [ ] **Step 3: 改 `get_current_events` / `get_history_events` / `get_world_runtime_state` 透传 (user,mode)**

把 `memory_center.py:775-788` 改为：

```python
    def get_current_events(self, world_id=None, user_id=None, mode="public"):
        """获取当前进行中的世界事件"""
        world_data = self.load_world_state(world_id, user_id, mode)
        return world_data.get("current_events", [])

    def get_history_events(self, world_id=None, user_id=None, mode="public"):
        """获取已结束的世界历史事件"""
        world_data = self.load_world_state(world_id, user_id, mode)
        return world_data.get("history_events", [])

    def get_world_runtime_state(self, world_id=None, user_id=None, mode="public"):
        """获取世界运行时环境（季节、天气、时间段）"""
        world_data = self.load_world_state(world_id, user_id, mode)
        return world_data.get("world_state", {})
```

- [ ] **Step 4: 语法检查**

Run: `cd backend && python -c "import py_compile; py_compile.compile('funcation/memory_center.py', doraise=True); print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add backend/funcation/memory_center.py
git commit -m "feat(world): world_state 按 (user, mode) 路由公共/私人实例

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: MemoryCenter 新增 world mode 与 fork 辅助方法

**Files:**
- Modify: `backend/funcation/memory_center.py`（在 `set_user_current_world` / `load_user_current_world` 附近，约 `:690-705`）

- [ ] **Step 1: 加 `get_user_world_mode` / `set_user_world_mode`**

在 `backend/funcation/memory_center.py` 的 `set_user_current_world` 方法（约 `:690`）之前插入：

```python
    def get_user_world_mode(self, user_id):
        """读取该用户当前世界的模式：'public' | 'private'。默认 public。"""
        from funcation.auth import SessionLocal, User
        db = SessionLocal()
        try:
            u = db.query(User).filter(User.id == user_id).first()
            mode = (u.current_world_mode if u else None) or "public"
            return mode if mode in ("public", "private") else "public"
        finally:
            db.close()

    def set_user_world_mode(self, user_id, mode):
        """设置该用户当前世界的模式"""
        from funcation.auth import SessionLocal, User
        if mode not in ("public", "private"):
            mode = "public"
        db = SessionLocal()
        try:
            u = db.query(User).filter(User.id == user_id).first()
            if u:
                u.current_world_mode = mode
                db.commit()
        finally:
            db.close()
```

- [ ] **Step 2: 加 `fork_private_world` / `delete_private_world` / `get_user_effective_world_state`**

在 `load_user_current_world` 方法（约 `:702`）之后插入：

```python
    def fork_private_world(self, user_id, world_id):
        """为用户创建某世界的私人副本（从默认空状态开始，不 copy 公共快照）。
        已存在则直接返回（幂等）。返回私人 world_state。"""
        path = self._get_world_state_path(world_id, user_id, "private")
        if os.path.exists(path):
            return self.load_world_state(world_id, user_id, "private")
        default = create_default_world_state(world_id)
        self.save_world_state(world_id, default, user_id, "private")
        return default

    def delete_private_world(self, user_id, world_id):
        """删除用户的私人世界副本"""
        path = self._get_world_state_path(world_id, user_id, "private")
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

    def has_private_world(self, user_id, world_id):
        """用户是否已开过某世界的私人副本"""
        return os.path.exists(self._get_world_state_path(world_id, user_id, "private"))

    def get_user_effective_world_state(self, user_id, world_id, mode=None):
        """按用户当前 mode 路由总入口，返回 world_state dict。"""
        if mode is None:
            mode = self.get_user_world_mode(user_id)
        return self.load_world_state(world_id, user_id, mode)
```

- [ ] **Step 3: 语法检查**

Run: `cd backend && python -c "import py_compile; py_compile.compile('funcation/memory_center.py', doraise=True); print('OK')"`
Expected: `OK`

- [ ] **Step 4: 功能冒烟测试**

Run:
```bash
cd backend && source .venv/Scripts/activate && python -c "
from funcation.memory_center import MemoryCenter
mc = MemoryCenter()
# fork 一个私人副本（用 user_id=9999 避免污染真实用户）
state = mc.fork_private_world(9999, 'campus')
assert state['world_id'] == 'campus', state
assert mc.has_private_world(9999, 'campus') is True
# 公共实例应与私人不同文件
pub = mc.load_world_state('campus', None, 'public')
assert pub['world_id'] == 'campus'
# 清理
mc.delete_private_world(9999, 'campus')
assert mc.has_private_world(9999, 'campus') is False
print('OK')
"
```
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add backend/funcation/memory_center.py
git commit -m "feat(world): 新增 world mode 读写 + fork/delete 私人副本方法

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: 角色记忆加 `seen_world_event_ids` 字段

**Files:**
- Modify: `backend/funcation/memory_center.py:106`（`create_default_memory` 末尾，`last_chat_time` 之前）
- Modify: `backend/funcation/memory_center.py`（`load_memory` 的懒补逻辑，需先定位）

- [ ] **Step 1: 加默认字段**

在 `backend/funcation/memory_center.py` 的 `create_default_memory()` 中，`"last_chat_time": None`（`:106`）之前插入：

```python
        "self_awareness": {
            "first_chat_date": "",       # 第一次聊天日期
            "peak_favorability": 50,     # 历史好感峰值
            "peak_fav_date": "",
            "min_favorability": 50,      # 历史好感低谷
            "min_fav_date": "",
            "milestones": [],            # 关系等级变化轨迹 [{date, from, to}]
            "fav_trail": [],             # 最近好感快照 [{date, value}]（用于感知升温/冷却）
        },
        "seen_world_event_ids": [],      # 该角色已感知过的世界事件 id（公共世界补影响去重）
        "last_chat_time": None
```

- [ ] **Step 2: 定位 load_memory 的懒补位置**

Run: `cd backend && grep -n "_ensure_self_awareness\|def load_memory" funcation/memory_center.py`
Expected: 显示 `load_memory` 行号与 `_ensure_self_awareness` 调用行号（用于在旁边补 `seen_world_event_ids`）。

- [ ] **Step 3: 在 `load_memory` 里懒补字段**

找到 `load_memory` 中调用 `_ensure_self_awareness(data)` 的那一行（Step 2 定位到），在其后追加：

```python
        data.setdefault("seen_world_event_ids", [])
```

若 `_ensure_self_awareness` 调用形如 `self._ensure_self_awareness(data)`，则在同一作用域紧接其后加这一行 `data.setdefault(...)`。

- [ ] **Step 4: 语法检查**

Run: `cd backend && python -c "import py_compile; py_compile.compile('funcation/memory_center.py', doraise=True); print('OK')"`
Expected: `OK`

- [ ] **Step 5: 功能冒烟测试（懒补幂等）**

Run:
```bash
cd backend && source .venv/Scripts/activate && python -c "
from funcation.memory_center import MemoryCenter, create_default_memory
mc = MemoryCenter()
d = create_default_memory()
assert 'seen_world_event_ids' in d and d['seen_world_event_ids'] == []
# 模拟旧文件无此字段
d.pop('seen_world_event_ids')
assert 'seen_world_event_ids' not in d
# load_memory 内部应补上（用真实用户/角色：linwan + admin=1，若已存在会补字段）
m = mc.load_memory(1, 'linwan')
assert 'seen_world_event_ids' in m, '懒补失败'
print('OK')
"
```
Expected: `OK`（若 linwan/admin 数据不存在会自动建默认，仍应通过）

- [ ] **Step 6: Commit**

```bash
git add backend/funcation/memory_center.py
git commit -m "feat(world): 角色 memory 新增 seen_world_event_ids 已读追踪字段

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: 拆 `tick()` 为 `evolve_world()` + `apply_world_impact_to_user()`

**Files:**
- Modify: `backend/funcation/world_event_agent.py:493-609`（`process_notifications` + `tick`）

这是方案 B 的核心。先抽出 `evolve_world`（纯世界演化），再把 `process_notifications` 改名为 `apply_world_impact_to_user` 并加公共去重。

- [ ] **Step 1: 新增 `evolve_world()`（纯世界演化，无角色影响）**

在 `backend/funcation/world_event_agent.py` 的 `tick` 函数（`:513`）之前插入新函数：

```python
def evolve_world(memory_center, world_def, user_id, mode, force=False):
    """纯世界演化：推进事件 + 生成新事件 + 环境更新 + NPC 互动。
    不碰角色记忆。公共世界按 last_tick_date 当天幂等（避免多用户重复演化）。

    返回 {action, world_id, mode, notifications, current_events, world_state, npc_interaction?}
    """
    world_id = world_def.get("id") or "campus"
    world_data = memory_center.load_world_state(world_id, user_id, mode)
    world_data = refresh_world_metadata(world_data)

    today = datetime.now().strftime("%Y-%m-%d")
    runtime = world_data.setdefault("world_state", {})
    last_tick = runtime.get("last_tick_date", "")

    if not force and last_tick == today:
        return {
            "action": "skipped",
            "reason": "already_ticked_today",
            "world_id": world_id,
            "mode": mode,
            "notifications": [],
            "current_events": world_data.get("current_events", []),
            "world_state": runtime,
        }

    notifications = []
    updated_events = []

    for event in list(world_data.get("current_events", [])):
        if event.get("status") != "running":
            updated_events.append(event)
            continue

        event, notif_type = advance_event(event)

        if notif_type == "finished":
            notifications.append({"type": "finished", "event": dict(event)})
            world_data = archive_finished_event(world_data, event)
        else:
            updated_events.append(event)
            if notif_type:
                notifications.append({"type": notif_type, "event": dict(event)})

    world_data["current_events"] = updated_events

    if count_running_events(world_data) < MAX_CONCURRENT_EVENTS:
        new_event = generate_world_event(world_def, world_data)
        if new_event:
            world_data.setdefault("current_events", []).append(new_event)
            notifications.append({"type": "created", "event": dict(new_event)})
            runtime["last_event_gen_date"] = today

    runtime["last_tick_date"] = today
    world_data["world_state"] = runtime
    memory_center.save_world_state(world_id, world_data, user_id, mode)

    result = {
        "action": "ticked",
        "world_id": world_id,
        "mode": mode,
        "notifications": notifications,
        "current_events": world_data.get("current_events", []),
        "world_state": runtime,
    }

    # NPC 互动（纯世界层，每天一次）
    if notifications:
        last_interaction = runtime.get("last_interaction_date", "")
        if last_interaction != today:
            from funcation import interaction_agent

            trigger_event = notifications[-1]["event"]
            interaction_result = interaction_agent.run_interaction(
                memory_center,
                world_def,
                trigger_event,
            )
            if interaction_result.get("action") == "simulated":
                runtime["last_interaction_date"] = today
                world_data["world_state"] = runtime
                memory_center.save_world_state(world_id, world_data, user_id, mode)
            result["npc_interaction"] = interaction_result

    return result
```

- [ ] **Step 2: 新增 `apply_world_impact_to_user()`（公共去重）**

在 `backend/funcation/world_event_agent.py` 的 `process_notifications`（`:493`）之前插入新函数：

```python
def apply_world_impact_to_user(memory_center, user_id, character, world_def, notifications, mode="public"):
    """对单个用户应用世界事件影响：角色状态 + 剧情 + proactive。
    公共世界（mode='public'）用角色 memory 的 seen_world_event_ids 去重，只对未见事件补影响。
    私人世界（mode='private'）演化即影响，不做去重。"""
    if not notifications:
        return {"applied": 0}

    character_id = character["id"]

    if mode == "public":
        memory_data = memory_center.load_memory(user_id, character_id)
        seen = set(memory_data.get("seen_world_event_ids", []))
        unseen = [
            n for n in notifications
            if n.get("event", {}).get("id") not in seen
        ]
    else:
        unseen = list(notifications)

    applied = 0
    for notif in unseen:
        event = notif["event"]
        notif_type = notif["type"]
        apply_character_impact(memory_center, user_id, character, event, world_def)
        link_story(memory_center, user_id, character, event, notif_type, world_def)
        mark_proactive_notice(memory_center, user_id, character_id, notif_type, event)
        applied += 1

    # 公共世界：把已处理事件 id 追加到 seen_world_event_ids（FIFO，最多保留 200 条）
    if mode == "public" and unseen:
        memory_data = memory_center.load_memory(user_id, character_id)
        seen_list = memory_data.get("seen_world_event_ids", [])
        for n in unseen:
            eid = n.get("event", {}).get("id")
            if eid and eid not in seen_list:
                seen_list.append(eid)
        memory_data["seen_world_event_ids"] = seen_list[-200:]
        memory_center.save_memory(user_id, character_id, memory_data)

    return {"applied": applied}
```

- [ ] **Step 3: 改 `tick()` 为 shim（按 mode 路由）**

把 `backend/funcation/world_event_agent.py:513-609` 的整个 `tick` 函数替换为：

```python
def tick(memory_center, user_id, character, world_def, force=False):
    """兼容 shim：按用户当前 world mode 路由。
    公共世界 → evolve_world（首个触发者演化，其余当天幂等）+ apply_world_impact_to_user（未见事件去重）
    私人世界 → evolve_world + apply_world_impact_to_user（全量影响）

    调用方（/chat、/chat/stream、调度器、/world/tick）无需感知 mode。
    """
    mode = memory_center.get_user_world_mode(user_id)
    world_id = world_def.get("id") or "campus"

    evolve_result = evolve_world(memory_center, world_def, user_id, mode, force=force)

    notifications = evolve_result.get("notifications", [])
    if notifications and character:
        apply_world_impact_to_user(
            memory_center, user_id, character, world_def, notifications, mode
        )

    return {
        "action": evolve_result.get("action"),
        "world_id": world_id,
        "mode": mode,
        "notifications": notifications,
        "current_events": evolve_result.get("current_events", []),
        "world_state": evolve_result.get("world_state", {}),
    }
```

注意：删除原 `tick` 函数体里 `process_notifications(...)` 的调用与 `interaction_agent` 分支——这些已分别移入 `evolve_world`（NPC 互动）和 `apply_world_impact_to_user`（角色影响）。`process_notifications` 函数本身保留（旧调用方 `create_event`/`update_event` 仍用，见 Task 6），不要删。

- [ ] **Step 4: 语法检查**

Run: `cd backend && python -c "import py_compile; py_compile.compile('funcation/world_event_agent.py', doraise=True); print('OK')"`
Expected: `OK`

- [ ] **Step 5: 功能冒烟测试（公共幂等）**

Run:
```bash
cd backend && source .venv/Scripts/activate && python -c "
from funcation.memory_center import MemoryCenter
from funcation import world_event_agent
mc = MemoryCenter()
# 用 admin=1 + linwan + campus 公共世界
character = mc.load_character_by_id('linwan')
world = mc.load_world_by_id('campus')
r1 = world_event_agent.tick(mc, 1, character, world, force=True)
assert r1['action'] in ('ticked', 'skipped'), r1
assert r1.get('mode') == 'public'
# 同一天非 force 第二次应 skipped（幂等）
r2 = world_event_agent.tick(mc, 1, character, world, force=False)
assert r2['action'] == 'skipped', r2
print('OK')
"
```
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add backend/funcation/world_event_agent.py
git commit -m "feat(world): 拆 tick() 为 evolve_world + apply_world_impact_to_user（公共去重）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 6: `create_event` / `update_event` / `get_world_snapshot` 透传 (user,mode)

这三个函数当前只用 `world_id` 调 `load_world_state`/`save_world_state`，私人世界会读到公共文件。需透传 (user,mode)。

**Files:**
- Modify: `backend/funcation/world_event_agent.py:616-685`（`create_event` / `update_event` / `get_world_snapshot`）

- [ ] **Step 1: 改 `create_event` 签名与内部路由**

把 `backend/funcation/world_event_agent.py:616-632` 的 `create_event` 改为：

```python
def create_event(memory_center, world_def, event_data=None, auto_generate=False, user_id=None, mode="public"):
    """手动创建或 AI 自动生成世界事件"""
    world_id = world_def.get("id") or "campus"
    world_data = memory_center.load_world_state(world_id, user_id, mode)
    world_data = refresh_world_metadata(world_data)

    if auto_generate or not event_data:
        event = generate_world_event(world_def, world_data)
        if not event:
            return None, world_data
    else:
        event = _normalize_event(event_data, world_id)
        event["status"] = "running"

    world_data.setdefault("current_events", []).append(event)
    memory_center.save_world_state(world_id, world_data, user_id, mode)
    return event, world_data
```

- [ ] **Step 2: 改 `update_event` 签名与内部路由**

把 `backend/funcation/world_event_agent.py:635-669` 的 `update_event` 改为：

```python
def update_event(memory_center, world_id, event_id, updates, user_id=None, mode="public"):
    """更新指定世界事件"""
    world_data = memory_center.load_world_state(world_id, user_id, mode)
    found = None

    for event in world_data.get("current_events", []):
        if event.get("id") == event_id:
            found = event
            break

    if not found:
        return None, world_data, None

    if "title" in updates and updates["title"] is not None:
        found["title"] = updates["title"]
    if "description" in updates and updates["description"] is not None:
        found["description"] = updates["description"]
    if "importance" in updates and updates["importance"] is not None:
        found["importance"] = max(1, min(10, int(updates["importance"])))
    if "progress" in updates and updates["progress"] is not None:
        found["progress"] = max(0, min(100, int(updates["progress"])))
    if "status" in updates and updates["status"] is not None:
        found["status"] = updates["status"]
        if found["status"] == "finished" and found["progress"] < 100:
            found["progress"] = 100

    notification_type = None
    if found.get("status") == "finished" and found.get("progress", 0) >= 100:
        notification_type = "finished"
        world_data = archive_finished_event(world_data, found)
    elif "progress" in updates:
        notification_type = "advanced"

    memory_center.save_world_state(world_id, world_data, user_id, mode)
    return found, world_data, notification_type
```

- [ ] **Step 3: 改 `get_world_snapshot` 签名与内部路由**

把 `backend/funcation/world_event_agent.py:672-685` 的 `get_world_snapshot` 改为：

```python
def get_world_snapshot(memory_center, world_def, user_id=None, mode="public"):
    """获取世界静态定义 + 动态状态完整快照"""
    world_id = world_def.get("id") or "campus"
    world_data = memory_center.load_world_state(world_id, user_id, mode)
    world_data = refresh_world_metadata(world_data)
    memory_center.save_world_state(world_id, world_data, user_id, mode)

    return {
        "world": world_def,
        "world_id": world_id,
        "world_state": world_data.get("world_state", {}),
        "current_events": world_data.get("current_events", []),
        "history_events": world_data.get("history_events", []),
    }
```

- [ ] **Step 4: 语法检查**

Run: `cd backend && python -c "import py_compile; py_compile.compile('funcation/world_event_agent.py', doraise=True); print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add backend/funcation/world_event_agent.py
git commit -m "feat(world): create_event/update_event/get_world_snapshot 透传 (user,mode)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 7: API 层现有 `/world*` 端点透传 mode

让 `/world`、`/world/events`、`/world/event/create`、`/world/event/update`、`/world/tick`、`/world/interactions`、`/world/interaction/simulate` 按当前用户 mode 路由。

**Files:**
- Modify: `backend/api/api.py:1305-1438`（world 端点区块）
- Modify: `backend/funcation/interaction_agent.py`（`get_interaction_snapshot` / `run_interaction` 透传，需先确认签名）

- [ ] **Step 1: 确认 interaction_agent 函数签名**

Run: `cd backend && grep -n "def get_interaction_snapshot\|def run_interaction" funcation/interaction_agent.py`
Expected: 两个函数定义行号与现有参数。记录它们当前是否只接 `world_id` / `world_def`。

- [ ] **Step 2: 给 interaction_agent 两个函数加 (user_id, mode) 透传**

根据 Step 1 的签名，给 `get_interaction_snapshot` 和 `run_interaction` 加可选参数 `user_id=None, mode="public"`，并让其内部调 `load_world_state`/`get_npc_relationships` 时透传。典型改法（若原签名是 `get_interaction_snapshot(memory_center, world_id)`）：

```python
def get_interaction_snapshot(memory_center, world_id, user_id=None, mode="public"):
    world_data = memory_center.load_world_state(world_id, user_id, mode)
    # ... 其余逻辑不变，凡内部再用 load_world_state / get_npc_relationships 的调用点都透传 (user_id, mode)
```

`run_interaction` 同理。**先读这两个函数全文**，把每个 `load_world_state(...)` / `get_npc_relationships(...)` 调用点都补上 `user_id, mode`。

- [ ] **Step 3: 改 `/world` 快照端点**

把 `backend/api/api.py:1305-1311` 的 `get_world` 改为：

```python
@app.get("/world")
def get_world(user = Depends(require_auth)):
    """获取当前世界静态定义 + 动态状态（事件、环境），按 mode 路由"""
    world = mc.load_user_current_world(user.id)
    if not world:
        return {"error": "world not found"}
    mode = mc.get_user_world_mode(user.id)
    return world_event_agent.get_world_snapshot(mc, world, user.id, mode)
```

- [ ] **Step 4: 改 `/world/events` 端点**

把 `backend/api/api.py:1314-1323` 改为：

```python
@app.get("/world/events")
def get_world_events(user = Depends(require_auth)):
    """获取当前世界事件列表（进行中 + 历史），按 mode 路由"""
    world_id = mc.get_user_current_world_id(user.id)
    mode = mc.get_user_world_mode(user.id)
    return {
        "world_id": world_id,
        "mode": mode,
        "current_events": mc.get_current_events(world_id, user.id, mode),
        "history_events": mc.get_history_events(world_id, user.id, mode),
        "world_state": mc.get_world_runtime_state(world_id, user.id, mode),
    }
```

- [ ] **Step 5: 改 `/world/event/create` 端点**

把 `backend/api/api.py:1326-1366` 改为（`create_event` 透传 mode；影响仍走 `apply_world_impact_to_user` 公共去重）：

```python
@app.post("/world/event/create")
def create_world_event(req: WorldEventCreateRequest, user = Depends(require_approved)):
    """创建世界事件（手动或 AI 自动生成），按 mode 路由"""
    world = mc.load_user_current_world(user.id)
    character = mc.load_user_current_character(user.id)
    mode = mc.get_user_world_mode(user.id)

    event_data = None
    if not req.auto_generate:
        event_data = {
            "title": req.title,
            "description": req.description,
            "importance": req.importance,
            "progress": 0,
            "status": "running",
            "impact": [],
        }

    event, world_data = world_event_agent.create_event(
        mc,
        world,
        event_data=event_data,
        auto_generate=req.auto_generate or not req.title,
        user_id=user.id,
        mode=mode,
    )

    if not event:
        return {"error": "事件创建失败"}

    # 创建事件对当前用户即时影响（公共世界用 seen 去重）
    world_event_agent.apply_world_impact_to_user(
        mc, user.id, character, world,
        [{"type": "created", "event": dict(event)}], mode,
    )

    return {
        "message": "世界事件已创建",
        "event": event,
        "current_events": world_data.get("current_events", []),
    }
```

- [ ] **Step 6: 改 `/world/event/update` 端点**

把 `backend/api/api.py:1369-1406` 改为：

```python
@app.post("/world/event/update")
def update_world_event(req: WorldEventUpdateRequest, user = Depends(require_approved)):
    """更新世界事件（进度、状态、标题等），按 mode 路由"""
    world = mc.load_user_current_world(user.id)
    character = mc.load_user_current_character(user.id)
    world_id = world.get("id") or mc.get_user_current_world_id(user.id)
    mode = mc.get_user_world_mode(user.id)

    updates = req.model_dump(exclude={"event_id"}, exclude_none=True)
    event, world_data, notification_type = world_event_agent.update_event(
        mc,
        world_id,
        req.event_id,
        updates,
        user_id=user.id,
        mode=mode,
    )

    if not event:
        return {"error": "事件不存在"}

    if notification_type:
        world_event_agent.apply_world_impact_to_user(
            mc, user.id, character, world,
            [{"type": notification_type, "event": dict(event)}], mode,
        )

    return {
        "message": "世界事件已更新",
        "event": event,
        "current_events": world_data.get("current_events", []),
        "history_events": world_data.get("history_events", []),
    }
```

- [ ] **Step 7: 改 `/world/tick` 端点**

`/world/tick` 调的是 `tick()` shim，shim 内部已按 mode 路由，无需改逻辑，但确认 `backend/api/api.py:1409-1423` 仍调 `world_event_agent.tick(mc, user.id, character, world, force=req.force)`——保持不变即可（shim 自路由）。本步无代码改动，仅确认。

- [ ] **Step 8: 改 `/world/interactions` 与 `/world/interaction/simulate` 端点**

把 `backend/api/api.py:1426-1438` 改为：

```python
@app.get("/world/interactions")
def get_world_interactions(user = Depends(require_auth)):
    """获取 NPC 间关系与近期互动记录，按 mode 路由"""
    world_id = mc.get_user_current_world_id(user.id)
    mode = mc.get_user_world_mode(user.id)
    return interaction_agent.get_interaction_snapshot(mc, world_id, user.id, mode)


@app.post("/world/interaction/simulate")
def simulate_world_interaction(user = Depends(require_approved)):
    """手动触发一次多角色互动模拟（基于当前世界事件），按 mode 路由"""
    world = mc.load_user_current_world(user.id)
    mode = mc.get_user_world_mode(user.id)
    result = interaction_agent.run_interaction(mc, world, user.id, mode)
    return result
```

- [ ] **Step 9: 改 `/world/current` 返回 mode**

把 `backend/api/api.py:1271-1277` 改为：

```python
@app.get("/world/current")
def get_current_world(user = Depends(require_auth)):
    """获取当前世界的完整定义 + 模式"""
    world = mc.load_user_current_world(user.id)
    mode = mc.get_user_world_mode(user.id)
    return {
        "world": world,
        "mode": mode,
    }
```

- [ ] **Step 10: 语法检查**

Run: `cd backend && python -c "import py_compile; [py_compile.compile(f, doraise=True) for f in ['api/api.py','funcation/interaction_agent.py']]; print('OK')"`
Expected: `OK`

- [ ] **Step 11: 启动后端 + TestClient 打通**

Run:
```bash
cd backend && source .venv/Scripts/activate && python -c "
from fastapi.testclient import TestClient
from api.api import app
c = TestClient(app)
# 公共世界快照
r = c.get('/world', headers={'Authorization':'Bearer ' + _get_token()})
print(r.status_code, r.json().get('world_id'))
"
```

其中 `_get_token()` 取 admin token：在脚本顶部加

```python
def _get_token():
    from funcation.auth import create_access_token
    return create_access_token({'sub': '1'})
```

Expected: `200 campus`（若 `/world` 需 auth，TestClient 带上 admin token）

- [ ] **Step 12: Commit**

```bash
git add backend/api/api.py backend/funcation/interaction_agent.py
git commit -m "feat(world): 现有 /world* 端点按用户 mode 路由 + /world/current 返回 mode

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 8: 新增 `/world/join-public` 与 `/world/fork-private` 端点

**Files:**
- Modify: `backend/api/api.py`（在 `/world/switch` 之后，约 `:773`）

- [ ] **Step 1: 加请求模型 + 两个端点**

在 `backend/api/api.py` 的 `switch_world`（`:768-773`）之后插入：

```python
class WorldJoinRequest(BaseModel):
    world_id: str


# 加入公共世界（共享演化）
@app.post("/world/join-public")
def join_public_world(req: WorldJoinRequest, user = Depends(require_approved)):
    """设当前世界 + mode=public（共享演化）"""
    if not mc.load_world_by_id(req.world_id):
        return {"error": "世界不存在"}
    mc.set_user_current_world(user.id, req.world_id)
    mc.set_user_world_mode(user.id, "public")
    return {"message": "已加入公共世界", "mode": "public"}


# 开私人副本（独立演化）
@app.post("/world/fork-private")
def fork_private_world(req: WorldJoinRequest, user = Depends(require_approved)):
    """为该世界创建私人空副本 + mode=private"""
    if not mc.load_world_by_id(req.world_id):
        return {"error": "世界不存在"}
    mc.fork_private_world(user.id, req.world_id)  # 幂等
    mc.set_user_current_world(user.id, req.world_id)
    mc.set_user_world_mode(user.id, "private")
    return {"message": "已开启私人世界", "mode": "private"}
```

- [ ] **Step 2: 让 `/world/switch` 保留为 join-public 别名**

确认 `backend/api/api.py:768-773` 的 `switch_world` 保持原样（它设 current_world 但不改 mode，等于保持原 mode，前端旧调用兼容）。无需改代码，仅确认。

- [ ] **Step 3: 语法检查**

Run: `cd backend && python -c "import py_compile; py_compile.compile('api/api.py', doraise=True); print('OK')"`
Expected: `OK`

- [ ] **Step 4: 功能测试（fork→mode 切换）**

Run:
```bash
cd backend && source .venv/Scripts/activate && python -c "
from fastapi.testclient import TestClient
from api.api import app
from funcation.auth import create_access_token
c = TestClient(app)
h = {'Authorization':'Bearer ' + create_access_token({'sub':'1'})}
# fork 私人
r = c.post('/world/fork-private', json={'world_id':'campus'}, headers=h)
print('fork', r.status_code, r.json())
assert r.json().get('mode') == 'private'
# 当前世界应反映 private
r2 = c.get('/world/current', headers=h)
print('current', r2.json().get('mode'))
assert r2.json().get('mode') == 'private'
# 切回公共
r3 = c.post('/world/join-public', json={'world_id':'campus'}, headers=h)
assert r3.json().get('mode') == 'public'
print('OK')
"
```
Expected: 三个断言通过，输出 `OK`

- [ ] **Step 5: Commit**

```bash
git add backend/api/api.py
git commit -m "feat(world): 新增 /world/join-public 与 /world/fork-private 端点

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 9: `/worlds` 标注私人副本；admin 世界定义 CRUD 端点

**Files:**
- Modify: `backend/funcation/memory_center.py:719-744`（`get_all_worlds`）
- Modify: `backend/api/api.py:760-764`（`/worlds`）+ 新增 admin 端点

- [ ] **Step 1: 改 `get_all_worlds` 返回更完整字段**

把 `backend/funcation/memory_center.py:719-744` 的 `get_all_worlds` 改为（保留原返回结构，仅补 background/world_event，不改前端契约）：

```python
    def get_all_worlds(self):
        """获取所有世界列表（静态定义摘要）"""
        worlds = []
        seen_ids = set()

        for search_dir in [WORLDS_DIR, "worlds"]:
            if not os.path.exists(search_dir):
                continue
            for file in os.listdir(search_dir):
                if file.endswith(".json"):
                    path = os.path.join(search_dir, file)
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        world_id = data.get("id")
                        if world_id and world_id not in seen_ids:
                            seen_ids.add(world_id)
                            worlds.append({
                                "id": world_id,
                                "name": data.get("name", world_id),
                                "description": data.get("description", ""),
                                "background": data.get("background", ""),
                                "world_event": data.get("world_event", {}),
                            })
                    except:
                        pass

        return worlds
```

- [ ] **Step 2: 改 `/worlds` 标注 forked_private**

把 `backend/api/api.py:760-764` 的 `get_worlds` 改为：

```python
@app.get("/worlds")
def get_worlds(user = Depends(require_auth)):
    worlds = mc.get_all_worlds()
    for w in worlds:
        w["forked_private"] = mc.has_private_world(user.id, w["id"])
    return {
        "worlds": worlds
    }
```

- [ ] **Step 3: 新增 admin 世界 CRUD 端点**

在 `backend/api/api.py`（admin 相关端点附近，或 `/world/fork-private` 之后）插入：

```python
class AdminWorldCreateRequest(BaseModel):
    id: str
    name: str
    description: str = ""
    background: str = ""
    world_event: dict | None = None


class AdminWorldUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    background: str | None = None
    world_event: dict | None = None


class AdminWorldIdRequest(BaseModel):
    world_id: str


def _save_world_definition(world_id, data):
    """写世界定义到 data/worlds/{world_id}.json"""
    path = os.path.join(WORLDS_DIR, f"{world_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


@app.post("/admin/world/create")
def admin_create_world(req: AdminWorldCreateRequest, user = Depends(require_admin)):
    """管理员创建世界定义"""
    if mc.load_world_by_id(req.id):
        return {"error": "世界 id 已存在"}
    data = {
        "id": req.id,
        "name": req.name,
        "description": req.description,
        "background": req.background,
        "world_event": req.world_event or {},
    }
    _save_world_definition(req.id, data)
    return {"message": "世界已创建", "world": data}


@app.put("/admin/world/update")
def admin_update_world(req: AdminWorldIdRequest, body: AdminWorldUpdateRequest, user = Depends(require_admin)):
    """管理员更新世界定义"""
    data = mc.load_world_by_id(req.world_id)
    if not data:
        return {"error": "世界不存在"}
    for k in ("name", "description", "background", "world_event"):
        v = getattr(body, k)
        if v is not None:
            data[k] = v
    _save_world_definition(req.world_id, data)
    return {"message": "世界已更新", "world": data}


@app.delete("/admin/world/delete")
def admin_delete_world(req: AdminWorldIdRequest, user = Depends(require_admin)):
    """管理员删除世界定义（连带清理公共 world_state）"""
    path = os.path.join(WORLDS_DIR, f"{req.world_id}.json")
    if not os.path.exists(path):
        return {"error": "世界不存在"}
    os.remove(path)
    # 清理公共 world_state（私人副本不在此清理，按用户隔离）
    state_path = os.path.join(WORLD_STATE_DIR, f"{req.world_id}.json")
    if os.path.exists(state_path):
        os.remove(state_path)
    return {"message": "世界已删除"}
```

需确认 `api/api.py` 顶部已 import `WORLDS_DIR` / `WORLD_STATE_DIR`。若未 import，在 import 区加：

```python
from funcation.memory_center import WORLDS_DIR, WORLD_STATE_DIR
```

（先用 `grep -n "WORLDS_DIR\|WORLD_STATE_DIR" backend/api/api.py` 确认是否已导入。）

注意：FastAPI 不能直接同时接两个 body 模型。把 `admin_update_world` 改为单一 body 合并 world_id：用 `AdminWorldUpdateRequest` 内含 `world_id: str` 字段更稳。重写为：

```python
class AdminWorldUpdateRequest(BaseModel):
    world_id: str
    name: str | None = None
    description: str | None = None
    background: str | None = None
    world_event: dict | None = None


@app.put("/admin/world/update")
def admin_update_world(req: AdminWorldUpdateRequest, user = Depends(require_admin)):
    """管理员更新世界定义"""
    data = mc.load_world_by_id(req.world_id)
    if not data:
        return {"error": "世界不存在"}
    for k in ("name", "description", "background", "world_event"):
        v = getattr(req, k)
        if v is not None:
            data[k] = v
    _save_world_definition(req.world_id, data)
    return {"message": "世界已更新", "world": data}


@app.delete("/admin/world/delete")
def admin_delete_world(req: AdminWorldIdRequest, user = Depends(require_admin)):
    """管理员删除世界定义（连带清理公共 world_state）"""
    path = os.path.join(WORLDS_DIR, f"{req.world_id}.json")
    if not os.path.exists(path):
        return {"error": "世界不存在"}
    os.remove(path)
    state_path = os.path.join(WORLD_STATE_DIR, f"{req.world_id}.json")
    if os.path.exists(state_path):
        os.remove(state_path)
    return {"message": "世界已删除"}
```

- [ ] **Step 4: 语法检查**

Run: `cd backend && python -c "import py_compile; [py_compile.compile(f, doraise=True) for f in ['api/api.py','funcation/memory_center.py']]; print('OK')"`
Expected: `OK`

- [ ] **Step 5: 功能测试（admin CRUD）**

Run:
```bash
cd backend && source .venv/Scripts/activate && python -c "
from fastapi.testclient import TestClient
from api.api import app
from funcation.auth import create_access_token
c = TestClient(app)
h = {'Authorization':'Bearer ' + create_access_token({'sub':'1'})}
# 创建
r = c.post('/admin/world/create', json={'id':'testworld','name':'测试世界','description':'x','background':'y'}, headers=h)
print('create', r.status_code, r.json().get('message'))
assert r.status_code == 200 and r.json().get('world',{}).get('id')=='testworld'
# 更新
r2 = c.put('/admin/world/update', json={'world_id':'testworld','name':'改名'}, headers=h)
assert r2.json().get('world',{}).get('name')=='改名'
# 删除
r3 = c.delete('/admin/world/delete', json={'world_id':'testworld'}, headers=h)
assert r3.json().get('message')=='世界已删除'
print('OK')
"
```
Expected: `OK`（注：DELETE 带 body 在 TestClient 用 `json=` 参数）

- [ ] **Step 6: Commit**

```bash
git add backend/api/api.py backend/funcation/memory_center.py
git commit -m "feat(world): /worlds 标注 forked_private + admin 世界定义 CRUD

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 10: 后台调度器公共世界去重演化

公共世界每轮每 world_id 只 `evolve_world` 一次（不再每活跃用户都 force-tick 共享文件），所有活跃用户补各自未见影响。

**Files:**
- Modify: `backend/funcation/world_tick_scheduler.py:102-189`（`_world_tick_due` / `_mark_world_ticked` / `_tick_one_user`）

- [ ] **Step 1: 改 `_world_tick_due` / `_mark_world_ticked` 按 (world, mode, user) 路由**

把 `backend/funcation/world_tick_scheduler.py:102-134` 的两个函数改为：

```python
def _world_tick_due(mc: MemoryCenter, world_id: str, user_id=None, mode="public") -> bool:
    """根据 world_state 的 last_bg_tick_time 字段判断是否到了 tick 时间。
    公共世界按 world_id 共享节流；私人世界按 (user,world) 节流。"""
    try:
        world_data = mc.load_world_state(world_id, user_id, mode)
    except Exception:
        return True

    runtime = world_data.get("world_state", {})
    last_bg_tick = runtime.get("last_bg_tick_time", "")
    if not last_bg_tick:
        return True

    try:
        last_dt = datetime.fromisoformat(last_bg_tick)
    except (ValueError, TypeError):
        return True

    return datetime.now() - last_dt > timedelta(minutes=MIN_TICK_INTERVAL_MIN)


def _mark_world_ticked(mc: MemoryCenter, world_id: str, user_id=None, mode="public"):
    """记录这一轮 background tick 的时间到 world_state。"""
    try:
        world_data = mc.load_world_state(world_id, user_id, mode)
        runtime = world_data.setdefault("world_state", {})
        runtime["last_bg_tick_time"] = datetime.now().isoformat()
        mc.save_world_state(world_id, world_data, user_id, mode)
    except Exception as exc:
        logger.warning("[world_tick] 标记 last_bg_tick_time 失败: %s", exc)
```

- [ ] **Step 2: 重写 `_tick_one_user` 用 evolve + apply 两层**

把 `backend/funcation/world_tick_scheduler.py:137-189` 的 `_tick_one_user` 改为：

```python
async def _tick_one_user(mc: MemoryCenter, user_info: dict, loop, evolved_worlds: set):
    """为单个用户的当前世界做一次 background tick。

    公共世界：每轮每 world_id 只 evolve 一次（evolved_worlds 去重）；
              所有用户对各自未见事件补影响。
    私人世界：按 (user,world) evolve + 全量影响。
    """
    user_id = user_info["id"]
    character_id = user_info.get("current_character_id") or "linwan"
    world_id = user_info.get("current_world_id") or "campus"

    # 1. 用户活跃检查
    if not await loop.run_in_executor(
        None, lambda: _should_tick_user(mc, user_id, character_id)
    ):
        return None

    # 2. 加载角色 + 世界定义 + 模式
    try:
        character = await loop.run_in_executor(
            None, lambda: mc.load_character_by_id(character_id)
        )
        world = await loop.run_in_executor(
            None, lambda: mc.load_world_by_id(world_id)
        )
        mode = await loop.run_in_executor(
            None, lambda: mc.get_user_world_mode(user_id)
        )
    except Exception as exc:
        logger.warning("[world_tick] user=%s 加载失败,跳过: %s", user_id, exc)
        return None

    if not world:
        return None

    # 3. 节流检查（公共按 world_id，私人按 user+world）
    dedup_key = world_id if mode == "public" else f"{user_id}:{world_id}"
    if not await loop.run_in_executor(
        None, lambda: _world_tick_due(mc, world_id, user_id if mode == "private" else None, mode)
    ):
        # 到点未到：公共世界即便没演化，也尝试给用户补未见事件影响
        evolved = dedup_key in evolved_worlds
        if not evolved:
            return None

    # 4. 演化世界（公共去重：本轮该 world 已演化过则跳过演化步骤）
    evolve_result = None
    if dedup_key not in evolved_worlds:
        try:
            evolve_result = await loop.run_in_executor(
                None,
                lambda: world_event_agent.evolve_world(mc, world, user_id, mode, force=True),
            )
            evolved_worlds.add(dedup_key)
            await loop.run_in_executor(
                None,
                lambda: _mark_world_ticked(mc, world_id, user_id if mode == "private" else None, mode)
            )
        except Exception as exc:
            logger.warning("[world_tick] user=%s evolve 失败: %s", user_id, exc)
            return None

    # 5. 补角色影响
    notifications = (evolve_result or {}).get("notifications", [])
    if notifications and character:
        try:
            await loop.run_in_executor(
                None,
                lambda: world_event_agent.apply_world_impact_to_user(
                    mc, user_id, character, world, notifications, mode
                ),
            )
        except Exception as exc:
            logger.warning("[world_tick] user=%s apply impact 失败: %s", user_id, exc)

    return evolve_result or {"action": "impact-only", "world_id": world_id, "mode": mode}
```

- [ ] **Step 3: 改 `_scheduler_loop` 传入 `evolved_worlds`**

把 `backend/funcation/world_tick_scheduler.py:210-225` 的主循环里调用 `_tick_one_user` 的部分改为（在 while 循环每轮开头新建 `evolved_worlds = set()`）：

```python
    while not _stop_event.is_set():
        try:
            users = await loop.run_in_executor(None, _get_active_users)
            evolved_worlds: set = set()
            ticked = 0
            for user_info in users:
                if _stop_event.is_set():
                    break
                if not user_info.get("current_character_id"):
                    continue
                result = await _tick_one_user(mc, user_info, loop, evolved_worlds)
                if result and result.get("action") in ("ticked", "impact-only"):
                    ticked += 1
                await asyncio.sleep(0.5)
            if ticked:
                logger.info("[world_tick] 本轮 tick 完成: %d/%d 个用户", ticked, len(users))
        except Exception as exc:
            logger.exception("[world_tick] 主循环异常: %s", exc)
```

- [ ] **Step 4: 语法检查**

Run: `cd backend && python -c "import py_compile; py_compile.compile('funcation/world_tick_scheduler.py', doraise=True); print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add backend/funcation/world_tick_scheduler.py
git commit -m "feat(world): 后台调度器公共世界每轮每 world 只演化一次 + 各用户补未见影响

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 11: 后端联调验证（/chat + /chat/stream）

**Files:** 无新改动，纯验证

- [ ] **Step 1: 启动后端**

Run: `cd backend && source .venv/Scripts/activate && uvicorn api.api:app --host 127.0.0.1 --port 8000 &`（后台启动）
Expected: 启动日志含 `Application startup complete`，无 ALTER 报错（`current_world_mode` 列应已迁移）

- [ ] **Step 2: 非流式 `/chat` 打通**

Run:
```bash
cd backend && source .venv/Scripts/activate && python -c "
from fastapi.testclient import TestClient
from api.api import app
from funcation.auth import create_access_token
c = TestClient(app)
h = {'Authorization':'Bearer ' + create_access_token({'sub':'1'})}
r = c.post('/chat', json={'message':'你好'}, headers=h)
print(r.status_code, list(r.json().keys()))
assert r.status_code == 200
assert 'reply' in r.json() or 'error' in r.json()
print('OK')
"
```
Expected: `OK`

- [ ] **Step 3: 流式 `/chat/stream` 首 token 正常**

Run:
```bash
cd backend && source .venv/Scripts/activate && python -c "
import requests
from funcation.auth import create_access_token
h = {'Authorization':'Bearer ' + create_access_token({'sub':'1'})}
r = requests.post('http://127.0.0.1:8000/chat/stream', json={'message':'在吗'}, headers=h, stream=True, timeout=60)
got_token = False
for line in r.iter_lines():
    if line and b'token' in line:
        got_token = True
        break
print('first_token', got_token)
assert got_token
print('OK')
"
```
Expected: `OK`（首 token 到达）

- [ ] **Step 4: 公共世界共享演化场景**

Run:
```bash
cd backend && source .venv/Scripts/activate && python -c "
from fastapi.testclient import TestClient
from api.api import app
from funcation.auth import create_access_token, SessionLocal, User
c = TestClient(app)
# 两个 token：admin=1 与一个测试 approved 用户
t1 = create_access_token({'sub':'1'})
h1 = {'Authorization':'Bearer '+t1}
# A 触发 force tick 公共世界
r = c.post('/world/tick', json={'force':True}, headers=h1)
print('A tick', r.json().get('action'), r.json().get('mode'))
assert r.json().get('mode')=='public'
# A 当天再非 force tick 应 skipped（幂等）
r2 = c.post('/world/tick', json={'force':False}, headers=h1)
print('A tick2', r2.json().get('action'))
assert r2.json().get('action')=='skipped'
print('OK')
"
```
Expected: `OK`（公共世界幂等生效）

- [ ] **Step 5: 停止后端**

Run: 根据进程情况 `kill` 掉 8000 端口的 uvicorn（或用启动时记录的 PID）

- [ ] **Step 6: 若有改动则 Commit（否则跳过）**

若联调发现并修复了 bug，单独 commit；否则无操作。

---

## Task 12: 前端类型与 API 层

**Files:**
- Modify: `front/src/types/api.ts:98-107`（`World`）
- Modify: `front/src/api/world.ts`

- [ ] **Step 1: 类型加 WorldMode + World 字段**

在 `front/src/types/api.ts` 的 `World` 接口（`:98`）处替换为：

```typescript
export type WorldMode = 'public' | 'private'

export interface World {
  id: string
  name: string
  description?: string
  background?: string
  world_event?: {
    title?: string
    impact?: number
  }
  forked_private?: boolean
}
```

- [ ] **Step 2: api/world.ts 加新函数**

在 `front/src/api/world.ts` 末尾追加：

```typescript
export const joinPublicWorld = (worldId: string) => {
  return request<{ message: string; mode: WorldMode }>('/world/join-public', {
    method: 'POST',
    body: JSON.stringify({ world_id: worldId }),
  })
}

export const forkPrivateWorld = (worldId: string) => {
  return request<{ message: string; mode: WorldMode }>('/world/fork-private', {
    method: 'POST',
    body: JSON.stringify({ world_id: worldId }),
  })
}

// 管理员世界 CRUD
export const adminCreateWorld = (data: {
  id: string
  name: string
  description?: string
  background?: string
  world_event?: { title?: string; impact?: number }
}) => {
  return request<{ message: string; world: World }>('/admin/world/create', {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export const adminUpdateWorld = (data: {
  world_id: string
  name?: string
  description?: string
  background?: string
  world_event?: { title?: string; impact?: number }
}) => {
  return request<{ message: string; world: World }>('/admin/world/update', {
    method: 'PUT',
    body: JSON.stringify(data),
  })
}

export const adminDeleteWorld = (worldId: string) => {
  return request<{ message: string }>('/admin/world/delete', {
    method: 'DELETE',
    body: JSON.stringify({ world_id: worldId }),
  })
}
```

并在文件顶部 import 处补 `WorldMode`：

```typescript
import type { World, WorldInteractionsSnapshot, WorldMode } from '@/types/api'
```

- [ ] **Step 3: 让 `getCurrentWorld` 返回 type 带 mode**

把 `front/src/api/world.ts:15-17` 的 `getCurrentWorld` 改为：

```typescript
export const getCurrentWorld = () => {
  return request<{ world: World; mode: WorldMode }>('/world/current')
}
```

- [ ] **Step 4: 类型检查**

Run: `cd front && npm run type-check`
Expected: 无新增类型错误（已有的与本次无关的错误可忽略，确认本次改动不引入新错）

- [ ] **Step 5: Commit**

```bash
git add front/src/types/api.ts front/src/api/world.ts
git commit -m "feat(world): 前端 WorldMode 类型 + join/fork/admin CRUD API

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 13: AboutView 世界切换 UI 改造

每世界卡片「🌐加入公共」+「🔒开私人副本」两按钮，当前选中标 mode，私人态可切回公共。

**Files:**
- Modify: `front/src/views/AboutView.vue:17-42`（世界观 section 模板）
- Modify: `front/src/views/AboutView.vue:186-320`（script：imports / state / handlers）

- [ ] **Step 1: 改模板：每世界卡片双按钮 + mode 标记**

把 `front/src/views/AboutView.vue:17-42` 的世界观 section 改为：

```html
        <!-- 世界观 -->
        <section class="glass-card">
          <h2><span>🌍</span> 世界观设置</h2>
          <div v-if="currentWorld" class="current-world">
            <strong>{{ currentWorld.name }}</strong>
            <span class="world-mode-tag" :class="worldMode">
              {{ worldMode === 'private' ? '🔒 私人世界' : '🌐 公共世界' }}
            </span>
            <p>{{ currentWorld.description }}</p>
            <p v-if="currentWorld.background" class="world-bg">{{ currentWorld.background }}</p>
            <div v-if="currentWorld.world_event" class="world-event">
              当前事件：{{ currentWorld.world_event.title }}
              <span v-if="currentWorld.world_event.impact">
                (影响 {{ currentWorld.world_event.impact > 0 ? '+' : '' }}{{ currentWorld.world_event.impact }})
              </span>
            </div>
          </div>
          <div class="world-list">
            <div v-for="w in worlds" :key="w.id" class="world-card" :class="{ active: currentWorld?.id === w.id }">
              <div class="world-card-head">
                <span class="world-name">{{ w.name }}</span>
                <span v-if="w.forked_private" class="forked-tag">已有私人副本</span>
              </div>
              <p class="world-desc">{{ w.description }}</p>
              <div class="world-card-actions">
                <button
                  class="btn small"
                  :disabled="loadingWorld || (currentWorld?.id === w.id && worldMode === 'public')"
                  @click="handleJoinPublic(w.id)"
                >🌐 加入公共</button>
                <button
                  class="btn small"
                  :disabled="loadingWorld"
                  @click="handleForkPrivate(w.id)"
                >🔒 开私人副本</button>
              </div>
            </div>
          </div>
        </section>
```

- [ ] **Step 2: 改 script：imports + state**

把 `front/src/views/AboutView.vue` 的 API import（`:186-190`）补 `joinPublicWorld` / `forkPrivateWorld`：

```typescript
  getWorlds,
  getCurrentWorld,
  switchWorld,
  joinPublicWorld,
  forkPrivateWorld,
  getWorldInteractions,
  simulateWorldInteraction,
```

把 type import（`:198`）补 `WorldMode`：

```typescript
import type { World, WorldInteractionsSnapshot, NpcRelationship, WorldMode } from '@/types/api'
```

在 state 区（`:200-209` 附近）加：

```typescript
const worldMode = ref<WorldMode>('public')
```

- [ ] **Step 3: 改 script：加载时读 mode**

把加载世界的 `Promise.all`（`:265-270`）改为：

```typescript
  const [worldsRes, worldRes] = await Promise.all([
    getWorlds(),
    getCurrentWorld(),
  ])
  worlds.value = worldsRes.worlds ?? []
  currentWorld.value = worldRes.world
  worldMode.value = worldRes.mode ?? 'public'
```

- [ ] **Step 4: 改 script：新增 join/fork handlers，旧 handleSwitchWorld 保留为 join 别名**

把 `handleSwitchWorld`（`:308-317`）替换为三个 handler：

```typescript
const handleJoinPublic = async (worldId: string) => {
  loadingWorld.value = true
  try {
    await joinPublicWorld(worldId)
    const res = await getCurrentWorld()
    currentWorld.value = res.world
    worldMode.value = res.mode ?? 'public'
    toolMessage.value = `已加入「${res.world.name}」公共世界`
  } finally {
    loadingWorld.value = false
  }
}

const handleForkPrivate = async (worldId: string) => {
  loadingWorld.value = true
  try {
    await forkPrivateWorld(worldId)
    const res = await getCurrentWorld()
    currentWorld.value = res.world
    worldMode.value = res.mode ?? 'private'
    // 刷新 forked_private 标记
    const worldsRes = await getWorlds()
    worlds.value = worldsRes.worlds ?? []
    toolMessage.value = `已开启「${res.world.name}」私人世界`
  } finally {
    loadingWorld.value = false
  }
}

// 旧调用兼容（如别处仍用 switchWorld）
const handleSwitchWorld = (worldId: string) => handleJoinPublic(worldId)
```

- [ ] **Step 5: 加样式（world-card / mode-tag）**

在 `front/src/views/AboutView.vue` 的 `<style>` 里（`.world-list` 附近，`:480`）追加：

```css
.world-mode-tag {
  display: inline-block;
  margin-left: 8px;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 12px;
  background: rgba(255,255,255,0.1);
}
.world-mode-tag.private { background: rgba(255,180,80,0.2); }
.world-mode-tag.public { background: rgba(120,200,255,0.2); }
.world-card {
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 12px;
  padding: 12px;
  margin-bottom: 10px;
}
.world-card.active { border-color: rgba(120,200,255,0.6); }
.world-card-head { display: flex; justify-content: space-between; align-items: center; }
.world-name { font-weight: 600; }
.forked-tag { font-size: 11px; color: rgba(255,180,80,0.9); }
.world-desc { font-size: 13px; opacity: 0.8; margin: 6px 0; }
.world-card-actions { display: flex; gap: 8px; }
.btn.small { padding: 4px 10px; font-size: 13px; }
```

- [ ] **Step 6: 类型检查 + 构建**

Run: `cd front && npm run build`
Expected: 构建通过（type-check + build）

- [ ] **Step 7: Commit**

```bash
git add front/src/views/AboutView.vue
git commit -m "feat(world): AboutView 世界卡片支持加入公共/开私人副本

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 14: AdminView 世界管理表单

**Files:**
- Modify: `front/src/views/AdminView.vue`（在现有 admin 面板加世界管理区块）

- [ ] **Step 1: 读 AdminView 现有结构**

Run: `cd front && head -60 src/views/AdminView.vue`
Expected: 了解现有结构（用户审批/配额区块），找到合适插入点。

- [ ] **Step 2: 加世界管理区块模板**

在 `front/src/views/AdminView.vue` 模板中合适位置（如用户管理 section 之后）插入：

```html
    <section class="admin-card">
      <h2>🌍 世界管理</h2>
      <div class="world-form">
        <input v-model="newWorld.id" placeholder="世界 id（英文）" />
        <input v-model="newWorld.name" placeholder="名称" />
        <input v-model="newWorld.description" placeholder="简介" />
        <textarea v-model="newWorld.background" placeholder="背景设定" rows="2"></textarea>
        <button class="btn primary" :disabled="creatingWorld" @click="handleCreateWorld">创建世界</button>
      </div>
      <div v-for="w in adminWorlds" :key="w.id" class="admin-world-item">
        <strong>{{ w.name }}</strong> <span class="muted">({{ w.id }})</span>
        <button class="btn danger small" @click="handleDeleteWorld(w.id)">删除</button>
      </div>
    </section>
```

- [ ] **Step 3: 加 script 逻辑**

在 `front/src/views/AdminView.vue` 的 `<script setup>` 中加：

```typescript
import { ref, onMounted } from 'vue'
import { getWorlds, adminCreateWorld, adminDeleteWorld } from '@/api'
import type { World } from '@/types/api'

const adminWorlds = ref<World[]>([])
const newWorld = ref({ id: '', name: '', description: '', background: '' })
const creatingWorld = ref(false)

const loadAdminWorlds = async () => {
  const res = await getWorlds()
  adminWorlds.value = res.worlds ?? []
}

const handleCreateWorld = async () => {
  if (!newWorld.value.id || !newWorld.value.name) return
  creatingWorld.value = true
  try {
    await adminCreateWorld({
      id: newWorld.value.id,
      name: newWorld.value.name,
      description: newWorld.value.description,
      background: newWorld.value.background,
    })
    newWorld.value = { id: '', name: '', description: '', background: '' }
    await loadAdminWorlds()
  } finally {
    creatingWorld.value = false
  }
}

const handleDeleteWorld = async (worldId: string) => {
  if (!confirm(`确认删除世界 ${worldId}？`)) return
  await adminDeleteWorld(worldId)
  await loadAdminWorlds()
}

onMounted(loadAdminWorlds)
```

注意：若 AdminView 已有 `onMounted` / 已 import `ref`/`getWorlds`，合并去重，不要重复声明。

- [ ] **Step 4: 加样式（如需）**

在 `<style>` 追加（若已有 `.admin-card`/`.btn` 样式可省略）：

```css
.world-form { display: flex; flex-direction: column; gap: 8px; margin-bottom: 16px; }
.world-form input, .world-form textarea { padding: 6px; }
.admin-world-item { display: flex; justify-content: space-between; align-items: center; padding: 8px 0; border-bottom: 1px solid rgba(255,255,255,0.08); }
.muted { opacity: 0.6; font-size: 12px; }
```

- [ ] **Step 5: 构建**

Run: `cd front && npm run build`
Expected: 构建通过

- [ ] **Step 6: Commit**

```bash
git add front/src/views/AdminView.vue
git commit -m "feat(world): AdminView 世界管理（创建/删除世界定义）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 15: 文档同步

**Files:**
- Modify: `CLAUDE.md`
- Modify: `backend/CLAUDE.md`
- Modify: `front/CLAUDE.md`
- Modify: `ROADMAP.md`

- [ ] **Step 1: 根 `CLAUDE.md` 加公共/私人世界一节**

在 `CLAUDE.md` 的"多剧情系统"或合适章节后新增一节：

```markdown
### 公共世界 vs 私人世界

用户对任意世界可二选一：**公共实例**（共享演化）或 **私人副本**（独立演化）。

**数据模型**:
- world_state 按 (user, mode) 路由：public → `data/world_state/{world_id}.json`（共享），private → `data/world_state/{user_id}/{world_id}.json`
- `User.current_world_mode`：`public` | `private`（默认 public）
- 角色 memory 加 `seen_world_event_ids`：公共世界补影响去重

**tick 解耦（方案 B）**:
- `world_event_agent.evolve_world(mc, world_def, user_id, mode, force)` — 纯世界演化（推进事件/生成/天气/NPC 互动），公共世界按 `last_tick_date` 当天幂等
- `world_event_agent.apply_world_impact_to_user(mc, user_id, character, world_def, notifications, mode)` — per-user 角色影响，公共世界用 `seen_world_event_ids` 去重
- 旧 `tick(mc, user_id, character, world_def, force)` 保留为 shim，按 mode 自动路由（`/chat`、`/chat/stream`、调度器、`/world/tick` 调用点无需感知 mode）

**后台调度器**: 公共世界每轮每 world_id 只 `evolve_world` 一次（去重），所有活跃用户补各自未见影响；私人世界按 (user,world) 演化+全量影响。

**API 变更**:
- `GET /worlds` — 每世界附 `forked_private`
- `GET /world/current` — 返回 `{world, mode}`
- `POST /world/join-public` `{world_id}` — mode=public
- `POST /world/fork-private` `{world_id}` — 建私人空副本 + mode=private
- `POST /admin/world/create` / `PUT /admin/world/update` / `DELETE /admin/world/delete` — admin 世界定义 CRUD
- 现有 `/world`、`/world/events`、`/world/interactions`、`/world/interaction/simulate`、`/world/event/*`、`/world/tick` 全部按 mode 路由
- 旧 `POST /world/switch` 保留（不改 mode）

**前端**: `AboutView.vue` 世界卡片「🌐加入公共」+「🔒开私人副本」；`AdminView.vue` 世界 CRUD。
```

- [ ] **Step 2: `backend/CLAUDE.md` 同步 tick 解耦与 world_state 路由**

在 `backend/CLAUDE.md` 的 World Event System 小节补充：

```markdown
### 公共/私人世界与 tick 解耦

- `MemoryCenter.load_world_state(world_id, user_id, mode)` / `save_world_state(...)` 按 (user,mode) 路由：private → `data/world_state/{user_id}/{world_id}.json`。
- `world_event_agent.tick()` 已拆为 `evolve_world()`（纯世界演化，公共按天幂等）+ `apply_world_impact_to_user()`（per-user 影响，公共用 `seen_world_event_ids` 去重）。`tick()` 保留为 shim。
- `world_tick_scheduler` 公共世界每轮每 world 只演化一次。
- 角色 memory 字段 `seen_world_event_ids` 用于公共世界已读追踪。
```

- [ ] **Step 3: `front/CLAUDE.md` 同步世界 API 与 UI**

在 `front/CLAUDE.md` 的 Backend Integration 端点列表补充 `/world/join-public`、`/world/fork-private`、`/admin/world/*`，并在 App Structure 注明 AboutView/AdminView 的世界管理职责。

- [ ] **Step 4: `ROADMAP.md` 更新**

把公共/私人世界条目标记为"已完成 MVP"（或对应状态）。

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md backend/CLAUDE.md front/CLAUDE.md ROADMAP.md
git commit -m "docs(world): 同步公共/私人世界文档

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Self-Review 记录

- **Spec 覆盖**：设计文档第 4-9 节均有对应 Task（4.1→T1，4.2→T2/T3，4.3→T4，5→T5/T6，6→T7/T10/T11，7→T7/T8/T9，8→T12/T13/T14，9→T1 迁移，10→T11）。
- **占位符扫描**：无 TBD/TODO；每个代码步均含完整代码。
- **类型一致性**：`get_user_world_mode` / `fork_private_world` / `evolve_world` / `apply_world_impact_to_user` 在定义 Task 与调用 Task 签名一致；前端 `WorldMode` 在 types/api.ts 与 world.ts 一致。
- **已知风险点**：Task 7 Step 2 的 interaction_agent 改造需先读函数全文确认所有 `load_world_state` 调用点；Task 9 Step 3 已规避 FastAPI 双 body 问题。
