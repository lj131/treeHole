# 批次 2：群聊发言权调度（2026-11-16）

> 方向来自 `2026-11-02-next-phase.md` 批次 2。动手前把现状重新核对了一遍，
> 下面的信号来源都是**查到代码里确实存在的**，不是照抄旧方案。

## Goal

从"随机抽一个人插嘴"变成"该说话的人说话"，同时**不做成轮流发言的假群聊**。

## 现状（已核对）

- `funcation/group_chat.py` 是**纯函数**：FNV-1a 确定性伪随机，零 IO，测试齐全（`test_group_chat.py`）。
- 插嘴只在 `/chat/stream` 的 `_make_interjection()`（`api/api.py:553`）里发生，
  在 `done` 事件之后追加，失败不抛。
- **候选来源**：`npc_registry.relationships`（世界状态里 NPC 关系矩阵），
  目前取所有和主角有过关系的人。
- **可用信号（全部查证存在）**：
  | 信号 | 来源 | 形状 |
  |---|---|---|
  | 关系强度 | `npc_registry.relationships[f][t]` | `{favorability, trust, intimacy}`，0~100 |
  | 内容相关 | `retrieved`（RAG 检索结果，`chat_stream` 已有） | `[{collection: "u{uid}_{char}_long_memory", ...}]` |
  | 性格外向 | `data/characters/*.json` 的 `personality` | 中文短文本（如"高冷"） |
  | 睡眠硬门 | `circadian.current_phase(hour).late_night` | bool |
  | 防连庄 | `npc_registry["recent_hecklers"]`（**本次新增字段**） | `["char_id", ...]` 最近 3 个 |
- **约束**：主角不插嘴、25% 概率、一轮最多 1 个（现有测试钉住）。

## 设计

### 1. 新纯函数 `plan_group_with_signals()`

放在 `group_chat.py`，**和旧的 `plan_group` 并存**（旧的不动，零回归）：

```
输入：candidates, primary_id, seed,
      affinity={cid: 0~100},   # 关系强度（主角视角）
      relevant={cid: bool},    # 本轮 RAG 命中了谁的集合
      extrovert={cid: bool},   # 性格外向
      recent=[cid, ...],       # 最近插过嘴的人
      sleeping=[cid, ...]      # 硬门：正在睡的
输出：GroupPlan（复用）
```

- **硬门**：`sleeping` 里的直接排除（深夜全员睡 → 返回空，不插嘴）。
- **权重**（基础 1.0，可叠加）：
  - 内容相关命中 → `+3.0`（最强：聊到谁谁接话）
  - 关系强度 → `+(favorability/100) * 2.0`（关系越好越爱接）
  - 性格外向 → `+0.5`
  - 防连庄 → 最近插过的人 `× 0.15`（不是禁止，是大幅降权 —— 保留自然感）
- **选择**：每个候选算 `draw = _hash_seed(f"{seed}|draw|{cid}") / 2^32 ∈ [0,1)`，
  按权重做加权轮盘。确定性、可测、权重真的影响结果。
- 概率门 `should_heckle()` 仍在外面先过，保持 25%。

### 2. `api._make_interjection()` 接线

- 新增入参 `relevant_ids`（从 `chat_stream` 的 `retrieved` 解析集合名）和 `sleeping`。
- 从 `world_state.npc_registry` 读 `relationships` → 算 affinity；读 `recent_hecklers` → 防连庄。
- 从 `mc.get_all_characters()` 读 `personality` → 外向判定（关键词表）。
- 插入成功后把 `pick` 写回 `recent_hecklers`（保留最近 3 个），**重读再只改这个字段**避免并发覆盖。
- 全部 best-effort，绝不让插嘴失败影响主链路。

### 3. 状态落点：`npc_registry["recent_hecklers"]`

选它而不是 `proactive_stats.json`（那是计数器，塞 char 列表会污染语义和被坏文件机制拦截），
也不是内存（重启即丢，连庄跨重启无法防）。零 schema 迁移，`ensure_npc_registry` 里加默认空列表。

## 验收

**单测**（`test_group_chat.py` 追加）
- 主角永不被选 / 一次不超过 cap / 同轮不重复（已有，回归）
- 给定信号 → 确定输出（同一 seed 同结果）
- 睡着的全排除 → 空 plan
- 权重排序：相关内容 + 高关系的人稳定压过无关低关系的人
- 防连庄：最近插过的人权重降到 0.15，统计上不再连庄
- 只有主角 + 睡觉的人 → 空

**实测**：连聊 5 轮（group=true），看插嘴者是否合理 —— 判据同方向文档：
连续两轮同一人插嘴 = 失败；插嘴者与话题无关 = 失败。

**固定动作**：后端双环境全绿、数据与索引还原、同步 3 份 CLAUDE.md、提交、写日志。

## 明确不做

- 不改 LLM 插嘴 prompt（那是"说什么"，本次只管"谁说"）
- 不引入新的持久化机制（复用 world_state）
- 不动 25% / max_hecklers 两个既有参数（调参等数据，见方向文档批次 4）
