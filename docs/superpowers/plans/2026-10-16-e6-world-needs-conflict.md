# E6 世界需要"坏事" —— NPC 关系危机 + 角色来倾诉 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让世界**能变坏** —— NPC 之间会争吵、误会、关系恶化，并且**当事角色会来找用户倾诉**。

**为什么做这个:** 现在系统只会往好的方向走。查证结果：

- prompt 里**有**负向 delta 示例（争吵 -10 / 背叛 -20 / 误会 -5）
- 但**没有任何指令鼓励生成冲突**，LLM 默认倾向"和谐"
- 实测：NPC 关系只涨（50 → 51 → 55），`recent_interactions` 全是友好交流

**没有冲突就没有故事。** 所有陪伴类产品都"永远温柔" ——
有争吵、有关系危机、有角色跑来找你倾诉，才是"活着"和"哄你开心"的区别。

## Task 0: 现状（**已查证**）

| 事实 | 位置 |
|---|---|
| `run_interaction(mc, world, event, user_id, mode)` **拿到真实 user_id** | `world_event_agent.py:630` |
| `apply_interaction_result(..., user_id, mode)` 也能拿到 user_id | `interaction_agent.py:335` |
| 关系落地用 `_clamp(rel + delta)`，**支持负向** | `interaction_agent.py:364` |
| `detect_trigger` 是**优先级链**：dream → world_event → story → relation → state | `proactive_trigger.py` |
| 消息生成按 `trigger["trigger"]` 分支，有 `world_event_context` / `dream_context` 两个可选段 | `proactive_message_agent.py` |

**⚠️ 关键约束：NPC 互动记忆写在 `_SYSTEM_USER_ID` 下（世界级），但"来找用户倾诉"
必须写进真实用户的角色记忆。** 好在 `user_id` 一路传得下来。

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `backend/funcation/tension.py` | **新增** | **纯函数**：张力决策 + 冲突检测（可单测） |
| `backend/tests/test_tension.py` | **新增** | 张力决策 / 冷却 / 冲突检测边界 |
| `backend/funcation/interaction_agent.py` | 修改 | prompt 加张力引导；`apply_*` 里检测冲突并写通知 |
| `backend/funcation/proactive/proactive_trigger.py` | 修改 | 加 `conflict` 分支 |
| `backend/funcation/proactive/proactive_message_agent.py` | 修改 | 加 `conflict_context` |
| `backend/tests/test_conflict_proactive.py` | **新增** | 端到端：冲突 → 通知 → 触发 → 消息 |

## Task 1: 张力决策（**纯函数，这是可控性的关键**）

- [ ] `decide_tension(relationships, *, seed, last_conflict_date, today) -> int`
      - 返回 `0`（平和）/ `1`（摩擦）/ `2`（冲突）
      - **依据**：关系里的最低信任度（信任越低越易冲突）+ 是否有明显裂痕
        （favorability 明显低于初始 50）+ 冷却（距上次冲突 < N 天一律 0）
      - **确定性**：用 `seed` 做伪随机（**不用 `random` 模块** → 可测）
- [ ] `detect_conflict(result) -> list[dict]`
      - 从 `relationship_changes` 找负向明显的（`favorability_delta <= -5`
        或 `trust_delta <= -5`）
      - 返回 `[{from, to, severity, reason}]`
      - **severity**：1 = 小摩擦（-5..-9），2 = 明显冲突（≤ -10）
- [ ] `conflict_notice_payload(conflicts, *, today) -> dict | None`
      - 生成要写进角色记忆的通知结构

**为什么张力由代码决定而不是让 LLM 自由发挥**：
频率不可控 → 要么天天吵（用户烦），要么永远不吵（回到现状）。
代码决定"这次要不要有张力"，prompt 只负责"怎么吵得自然"。

## Task 2: prompt 引导

- [ ] `interaction_agent` 的 prompt 加「# 关系张力」段，按 `tension_level` 给不同指令：
      - `0`：允许小分歧，但整体友好
      - `1`：**应包含一次意见不合或小误会**（不是吵架）
      - `2`：**应包含一次明显的争吵 / 对立 / 失望**
- [ ] **必须同时给"修复"引导**：如果关系里有裂痕，允许本次**和解 / 缓和**
      —— 否则关系只会一路跌到底，世界会崩
- [ ] `simulate_interaction` 接受 `tension_level` 参数并注入 prompt

## Task 3: 冲突 → 用户通知

- [ ] `apply_interaction_result` 里：`detect_conflict(result)` 有结果时，
      给**参与冲突的角色**写 `memory["conflict_notice"]`
      - 只写**一方**（`from`，即"更想倾诉的那个"）—— 两边都来会很吵
      - **只在 `user_id` 是真实用户时写**（`_SYSTEM_USER_ID` 时跳过，避免污染）
      - 写进该用户的角色记忆（`mc.load_memory(user_id, char_id)` + save）
- [ ] 结构：`{"changed": True, "with": 对方名, "summary": ..., "severity": 2, "time": ...}`
- [ ] **冷却**：写入前检查 `last_conflict_date`，太近则不写

## Task 4: 触发器 + 消息

- [ ] `detect_trigger` 加 `conflict` 分支，**放在 dream 之后、world_event 之前**
      - 冲突是强情绪，该优先说；但 dream 有"昨晚"的时效性，不动它
      - **只读不清 flag**（同 dream 的理由：被冷却拦下不能丢）
- [ ] `proactive_message_agent` 加 `conflict_context`：
      - 要的是**吐槽/倾诉**，不是"事件报告"
      - 明确禁止：复述整个事件经过、像新闻播报
- [ ] 投递成功后清 `conflict_notice`（由 engine 调，同 dream 的模式）

## Task 5: 测试

- [ ] `test_tension.py`：
      - 冷却生效（最近冲突过 → 一律 0）
      - 信任低 → 更容易出张力
      - 有裂痕 → 更容易继续冲突
      - **确定性**：同 seed 同结果
      - `detect_conflict`：只挑明显负向 / severity 分档 / 正向变化不算冲突 /
        边界（-4 不算、-5 算）
- [ ] `test_conflict_proactive.py`：
      - 冲突 → 写进用户角色记忆（**且不写系统用户**）
      - 冷却期内不重复写
      - `detect_trigger` 优先返回 conflict
      - **只读不清 flag**（调两次 trigger 都还能拿到）
- [ ] **验证"测试能失败"**：去掉冷却 → 断言红；把 `-5` 改成 `-1` → 断言红

## 最终验收

- [ ] 后端全绿；前端不回归
- [ ] **真实调一次互动**（带张力）确认能产生负向 delta 与冲突通知
- [ ] 确认**不破坏**正常（无冲突时行为与之前一致）

## Self-Review

**1. Spec coverage**：要"关系能变坏" → Task 1-3；要"角色来倾诉" → Task 3-4。✅
**2. 最大风险 = 频率失控**：冲突太密用户会烦、关系会崩。
→ 代码侧决定张力 + 冷却 + prompt 里的修复引导。✅
**3. 不破坏现状**：`tension_level` 默认 0（平和），老路径行为不变。✅
**4. 可测性**：张力决策与冲突检测都是纯函数，不用随机模块。✅
**5. 不过度设计**：不做前端新页面（D4 的 `recent_interactions` 会自然显示冲突）、
不做关系修复的专门机制（prompt 允许和解即可）。✅

## Known Issues（预期）

- 张力决策依赖 LLM 真的按指令产生负向 delta（prompt 引导不是保证）
- 冲突只通知一方 → 另一方可能永远不"抱怨"，看起来不对称（可接受）
- 不做"用户介入调解"（那是更大的功能）
