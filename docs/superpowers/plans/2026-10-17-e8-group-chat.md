# E8 多人群聊 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把最小展示单位从"你和**某**角色"改成"你和**一群**角色" ——
你说话，主角答，**其他人可能插嘴**。

**为什么做:** D4 是"旁观 NPC 群聊"，E8 是**用户参与其中**。
现在每轮只有一个角色说话（`mc.get_user_current_character_id` 定的那个）。

## Task 0: 现状（**已查证**）

| 事实 | 位置 |
|---|---|
| 每轮只有一个说话者：`char_id = mc.get_user_current_character_id(user.id)` | `api.py:504` |
| `build_social_prompt_for_character()` 已给当前角色注入 NPC 社交上下文 | `interaction_agent.py:616` |
| `ChatRequest` 只有 `{message}` | `api.py:250` |
| SSE 事件：`{token}` / `{memories}` / `{done}` / `{error}` | `chat.ts` |

## 核心设计：**主链路不变，插嘴独立追加**

改"让一个 LLM 同时输出多个人说话"要把输出解析整个换掉，风险大。
所以：

1. **主答完全走原链路**（主角、原 prompt、原流式）→ **零回归风险**
2. SSE 的 `{token}` 多带 `speaker` / `speaker_name`（老前端忽略未知字段，照常工作）
3. 主答应完后，**只有命中时才**追加一次小 LLM 调用生成插嘴
   → 新事件 `{"interjection": {"speaker": id, "name": 名, "text": 台词}}`
4. 前端把插嘴渲染成一条**独立消息**（带那个人的头像）

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `backend/funcation/group_chat.py` | **新增** | **纯函数**：选插嘴者 + 是否插嘴 |
| `backend/tests/test_group_chat.py` | **新增** | 选人约束 / 概率 / 确定性 / 边界 |
| `backend/api/api.py` | 修改 | `ChatRequest` 加 `group?`；token 带 speaker；追加插嘴 |
| `front/src/api/chat.ts` | 修改 | 加 `speaker` / `onInterjection` |
| `front/src/types/api.ts` | 修改 | `ChatMessage.speaker` |
| `front/src/stores/chatStore.ts` | 修改 | 记 speaker + 插嘴入列 |
| `front/src/views/Chat.vue` | 修改 | 群聊开关 + 每条消息显示说话者 |

## Task 1: 选谁插嘴（纯函数）

- [ ] `pick_heckler(candidates, *, primary_id, seed) -> str | None`
      - `candidates` 是群成员（除主角外的角色 id 列表）
      - 排除 `primary_id`；空列表返回 `None`
- [ ] `should_heckle(seed, *, chance=25) -> bool`
      - **25%**：别每轮都有人插嘴（插一句是点缀，插三句是噪音）
      - 确定性伪随机（同 E6/E7 的 FNV-1a，不用 `random`）
- [ ] `plan_group(candidates, *, primary_id, seed, max_hecklers=1) -> GroupPlan`
      - `{"primary": id, "hecklers": [...]}`（默认最多 1 个）

## Task 2: 后端接线

- [ ] `ChatRequest` 加 `group: bool = False`（**默认关** —— 不破坏现有行为）
- [ ] `{token}` 事件带 `speaker`（char_id）和 `speaker_name`
- [ ] 主答 `done` 后，若 `group` 且命中 → 生成插嘴并发 `{"interjection": ...}`
      - 插嘴 prompt 要**短**（一句台词），并带上下文（刚说了什么）
      - **失败不响主链路**：插嘴失败只记日志
- [ ] 群成员来源：`build_social_prompt_for_character` 的参与者 +
      `get_all_characters()` 中与主角有关系的

## Task 3: 前端

- [ ] 聊天页加**群聊开关**（默认关，和"世界日报"一样放在工具栏）
- [ ] 每条 assistant 消息显示**说话者**（小头像 + 名字）
      - 插嘴消息用那个角色的头像
      - 单聊模式下不显示（保持现状）
- [ ] `onInterjection` → 作为新消息入列（`role: assistant` + `speaker`）
- [ ] 群成员头像从 `/characters`（前端已有）

## Task 4: 测试

- [ ] `test_group_chat.py`：
      - 插嘴者**排除主角** / 空候选返回 None
      - `should_heckle` 概率（100 个 seed 有真有假）
      - **确定性**（同 seed 同结果）
      - `max_hecklers` 生效 / 候选只有主角自己 → 空
      - 坏输入（None / 非字符串）不崩
- [ ] **验证"测试能失败"**（用 Edit 不用 cp）：允许插嘴者 == 主角 → 断言红

## 最终验收

- [ ] 后端全绿；前端 type-check / lint / vitest 全绿
- [ ] **端到端实测 + 截图**：开群聊 → 发消息 → 看到主答 + 插嘴（两条不同说话者）
- [ ] 确认**默认（不开群聊）行为和之前完全一致**

## Self-Review

**1. Spec coverage**：要"一群角色" → Task 1-3。✅
**2. 最大风险 = 破坏单聊**：`group` 默认 False + token 事件只加字段 →
  老前端/老行为完全不变。✅
**3. 插嘴成本**：只在命中时多一次 LLM 调用（25% 概率），
  且主答已返回、用户已在读，插嘴是"追加"不增加首 token 延迟。✅
**4. 不过度设计**：不做多人同时打字、不做@指定、不做群公告。✅
**5. 头像**：群成员头像走已有 `/characters`，不新增接口。✅

## Known Issues（预期）

- 插嘴是"事后追加"，不是真并发（视觉上仍像接力发言）
- 群成员 = 与主角有关系的角色，**不是用户自选**（自选群是更大的功能）
- 插嘴内容不带记忆上下文（只有最近几句）
