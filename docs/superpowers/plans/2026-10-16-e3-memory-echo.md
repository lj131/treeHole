# E3 记忆回响 —— 让"她记得"这件事可见 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** RAG 每轮都在召回长期记忆进 prompt，但用户**完全看不见**。
让这件事可见：助手消息上标一个「💭 参考了 N 条记忆」，点开能看到具体内容。

**为什么做这个:** 陪伴类产品最核心的体验是"**被记住**"。
现在这件事在后台真实发生（每轮召回 + 注入 prompt），但用户感受不到 ——
**已投入的能力没变现**。

## Task 0: 数据源（**已实测**）

`memory_rag.retrieve_memories()` 返回 `[{text, collection, score, weighted_score, metadata}]`。

**⚠️ 三个实测结论（决定了实现方式）：**

1. **`score` 是 distance（越小越相关）** —— `items.sort(key=lambda x: x["score"])` 升序。
2. **分数区间极窄**（实测 1.22 ~ 1.47）→ **不能用绝对阈值过滤**，
   只能按相对排序取前 N 条。
3. **不是所有集合都适合当"记忆回响"**：

| collection | 适合吗 | 原因 |
|---|---|---|
| `long_memory` | ✅ | 正是"她记得你说过的事" |
| `events` | ✅ | 你们之间发生过的事 |
| `profile` | ⚠️ | 用户画像，但常有「用户姓名：未知」这类噪音 |
| `story` | ❌ | 剧情**设定**文本，不是"记得" |
| `relationship` | ❌ | 关系**状态**，不是记忆 |

`/chat/stream` 的 SSE 已有 `{token}` / `{done}` / `{error}` 三种事件；
`retrieved` 在**轮 2**（关键路径）拿到，**就是最终进 prompt 的那份**（无二次筛选）。

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `backend/funcation/memory_echo.py` | **新增** | **纯函数**：挑出该展示哪几条（可单测） |
| `backend/tests/test_memory_echo.py` | **新增** | 过滤 / 排序 / 噪音剔除 / 边界 |
| `backend/api/api.py` | 修改 | 轮 2 后发 `{memories}` SSE 事件 |
| `front/src/api/chat.ts` | 修改 | 加 `onMemories` 回调 |
| `front/src/types/api.ts` | 修改 | `ChatMessage.memories` |
| `front/src/stores/chatStore.ts` | 修改 | 把 memories **挂到该条助手消息上** |
| `front/src/views/Chat.vue` | 修改 | 消息下方的 💭 标记 + 展开 |
| `front/src/utils/memoryEcho.ts` | **新增** | 摘要文案（纯函数，可单测） |

## Task 1: 挑哪几条（纯函数）

- [ ] `pick_echoes(retrieved, *, limit=3) -> list[dict]`
      - **只保留** `long_memory` / `profile` / `events`
        （`story` / `relationship` 是设定与状态，不是"记得"）
      - 按 `score` **升序**（distance 小 = 相关），取前 `limit` 条
      - **剔噪音**：文本太短（< 6 字）、含占位词（「未知」「无变化」「暂无」）的跳过
      - 输出 `[{text, collection}]` —— **不带 score**（前端不需要，
        而且把 distance 显示给用户只会造成误解）
- [ ] `echo_summary(echoes) -> str` —— 「参考了 3 条记忆」，空则空串

## Task 2: 后端发事件

- [ ] `/chat/stream` 在**轮 2 之后**发 `{"memories": [...]}`
      - 放在 token 之前 → 用户看到角色开始打字时标记已经在了
      - 空列表**也发**（前端据此判断"这次没参考记忆"，而不是"还没收到"）
- [ ] 只影响 `/chat/stream`；`/chat`（非流式）不动

## Task 3: 前端

- [ ] `chat.ts` 加 `onMemories?: (memories) => void`，解析 `data.memories`
- [ ] `chatStore`：把 memories 挂到**当前正在生成的助手消息**上
      - **挂到消息而不是全局** —— 每条消息参考的记忆不同，
        全局状态会导致"翻历史时每条都显示同一个数字"
- [ ] `Chat.vue`：助手消息下方一行 `💭 参考了 3 条记忆`
      - 点击展开具体文本；无记忆时**不显示**（不占位）
- [ ] `utils/memoryEcho.ts` 抽文案（纯函数，可单测）

## Task 4: 措辞（**这条是设计决策，不是文案**）

**不写"她想起了你说过 XX"** —— 无法确认 LLM 真的用了那条记忆
（召回 ≠ 使用，prompt 注入了不代表模型采纳了）。

用 **「参考了 N 条记忆」**：准确、不撒谎，点开能看具体内容让用户自己判断。
**诚实 > 煽情**：一旦被用户发现"她说想起了 X 但根本没提过 X"，信任就没了。

## Task 5: 测试

- [ ] `test_memory_echo.py`：
      - **只要三个集合**（story / relationship 被排除）
      - 按 score 升序取前 N
      - 噪音剔除（短文本 / 占位词）
      - `limit` 生效 / 空输入 → 空列表 / 坏数据不崩 / 缺字段不崩
      - **不带 score 输出**
- [ ] `memoryEcho.spec.ts`：摘要文案（0 条 → 空串 / N 条 → 文案）
- [ ] **验证"测试能失败"**（用 Edit 改，不用 cp）：放行 `story` → 断言红

## 最终验收

- [ ] 后端全绿；前端 type-check / lint / vitest 全绿
- [ ] **端到端实测 + 截图**：真实聊天看到 💭 标记 + 展开内容
- [ ] 确认非流式 `/chat` 不受影响

## Self-Review

**1. Spec coverage**：要"让被记住可见" → Task 1-4 全覆盖。✅
**2. 最大风险 = 说了谎**：写"她想起了 X"但模型没用 → Task 4 用中性措辞规避。✅
**3. 数据特征已实测**：分数区间窄 → 不用绝对阈值；集合性质不同 → 白名单。✅
**4. 不破坏现状**：SSE 多一个事件类型，老前端忽略未知字段照常工作。✅
**5. 不过度设计**：不做"记忆命中率统计"、不做记忆编辑（那是 E12）、
不做逐条高亮（做不到就别假装）。✅

## Known Issues（预期）

- 召回 ≠ 使用：显示的只是"注入了 prompt 的记忆"，不是"模型真的用了的"
- 分数区间窄时（数据少）排序区分度低，前 3 条未必最相关
- 不做"这条记忆来自哪次对话"的溯源（`events` 有 time，但 `long_memory` 没有）
