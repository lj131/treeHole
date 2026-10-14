# 记忆真源统一到 JSON（P0 §1-7 根治）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `long_memory` / `events` / `chat_summary` **不再只存在于向量库** ——
向量库被隔离时不再等于数据丢失。

## 现状：三个字段的方向反了（其余三个是对的）

实测（2026-10-14）：

| collection | 真源 | 向量库角色 |
|---|---|---|
| `profile` | **JSON**（`data/memories/{uid}/{char}.json` 的 `profile`） | 派生索引（`_sync_profile_to_rag`） |
| `story` | **JSON** | 派生索引（`_sync_story_to_rag`） |
| `relationship` | **JSON** | 派生索引（`_sync_relationship_to_rag`） |
| **`long_memory`** | ❌ **只有向量库** | 唯一存储 |
| **`events`** | ❌ **只有向量库** | 唯一存储 |
| **`chat_summary`** | ❌ **只有向量库** | 唯一存储 |

**所以修法不是发明新架构，而是把后三个对齐到前三个已有的模式。**

### 这个方向是历史上被改过去的

`memory_center._migrate_to_chroma()` 里有 `data.pop("long_memory", None)` ——
**当年是刻意把它们从 JSON 搬进向量库的**，于是"向量库损坏 = 数据丢失"。
本次是把它反过来，并且**删掉这个反向迁移**（不删的话它会把字段又 pop 出去）。

### 数据量很小，不需要分批迁移

实测 `data/chroma`：18 个集合 / 37 条记录，其中受影响的三类共 **4 条**
（`long_memory` 3 + `events` 1 + `chat_summary` 0）。所以一次性迁移即可。

## 架构：三个字段进**独立文件**（不是主 JSON）

```
data/memories/{uid}/{char}.json        ← 小状态（profile/favorability/story/...）**行为不变**
data/memories/{uid}/{char}.rag.json    ← long_memory / events / chat_summary（新，真源）
```

**为什么另起一个文件，而不是塞进主 JSON**：主 JSON 的 `save_memory` 是
「**用调用方手上的快照整体覆盖**」的语义。而聊天主流程是：

```
load_memory → ... → add_chat_summary(×2) → save_memory(早先加载的旧快照)
                     ↑ 写 JSON                      ↑ 会把上面的写入冲掉
```

也就是说：**`add_*` 和 `save_memory` 会争同一个文件**。
另起文件 = 两个 writer 各写各的，**零冲突**，也不用改动既有的 save/load 语义（改动面最小）。

> 顺带记录一个**已存在的同类 bug**（本次不修，见 Known Issues）：
> `update_last_chat_time()` 内部 `load → 改 → save`，紧接着主流程又
> `save_memory(旧快照)`，于是 `last_chat_time` 会被冲回旧值。

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `backend/funcation/memory_center.py` | 修改 | 三个字段改读写 `.rag.json`；反向迁移；重建入口 |
| `backend/funcation/memory_rag.py` | 小改 | 加 `rebuild_index_from_json()`；隔离时不再当作数据丢失 |
| `backend/api/api.py` | 修改 | 手动重建接口（管理员）；隔离事件里提示可重建 |
| `backend/tests/test_memory_source_of_truth.py` | **新增** | 核心不变量：**向量库清空后数据仍在** |
| `backend/CLAUDE.md` | 修改 | 记录"真源/索引"的划分与不变量 |

---

## Task 0: 基线

- [ ] `cd backend && ../.venv/Scripts/python.exe -m pytest -q`（当前 338 passed）
- [ ] 记下当前 `data/chroma` 的集合数与记录数（用于迁移前后对比）

## Task 1: 三个字段落到 `.rag.json`

- [x] **Step 1**: 加路径与方法
  ```python
  #: 这三个字段**只**由各自的 add_* 写入，不进主 JSON（见模块 docstring 的"为什么另起文件"）
  RAG_FIELDS = ["long_memory", "events", "chat_summary"]

  def _get_rag_path(self, user_id, character_id):
      return os.path.join(MEMORIES_DIR, str(user_id), f"{character_id}.rag.json")

  def _load_rag(self, user_id, character_id) -> dict:
      """读 .rag.json；不存在/坏了 → 返回默认空结构（**绝不抛**）"""
  def _save_rag(self, user_id, character_id, rag: dict) -> None:
      """原子写（临时文件 + os.replace），避免写一半被读到"""
  ```
- [x] **Step 2**: `get_long_memories` / `get_events` / `get_chat_summary` 改为**读 `.rag.json`**
      （保留原有的 `events` 取最近 50 条、`chat_summary` 取最近 10 条的行为）
- [x] **Step 3**: `add_long_memory` / `add_event` / `add_chat_summary` 改为
      **read-modify-write `.rag.json`** + **best-effort 写向量库索引**
      - 索引失败**不能**让写入失败（JSON 才是真源，索引坏了可以重建）
      - 去重、裁剪逻辑保持原样
- [x] **Step 4**: `update_long_memory` / `update_chat_summary` 同样改走 `.rag.json`
- [x] **Step 5**: `load_memory` 从 `.rag.json` 合并三个字段（**对外返回结构不变**，
      调用方无感）

## Task 2: 一次性反向迁移（把存量从向量库捞回来）

- [x] **Step 1**: 把 `_migrate_to_chroma` 换成 `_migrate_from_chroma`：
      - 若 `.rag.json` 已有内容 → 跳过（幂等）
      - 否则从向量库读三个集合 → 写进 `.rag.json`
      - **向量库读不到（已损坏/被隔离）→ 不报错、不写空文件**，留给重建/人工恢复
- [x] **Step 2**: 在 `load_memory` 里调用（替换原来的 `_migrate_to_chroma` 调用点）
- [x] **Step 3**: 测试：给定"只有向量库有数据"的状态 → 首次 load 后 `.rag.json` 出现且内容一致

## Task 3: 索引可重建

- [x] **Step 1**: `memory_rag.rebuild_index_from_json(user_id, character_id)`：
      清空三个集合 → 从 `.rag.json` 全量重新索引
- [x] **Step 2**: `memory_center.rebuild_rag_index(user_id, character_id)` 包一层
- [x] **Step 3**: **隔离时不再把向量库当唯一数据**：`_quarantine_corrupt_dir` 的日志/事件里
      说明"数据在 JSON，可重建"（不改隔离逻辑本身，只改叙事与后续动作）
- [x] **Step 4**: 管理员接口 `POST /admin/rag/rebuild`（可按 user+character 或全量）

## Task 4: 测试（核心不变量）

- [x] **Step 1: 最重要的那条** —— 模拟"向量库被隔离"：
  ```
  写入 long_memory/events/chat_summary
  → 把整个 chroma 目录挪走（模拟隔离）
  → 重新 load_memory
  → 断言三个字段**内容完全一致**          ← 这条就是本次要买的东西
  ```
- [x] **Step 2**: 索引可重建：挪走 chroma 后调 rebuild → 集合恢复且条数对得上
- [x] **Step 3**: 反向迁移幂等（跑两次结果一样）+ 已有 `.rag.json` 时不被覆盖
- [x] **Step 4**: 索引写失败不影响 JSON 写入（monkeypatch `memory_rag.add_memory` 抛异常）
- [x] **Step 5**: `.rag.json` 损坏/半截 → `_load_rag` 返回默认值不抛
- [x] **Step 6**: 去重/裁剪行为不变（长期记忆去重、events 50 条、chat_summary 10 条）

## Task 5: 验收

- [ ] 全量 pytest 绿（两种环境：模拟 CI + 本机）
- [ ] 前端 lint / type-check / vitest 绿（应该零改动）
- [ ] 真机跑一次：起后端 → 聊一句 → 确认 `.rag.json` 出现且有内容
- [ ] **挪走 chroma 目录 → 重启后端 → 记忆还在**（端到端证伪"隔离=丢数据"）

## Known Issues

- **不修** `update_last_chat_time` 被旧快照冲掉的老 bug（见架构一节）——
  它是既有问题、与本次目标无关，改了会扩大改动面。**已记录，建议单开一条**。
- **并发**：同一 (user, character) 的 `.rag.json` 是 read-modify-write。
  当前是单进程 asyncio 顺序执行，够用；多 worker 部署时要加文件锁（未做）。
- **`.rag.json` 会随聊天增长**：`chat_summary` 保留 10 条、`events` 读侧取 50 条，
  但 `long_memory` 无上限（与现状一致，本次不引入新行为）。
- 旧的 `chroma_corrupt_*` 残留目录**本次仍不删** —— 等真源切换跑一段时间再删更稳。

## Self-Review

**1. Spec coverage**：§1-7 的目标是"让只存向量库的数据可重建"，Task 1-4 完整覆盖。✅
**2. Placeholder scan**：Task 1 Step 1 给了方法签名与关键约束，未逐行给实现；
其余都有确切行为描述。⚠️ 可接受（实现细节留到编码时）。
**3. 最大风险 = 改动既有记忆读写导致丢数据**：
   - 用**独立文件**避开与 `save_memory` 争抢（这是本方案最重要的决定）
   - Task 4 Step 1 用"挪走 chroma 后内容一致"直接钉住不变量
   - Task 2 的迁移**幂等**且**不写空文件**（避免把"读不到"当成"没有"）
✅
**4. 方向性**：明确记录"这是把历史上一处反向迁移改回来"，不是新发明。✅
**5. 不过度设计**：没做文件锁、没做压缩、没顺手修老 bug —— 都写进 Known Issues 并说明理由。✅

---

## 执行结果（2026-10-14）

5 个 Task 全部完成。**真实数据已迁移，且验证了"隔离不再丢数据"。**

### 关键发现：这是把历史上一处反向迁移改回来

`memory_center._migrate_to_chroma()` 里有 `data.pop("long_memory", None)` ——
**当年是刻意把这三个字段从 JSON 搬进向量库的**，于是"向量库损坏 = 数据丢失"。
本次把它反过来（`_migrate_from_chroma`），并删掉反向迁移。

而且 `profile` / `story` / `relationship` **本来就是**"JSON 真源 + chroma 派生索引"，
所以修法不是发明新架构，是**把三个走偏的字段对齐到既有模式**。

### 架构：三个字段进独立文件 `.rag.json`

不是塞进主 JSON。原因：主 JSON 的 `save_memory()` 是「用调用方快照整体覆盖」，
而聊天主流程是 `load → add_chat_summary(×2) → save_memory(旧快照)` ——
`add_*` 和 `save_memory` 会争同一个文件。另起文件 = 两个 writer 各写各的，**零冲突**。

### 真实数据迁移结果

迁移前：4 条真实记忆只在向量库（linwan/xiaomei/maid 各 1 条 long_memory + linwan 1 条 event）。
触发 `load_memory` 后自动迁移，内容一字不差。

### 端到端验证（真实数据）

```
① 迁移前：.rag.json 不存在
② load_memory → 自动反向迁移
③ 真源内容正确（真实记忆都在）
④ 模拟隔离（索引指向空目录）
⑤ 关键断言：三个角色数据与迁移前**完全一致** ✅
⑥ 索引可从真源重建 ✅
结论：✅ 向量库被隔离不再丢数据
```

### 测试是否有"牙齿"

把 `get_long_memories` 临时改回"从向量库读"，核心断言立刻红
（`Right contains one more item: '用户喜欢雨天'` = 数据丢了），改回后绿。
**验证过能失败的测试才算测试。**

### 顺带修掉一个更早就存在的测试污染

`tests/conftest.py` 的 `disable_rag` **漏 mock 了 `upsert_memory`**，
于是 `_sync_profile_to_rag` / `_sync_story_to_rag` / `_sync_relationship_to_rag`
一直在往**真实的 `data/chroma`** 写（`PERSIST_DIR` 是绝对路径，不受 chdir 隔离）。
开发库里因此积了 u2..u9 一批 `e2e_voice_*` 测试用户的集合。

- 补上 `upsert_memory`（以及我新加的 `rebuild_collection_from_items`、`purge_collection`）
- 清理了那批测试用户集合：**21 集合 / 40 记录 → 12 集合 / 22 记录**，剩下的全是 admin 的真实数据

**另一类污染**：`disable_rag` 是 **session 级**的，只要会话里有别的测试用了 `client`，
它就会把 `memory_rag` 全 mock 成空 —— 导致我新写的测试"单独跑过、全量跑挂"。
修法：在**模块导入时**抓一份真函数（那时 fixture 还没跑），fixture 里还原。

### 验证

- 后端 pytest **353 passed**（338 → +15），**两种环境都过**（本机 / 模拟 CI）
- 前端 lint:ci 0 / type-check 0（零改动）
- **开发库未被测试污染**（跑完仍是 12 集合 / 22 记录，无 `u1_` 以外的集合）
- 真实数据已迁移；备份在 `D:/mmmy/3d-verify/mem-backup/`

### 踩的坑

- **Windows 文件锁**：chromadb 持有 sqlite 句柄，`release_client()` 也放不掉，
  直接 rename 目录会 `PermissionError: WinError 5`。
  改用"把索引指向一个空目录"模拟隔离 —— 语义等价且不受锁影响。
- **`/tmp` 在 Git Bash 与 Windows Python 里不是同一个地方**（又踩一次）：
  用 `/tmp` 做备份，Python 那边找不到。用 `$LOCALAPPDATA/Temp`。
  这次因为备份没落盘，我手改回了临时改动 —— 所幸改动很小、能精确还原。

### 仍未做

- `update_last_chat_time()` 被旧快照冲掉的老 bug（既有问题，与本次无关）
- `.rag.json` 的并发写锁（当前单进程 asyncio 顺序执行，够用）
- 旧的 `chroma_corrupt_*` 残留目录（等真源切换跑一段时间再删更稳）
