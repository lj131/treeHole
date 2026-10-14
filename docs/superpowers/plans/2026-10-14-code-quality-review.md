# 代码质量把控实录 & 团队技术提升报告

> 2026-10-14 · 一次"拿自己写的代码开刀"的评审

## 0. 先说这份文档怎么来的

团队要求"资深开发者的指导和代码质量把控"。我没有讲通用最佳实践，
而是**对我今天新写的三个模块做了一次严格评审**（其中 4 个缺陷是我自己写的）。

结果是：**找到 6 个 P1，其中 1 个会让整个主动消息功能在第 5 条之后静默失效**。
所有问题都核实过、修好了、带了回归测试，并且**验证过"测试能失败"**。

这份文档的价值不在"发现了几个 bug"，而在**从这些 bug 里提炼出的 5 条可复用规矩** ——
那才是团队技术水平真正能带走的东西。

---

## 1. 评审结果：6 个缺陷

### 1.1 最致命的：`today_count` 终身累计

```python
# funcation/proactive/proactive_decision.py（修前）
today_count = proactive.get("today_count", 0)
if today_count >= 5:
    return False        # ← 本意是"今天最多 5 条"
```

这个字段**从来没有按天清零** —— `create_default_memory` 置 0 之后只 `+1`，
全仓没有任何地方重置它。

于是它的实际含义变成了「**这个角色一辈子最多主动发 5 条**」，
第 6 条起主动消息和梦境投递**永久静默，且不报任何错**。

**真实数据佐证**（`data/memories/1/linwan.json`）：

```json
"proactive": {
  "last_time": "2026-10-12T14:03:25",
  "today_count": 1,        ← 10-12 发的，永远不会归零
  "last_trigger": "world_event"
}
```

这个角色这辈子只剩 4 条主动消息。

**修法**：计数旁边必须带 `count_date`，跨天先视为 0。

### 1.2 dry-run 漏传到底

```python
# funcation/disk_cleanup.py（修前）
def run_startup_cleanup(data_dir="data", dry_run=False):
    result["quarantine"] = cleanup_quarantine_dirs(data_dir, dry_run=dry_run)  # 传了
    result["worker_log_freed"] = truncate_worker_log(data_dir)               # ← 漏了
```

dry-run 模式下隔离目录是"预演"，**worker.log 却被真实截断了**。
"先看会删什么再动手"的安全承诺，在日志这一项上不成立。

### 1.3 日志截断用 replace，而写方是长驻追加

```python
# 修前
tmp = path + ".tmp"
with open(tmp, "wb") as f: f.write(tail)
os.replace(tmp, path)          # ← worker 是 open(..., "ab") 长驻追加的
```

- **POSIX**：replace 后 worker 的 fd 指向已被 unlink 的旧 inode，
  之后所有日志写进**黑洞**，直到 worker 重启
- **Windows**：replace 一个被占用的文件直接 `PermissionError`，
  被 except 吞掉后返回 0 —— 日志永远超阈值、永远"截断失败"

**修法**：原地 `os.truncate`（保留 inode）。
回归测试用"**一直开着追加 fd 模拟 worker**"钉住这条。

### 1.4 lost update（我自己写的）

```python
# dream_agent.ensure_dream_pending（修前）
memory_data = mc.load_memory(...)      # ① 开头 load 一份快照
if not _dream_due(memory_data): return
...
text = generate_dream(...)             # ② 中间隔一次数秒到数十秒的 LLM 调用
...
mc.save_memory(..., memory_data)       # ③ 用 ① 的旧快照整包回写
```

② 期间用户聊天链路的 `update_last_chat_time`、状态更新等也在写同一个 JSON ——
③ 会把它们**全部覆盖**。

**修法**：落盘前重新 load，只 merge 自己负责的字段。

### 1.5 用字符串切片比日期（我自己写的）

```python
# dream_agent._dream_due（修前）
if last_chat[:10] <= last_dream_date:   # ← 靠隐式格式契约
```

现在是本地 naive ISO 字符串，两边自洽所以**不会炸**。
但任何格式漂移（换 UTC、带时区后缀、紧凑格式）都会让判定**静默失效**，
而且会被 `ensure_dream_pending` 的 except 吞成 warning，更难发现。

**修法**：`datetime.fromisoformat(raw).date()`。

### 1.6 裸奔的 async 入口

```python
# proactive_engine.run（修前）
def run(mc, user_id, character, world):
    memory_data = mc.load_memory(...)
    ...
    message = proactive_message_agent.generate_message(...)   # ← LLM 调用
    ...                                                       # ← 无 try/except、无锁、无日志
```

三个后果：
- LLM 超时直接冒到 `/proactive` → **用户看到 500**，而不是"今天没有主动消息"
- 用户开两个标签页 → 双倍 LLM 花费、`today_count` 各基于旧值 +1、两份旧快照互覆
- 零日志 → "用户说没收到主动消息"时**无从定位**

---

## 2. 提炼出的 5 条团队规矩

| # | 规矩 | 反面教材 | 怎么落地 |
|---|---|---|---|
| **1** | **修 bug 必须带回归测试，且要验证"测试能失败"** | 只改代码不写测试 → 半年后又被改回去 | 把修复临时退回旧行为，确认测试**真的红** |
| **2** | **在旧代码上加功能前，先确认依赖的判定还在工作** | 我把梦境建在坏掉的 `today_count` 上 | 新功能用到旧代码的阈值/计数时，**先看它清零逻辑** |
| **3** | **dry-run 必须一路透传到底** | 漏一层 → "预演"其实真删了 | 每个子函数都收 `dry_run` 参数；测试断言"dry-run 前后字节不变" |
| **4** | **长驻追加的日志只能原地 truncate** | replace 换文件 → POSIX 写进黑洞 / Windows 永远失败 | 回归测试：开着一个追加 fd，截断后继续写能读到 |
| **5** | **裸奔的 async 入口 = 线上 500** | 无 try/except → LLM 超时 500；无锁 → 双倍调用 | try/except + 并发锁 + debug 日志，三件套 |

### 还有几条环境层面的（踩过三次以上）

- `os.remove` 会被环境拦（还可能抛 `SystemExit`，`except Exception` 接不住）
  → 清理逻辑写成 **best-effort**（`except (Exception, SystemExit)` + 记日志）
- chromadb 持 sqlite 句柄，`release_client()` 放不掉 → **别 rename 数据目录**
- **本机全绿 ≠ CI 会绿** → 推前跑 `VOICE_CLONE_VENV=<不存在路径> pytest -q`
- **只看文件大小不能证明"有声音"** → 验音频必须量 peak/rms

---

## 3. 当前代码质量基线

| 指标 | 数值 |
|---|---|
| 后端 pytest | **389 passed**（本机 + 模拟 CI 均通过） |
| 前端 type-check / lint | 0 / 0 |
| 前端 vitest | 138 |
| 测试覆盖率 | 本次 4 个新模块，缺陷集中在**集成接缝处**而非纯函数 |
| 真实数据隔离 | ✅ 测试不污染 `data/chroma`（12 集合 / 22 记录） |

### 仍欠的（不建议现在做，但要知道）

| 项 | 状态 |
|---|---|
| §3.4 request-scoped cache | 一次 `/chat` 把同一记忆文件 load→改→save 8-10 次 |
| `.rag.json` 并发写锁 | 当前单进程 asyncio 顺序执行够用；多 worker 部署要补 |
| `detect_trigger` 就地清 flag 的历史写法 | 4 个旧分支都这样，契约只活在注释里 |
| 顶层函数超时控制 | LLM 无超时参数时为库默认值 |

---

## 4. 给团队的下一步建议

### 立即可做（把规矩变成机制）

1. **给 `pytest` 加一个"评审清单"钩子**：改动文件里出现"删除/替换文件"的写法，
   CR 里自动贴出规矩 4 的提醒。
2. **每个 bug fix 的 commit message 必须写"原 bug 是什么表现"** ——
   不写清楚症状的修复，后人无法判断是否复发。
3. **新增会写共享状态的公开函数时，先问三个问题**：
   谁会并发调？失败要不要影响主流程？删/改之前要不要 dry-run？

### 中期（技术债，按 ROI 排）

1. **§3.4 request-scoped cache** —— 直接消掉本次发现的"lost update"整类问题
2. **主动消息链路加超时与熔断** —— LLM 不可用时主动消息静默降级
3. **把 `detect_trigger` 的"就地清 flag"统一改成"返回待清标记"**

---

## 5. 结束语

这轮最值得记住的不是那 6 个 bug，而是这条：

> 最致命的那个 bug **不是我引入的**，但我今天把新功能建在了它上面。
> 如果我不评审自己的代码，它还会继续躺着，
> 而我的梦境日记会一直"看起来能跑"。

技术提升不来自"知道更多最佳实践"，而来自**每次写完代码后真的回头审它一遍**，
并且把审出来的东西变成**测试和规矩**，而不是只变成一次修复。

---

*配套材料：`docs/superpowers/plans/2026-10-14-dream-diary.md`（功能实现）、
`backend/tests/test_dream.py` 与 `test_disk_cleanup.py` 的"回归测试"小节。*
