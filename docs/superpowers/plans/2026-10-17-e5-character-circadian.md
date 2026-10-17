# E5 角色作息 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让角色**知道现在几点** —— 凌晨 3 点和她聊天，她应该有睡意而不是精神饱满。

**为什么做:** 实测（已查证）：`prompt.py` 只用了 `world_state.time_period`（**世界的**时间，
由 world tick 每天更新一次，可能和用户本地时间差很远）；角色设定里**没有**任何作息字段。
所以用户凌晨打开 App，看到的仍然是"傍晚的林婉"在精神饱满地秒回。

## Task 0: 现状（**已查证**）

| 事实 | 位置 |
|---|---|
| 角色设定字段只有 `id/name/description/personality/system_prompt/avatar` —— **无作息** | `data/characters/*.json` |
| prompt 里唯一的时间是 `world_state.time_period`（世界 tick 更新） | `prompt.py:431` |
| `character_state` 有 `mood`/`energy`，但**不和小时联动** | `memory_center` |

**关键决策：用哪个时间？**
用**用户本地时间**（`datetime.now().hour`），不用世界的 `time_period`。
理由：陪伴类产品的体感是"我半夜打开 App，她应该也在半夜"。
世界的 `time_period` 是设定在"夏天的校园"，且一天才 tick 一次，和用户当下无关。

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `backend/funcation/circadian.py` | **新增** | **纯函数**：时段划分 + prompt 提示文案 |
| `backend/tests/test_circadian.py` | **新增** | **每个时段边界** + 非法 hour + 上下文结构 |
| `backend/funcation/prompt.py` | 修改 | `build_system_prompt` 注入时间上下文 |

## Task 1: 时段划分（纯函数）

- [ ] `current_phase(hour) -> Phase`，`Phase` 含 `label` / `hint`（给 LLM 的行为指引）
- [ ] 时段（边界值必须明确，写进测试）：

| 小时 | label | 行为指引要点 |
|---|---|---|
| 0-4 | 凌晨 | 你本来在睡觉，被吵醒了 |
| 5-7 | 清晨 | 刚醒，还没完全清醒 |
| 8-10 | 上午 | 精神好 |
| 11-12 | 上午 | 临近午饭，可能饿了 |
| 13-17 | 下午 | 正常 |
| 18-21 | 傍晚 | 最可能聊天的时段，放松 |
| 22-23 | 深夜 | 该睡了，有点困 |

- [ ] `build_time_context(now=None) -> dict`
      - `{"phase": ..., "hour": ..., "hint": ..., "is_late_night": bool}`
      - `now` 可注入（测试固定时间，避免 flaky）

## Task 2: 接进 prompt

- [ ] `build_system_prompt` 加一段 `# 当前时间`：
      - 用 `circadian.build_time_context()`
      - 文案末尾必须带 **"你的角色设定优先，时间只影响状态和语气"** ——
        否则 LLM 可能过度强调"我很困"，把人设带跑
- [ ] **语气要克制**：时段只是**一条**信息，不能让它盖过人设
      （prompt 约定"角色设定优先，时段只影响状态与语气"）

## Task 3: 测试

- [ ] **每个时段边界全覆盖**（0/4/5/7/8/10/11/12/13/17/18/21/22/23）
- [ ] 非法 hour（-1 / 24 / None / "8"）不崩
- [ ] `is_late_night` 只在凌晨段为 True
- [ ] `build_time_context` 可注入 `now`
- [ ] **每个 phase 的 hint 都非空**（空 hint 会让 prompt 出现空段）
- [ ] **验证"测试能失败"**（用 Edit 不用 cp）：改一个边界 → 断言红

## 最终验收

- [ ] 后端全绿；前端不回归
- [ ] **真实验证**：构造深夜时间调 `build_system_prompt`，确认 prompt 里出现"被吵醒"
- [ ] 确认白天时段的行为和之前一致（不破坏现状）

## Self-Review

**1. Spec coverage**：要"角色知道现在几点" → Task 1-2。✅
**2. 最大风险 = 时段盖过人设**：角色凌晨说"我好困"可以，但不能变成"我在睡觉别烦我"
（用户还得得到回复）。→ Task 2 明确"人设优先，时段只影响状态与语气"，
且**不做"深夜不回复"**（那是更激进的设计，会破坏可用性）。✅
**3. 确定性**：`now` 可注入，测试不依赖真实时间。✅
**4. 不过度设计**：不做 per-角色作息表（角色设定里没有这个数据，加了要改 schema）、
不做 energy 联动（那是另一个系统）。✅
**5. 省 token**（**实现时偏离了，见下**）：本想平淡时段不注入。✅→⚠️

## ⚠️ 与方案的偏离（实现在这里，已确认）

第 5 条原本写"平淡时段（上午/下午）不注入，省 token"。**实现是全部注入。**
偏离理由：

1. 让角色知道"现在几点"对**一致性**有价值 —— 否则她可能在下午说"晚安"、
   在凌晨说"早上好啊"，这种违和比多 40 个 token 更伤
2. 保留"每个时段都有 hint"的简单结构，少一个"哪些时段算平淡"的判断条件

**结论：偏离是对的，方案第 5 条的假设（token 比一致性更重要）在这个场景下不成立。**
所以不回头改代码，只在这里记录，免得后来者困惑。

## Known Issues（预期）

- `character_state.energy` 不和时段联动（要做的话是另一项）
- 用户改了系统时区后，脚本判断的"深夜"也跟着变（这是**正确的**，按用户本地算）
- 不做"用户真的凌晨发消息时延迟到早上回"（可用性优先）
