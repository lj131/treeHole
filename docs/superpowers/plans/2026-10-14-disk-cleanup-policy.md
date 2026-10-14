# 磁盘清理策略（P2 §3.2）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 `backend/data/` 一个清理策略。它被 `.gitignore`，一直在长也没人注意。

**Architecture:** 一条 `funcation/disk_cleanup.py`，进程启动时跑一次（后台线程，绝不阻塞启动），
另给一个手动脚本 `scripts/cleanup_disk.py`（带 `--dry-run`）。

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `backend/funcation/disk_cleanup.py` | **新增** | 隔离目录清理 + worker 日志截断 |
| `backend/scripts/cleanup_disk.py` | **新增** | 手动清理（`--days` / `--dry-run`） |
| `backend/api/api.py` | 修改 | lifespan 启动时跑一次 |
| `backend/tests/test_disk_cleanup.py` | **新增** | 14 条测试 |

---

## Task 1: 摸清现状

- [x] 实测 `data/` 454MB：`openvoice/` 432M（权重，**故意留着**）、
      `chroma/` 9.3M（活跃索引）、**隔离残留 12M**、`tmp/clone/worker.log` 105K
- [x] `data/voice_refs/` 空的（无孤儿音频）
- [x] **发现一个自己引入的问题**：克隆 worker 的日志是 `open(..., "ab")` **只追加不轮转**

## Task 2: 清理模块

- [x] `find_quarantine_dirs()` —— 按**前缀白名单**列隔离目录（`chroma_corrupt_*` / `chroma_new`），
      显式排除活跃 `chroma`
- [x] `cleanup_quarantine_dirs(max_age_days=30, dry_run=False)` —— 按保留期删 + 报释放字节
- [x] `truncate_worker_log()` —— 超过 1MB 只留尾部 200KB，从第一个完整行开始
- [x] `run_startup_cleanup()` —— **绝不抛**（清理失败不能影响启动）

## Task 3: 接进启动流程

- [x] lifespan 里 `asyncio.create_task(asyncio.to_thread(...))` —— 后台线程，不阻塞启动

## Task 4: 测试（14 条）

- [x] **核心安全**：`test_active_chroma_dir_is_never_removed` ——
      保留期 0 天（最激进）也不许碰活跃索引；活跃目录**都不该被列出来**
- [x] 前缀白名单外的目录（`chroma_backup_should_not_touch`）一个都不动
- [x] 保留期、dry-run、幂等、释放字节报告
- [x] 删不掉（`PermissionError`）只跳过不抛
- [x] `data/` 不存在、启动路径 best-effort
- [x] worker.log：超阈值截断 / 不超不动 / 截断后不留半行

## 最终验收

- [x] 前端零改动；后端两种环境全绿
- [x] lifespan 起停不阻塞不抛（实测后台清了 95 天前的旧目录）

## Self-Review

**1. Spec coverage**：§3.2 要的是"磁盘没有清理策略"——Task 1-4 给了策略 + 验证。✅
**2. Placeholder scan**：无占位，每个函数都有确切行为。✅
**3. 最大风险 = 删错目录**：用**前缀白名单**而不是模糊匹配，再加"显式排除活跃 chroma"
   双保险，并有保留期 0 天的最激进测试钉住。✅
**4. 顺手发现并修了自己引入的问题**（worker.log 无界增长）。✅
**5. 不过度设计**：没做成通用 GC（不扫 voice_refs 孤儿/chat_history 压缩），
   那些实测没有无界增长；也没删存量隔离目录（按保留期自然老化）。✅

---

## 执行结果（2026-10-14）

4 个 Task 全部完成，14 条测试全过。

### 实测数据

| 项 | 体积 | 处置 |
|---|---|---|
| `data/openvoice/` | 432M | 不动（重新下要 480MB 流量） |
| `data/chroma/` | 9.3M | **绝不碰**（活跃索引） |
| 隔离残留 | 12M | 按 30 天保留期自然老化 |
| `tmp/clone/worker.log` | 105K | 加截断（超 1MB 只留尾部 200KB） |

### 安全设计

1. **前缀白名单**（`chroma_corrupt_*` / `chroma_new`），绝不做模糊匹配 ——
   一个写错的 glob 就能把 `data/chroma` 连带删掉
2. **显式排除**活跃 `chroma` 目录名（双保险）
3. **保留期 30 天**，不是"见到就删"
4. **best-effort**：删不掉只跳过（Windows 文件锁 / 环境的删除保护）
5. **有 dry-run**，先看会删什么再动手

### 顺带清掉自己 e2e 留下的测试数据

- 1 个测试语音包 `克隆测试_mv7gh4y8`（engine=clone，无参考音频）——
  之前 e2e 脚本被 SIGTERM 打断，没走到删除。**只删我测试命名前缀的**
  （`克隆测试_` / `重启验证_` / `耗时测量_` / `出声验证_`），备份已留。

### 验证

- 后端 **366 passed / 1 skipped**（本机）、**367 passed**（模拟 CI）
- 前端零改动全绿
- lifespan 实测：后台线程清了 95 天前的旧目录（184K），**不阻塞、不抛**
- 磁盘：`data/` 453M（少掉刚被清的那 184K）

### 遇到的"假警报"

全量跑时本机报 `1 skipped`、模拟 CI 没有 —— 查下来是
`tests/test_edge_tts_compat.py::test_real_synthesis_works` 的**瞬态网络抖动**
（它设计成失败就 skip）。单独重跑即过，不是环境依赖 bug。

### 仍未做

- **存量 12M 隔离残留没主动删**：按保留期会自然老化。要立刻清就跑
  `scripts/cleanup_disk.py --days 0`。这是刻意的保守选择。
- `data/openvoice/` 480MB 权重没有大小/生命周期管理（需要模型就该留着）
