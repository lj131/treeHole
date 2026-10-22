# E11 数据导出 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用户能把自己的数据导出来 —— 聊天记录 / 记忆 / 角色设定 / 关系与好感。
**隐私信任 + 情感价值（"导出成纪念册"）。**

## Task 0: 现状（**已查证**）

| 事实 | 位置 |
|---|---|
| **完全无导出能力**（`grep -c export api/api.py` = 0） | — |
| 聊天历史：`memory.load_memory(user_id, char_id)` | `funcation/memory.py` |
| 长期记忆/聊天摘要真源在 `.rag.json`，已有封装读法 | `mc.get_long_memories()` / `mc.get_chat_summary()` |
| 主 JSON 字段：`profile/relationship/favorability/story/character_state/self_awareness/events/dreams` | `data/memories/1/linwan.json` |
| 前端已有 `URL.createObjectURL` 用法（可复用下载模式） | `SettingsView.vue` 等 |

## 设计

- **`funcation/export_data.py`（纯函数，可测）**：
  - `collect_export_data(...)` —— 组装所有区块
  - `render_markdown(...)` —— 人读格式（"纪念册"）
  - `render_json(...)` —— 机器读格式
- **`GET /export?format=markdown|json`** —— 直接返回文件下载
  （`Content-Disposition: attachment`，用户也能用 curl 直接拿）
- **只导当前用户的当前角色**（和聊天页的上下文一致，不做全账号导出）
- 前端在 **SettingsView** 加入口 + 格式选择

## ⚠️ 安全：导出必须过滤敏感字段

导出的是"用户自己的数据"，但 memory/character 字典里可能混着不该出去的东西
（API key、token、内部路径、其他用户的引用）。所以：
- **白名单式收集**（只取我们明确要的字段），不是"把整个 dict 倒出去"
- 专门有一条测试钉住：即使源数据里塞了 `api_key`/`token`/`password`，
  **导出结果里也绝不出现**

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `backend/funcation/export_data.py` | **新增** | 纯函数：收集 + 渲染 Markdown/JSON |
| `backend/tests/test_export_data.py` | **新增** | 区块齐全/敏感字段过滤/空数据/坏输入 |
| `backend/api/api.py` | 修改 | `GET /export`（`require_approved`） |
| `front/src/api/export.ts` | **新增** | 请求 + Blob 下载 |
| `front/src/views/SettingsView.vue` | 修改 | 导出入口 + 格式选择 |

## Task 1: `funcation/export_data.py`

- [ ] `collect_export_data(mc, user_id, character_id, character, messages) -> dict`
      - 区块：`meta`（导出时间/角色/用户 id）、`character`（设定）、
        `relationship`（好感+关系+原因）、`profile`（用户画像）、`story`（剧情）、
        `chat_summary`、`long_memory`、`events`、`diaries`、`dreams`、`messages`（聊天记录）
      - **白名单**：只取明确要的字段
- [ ] `render_markdown(data) -> str`：分节、可读、有标题层级
      （纪念册感：开头一段"你和 XX 的故事"）
- [ ] `render_json(data) -> str`：`ensure_ascii=False, indent=2`

## Task 2: 端点

- [ ] `GET /export?format=markdown|json`（`require_approved`）
      - 默认 markdown；未知 format → 400
      - `Content-Disposition: attachment; filename="..."`（带角色名和日期）
      - 取不到角色/数据 → 仍返回一个**空的但结构完整**的导出（不 500）

## Task 3: 前端

- [ ] `SettingsView` 加「导出我的数据」：格式二选（Markdown 纪念册 / JSON 完整数据）
      - 下载走 `URL.createObjectURL` + `<a download>`，用完 **revokeObjectURL**
      - 文件名带角色名和日期

## Task 4: 测试

- [ ] `test_export_data.py`：
      - collect 覆盖**所有区块**（含空数据的区块也存在，不缺键）
      - **敏感字段被过滤**：源数据塞 `api_key`/`token`/`password`/`secret`
        → 导出结果里**一个都不出现**
      - **不越权**：只读传入的 `user_id`/`character_id`（假 mc 记录调用参数）
      - 空数据 / None / 坏类型不崩
      - Markdown 含各节标题、含角色名、聊天记录按序渲染
      - JSON 可解析且字段齐全
- [ ] **验证"测试能失败"**（用 Edit 不用 cp）：把 collect 改成"整个 dict 倒出去" → 敏感字段测试红

## 最终验收

- [ ] 后端全绿；前端 type-check / lint / vitest 全绿
- [ ] **端到端实测 + 截图**：Settings 点导出 → 下载到文件 →
      **打开看内容确实包含聊天记录/记忆/好感**（真数据）
- [ ] 敏感字段测试通过（这是安全承诺，不能只靠"我觉得没问题"）

## Self-Review

**1. Spec coverage**：要"导出聊天记录/记忆/角色设定" → Task 1-3 全覆盖。✅
**2. 最大风险 = 泄漏敏感字段**：白名单收集 + 专门测试钉住。✅
**3. 不越权**：只导当前用户当前角色，`require_approved` + 测试验证参数。✅
**4. 不过度设计**：不做全账号导出、不做 ZIP 打包、不做导入（反向）、
   不做定时导出。✅
**5. 双格式**：Markdown 给人看（纪念册），JSON 给机器/备份。✅

## Known Issues（预期）

- 只导**当前角色**（全账号导出是另一个功能）
- 不含媒体文件（头像/语音包）—— 只导文本数据
- 导入（把导出的数据读回来）刻意不做：那是另一套冲突解决逻辑
