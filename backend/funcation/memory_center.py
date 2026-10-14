"""
MemoryCenter - 角色数据中心

统一管理一个角色的所有动态数据：
- 用户画像 (profile)
- 好感度 (favorability)
- 长期记忆 (long_memory)
- 事件 (events)
- 聊天摘要 (chat_summary)

也管理角色和世界的切换与加载。

数据存储结构:
data/
├── characters/          # 静态角色定义
├── worlds/              # 静态世界定义
└── memories/
    ├── {uid}/{char}.json      # 小状态（profile / favorability / story / ...）
    └── {uid}/{char}.rag.json  # 三个"靠向量库检索"的字段（见下）

## 真源划分（重要，别改错方向）

| 字段 | 真源 | 向量库的角色 |
|---|---|---|
| profile / story / relationship | `.json` | **派生索引**（api.py 的 `_sync_*_to_rag`） |
| long_memory / events / chat_summary | **`.rag.json`** | **派生索引**（本模块的 `add_*`） |

**向量库随时可以删掉重建** —— 它是索引，不是存储。
这条是 2026-10-14 修 P0 §1-7 时立的：在那之前，
`long_memory`/`events`/`chat_summary` **只存在于向量库**，
于是向量库一被隔离就等于**静默丢数据**（真实发生过 6 次）。

### 为什么这三个字段另起一个文件，而不是塞进主 JSON

主 JSON 的 `save_memory()` 是「**用调用方手上的快照整体覆盖**」的语义，
而聊天主流程是：

    load_memory → ... → add_chat_summary(×2) → save_memory(早先加载的旧快照)
                         ↑ 写磁盘                    ↑ 会把上面的写入冲掉

也就是 `add_*` 与 `save_memory` 会争同一个文件。
另起 `.rag.json` = 两个 writer 各写各的，**零冲突**，
也不用改动既有的 save/load 语义（改动面最小）。
"""

import json
import os
import random
import tempfile
from datetime import datetime


# ============================================================
# 路径常量
# ============================================================

DATA_DIR = "data"
CHARACTERS_DIR = os.path.join(DATA_DIR, "characters")
WORLDS_DIR = os.path.join(DATA_DIR, "worlds")
WORLD_STATE_DIR = os.path.join(DATA_DIR, "world_state")
MEMORIES_DIR = os.path.join(DATA_DIR, "memories")


# ============================================================
# 默认记忆工厂
# ============================================================

def create_default_memory():
    """创建一个角色的默认记忆结构（大数据字段由 ChromaDB 管理，JSON 仅存小状态）"""
    return {
        "profile": {
            "name": "",
            "city": "",
            "job": "",
            "mood": "",
            "recent_topics": []
        },
        "favorability": 50,
        "relationship": {
            "level": "普通",
            "last_reason": ""
        },
        "character_state": {

            "mood": "开心",

            "energy": 80,

            "current_event": {

                "title": "",

                "description": "",
                "event_date": "",

                "start_time": "",
                "impact": -20
            },

            "last_active_time": ""
        },
        "proactive": {

            "last_time": "",

            "last_message": "",
            "today_count": 0,

            "last_trigger": "",

            "cooldown_hours": 6
        },
        "story": {
            "story_id": "",
            "title": "",
            "description": "",
            "stage": 0,
            "max_stage": 0,
            "stages": [],
            "last_update_date": ""
        },
        "stories": [],
        "story_history": [],
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
    }

# 这三个字段的真源是 `.rag.json`（**不是**向量库）。
# 名字沿用历史叫法；注意它现在表示"由 add_* 写入 .rag.json 并索引进向量库"，
# 而不是"存在向量库里"。
_CHROMA_FIELDS = ["long_memory", "events", "chat_summary"]


def create_default_rag():
    """`.rag.json` 的默认结构"""
    return {
        "long_memory": [],      # [str]
        "events": [],           # [{time, event}]
        "chat_summary": [],     # [str]
        "meta": {"version": 1, "updated_at": None},
    }


def create_default_world_state(world_id=""):
    """创建世界动态状态的默认结构（独立于角色记忆）"""
    now = datetime.now().isoformat()
    return {
        "world_id": world_id,
        "world_state": {
            "season": "",
            "weather": "晴",
            "time_period": "",
            "last_tick_date": "",
            "last_event_gen_date": "",
            "last_interaction_date": "",
            "npc_registry": {},
            "factions": {},
            "economy": {},
        },
        "current_events": [],
        "history_events": [],
        "meta": {
            "version": 1,
            "created_at": now,
            "updated_at": now,
        },
    }


# ============================================================
# MemoryCenter 类
# ============================================================

class MemoryCenter:
    """
    角色的数据中心，统一管理所有动态数据。

    用法:
        mc = MemoryCenter()
        char = mc.load_current_character()
        mem = mc.load_memory(char["id"])
        mc.update_favorability(user_input, char["id"])
    """

    # ========== 记忆文件路径 ==========

    def _get_memory_path(self, user_id, character_id):
        """记忆文件按用户隔离：data/memories/{user_id}/{character_id}.json"""
        return os.path.join(MEMORIES_DIR, str(user_id), f"{character_id}.json")

    def _get_rag_path(self, user_id, character_id):
        """三个检索型字段的真源：data/memories/{user_id}/{character_id}.rag.json"""
        return os.path.join(MEMORIES_DIR, str(user_id), f"{character_id}.rag.json")

    # ========== .rag.json 读写（三个检索型字段的真源） ==========

    def _load_rag(self, user_id, character_id) -> dict:
        """读 `.rag.json`。

        **绝不抛**：文件不存在、内容损坏、写了一半 —— 一律退回默认空结构。
        读失败当成"空"是安全的：真源文件坏了要人工介入，
        但绝不能因此让整个聊天流程崩掉。
        """
        path = self._get_rag_path(user_id, character_id)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return create_default_rag()
        if not isinstance(data, dict):
            return create_default_rag()

        base = create_default_rag()
        for key in _CHROMA_FIELDS:
            value = data.get(key)
            if isinstance(value, list):
                base[key] = value
        base["meta"].update(data.get("meta") or {})
        return base

    def _save_rag(self, user_id, character_id, rag: dict) -> None:
        """原子写 `.rag.json`（临时文件 + `os.replace`）。

        直接 `open(path, "w")` 的话，写到一半被读到就是**半截 JSON** ——
        而这是真源，宁可旧也不能坏。
        """
        path = self._get_rag_path(user_id, character_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        payload = {k: rag.get(k, []) for k in _CHROMA_FIELDS}
        payload["meta"] = {
            **(rag.get("meta") or {}),
            "version": 1,
            "updated_at": datetime.now().isoformat(),
        }

        fd, tmp = tempfile.mkstemp(
            prefix=f".{character_id}.", suffix=".rag.tmp", dir=os.path.dirname(path)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except BaseException:
            # 临时文件清理也是 best-effort（本环境的 CLI shim 会拦 os.remove）
            try:
                os.remove(tmp)
            except (Exception, SystemExit):
                pass
            raise

    # ========== 记忆读写 ==========

    def load_memory(self, user_id, character_id):
        """加载角色的完整记忆数据（小状态 JSON + 检索型字段 .rag.json）

        对外返回结构与历史一致（三个检索型字段照样在 dict 里），调用方无感。
        """
        path = self._get_memory_path(user_id, character_id)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = create_default_memory()

        # 一次性**反向**迁移：把早年搬进向量库的三个字段捞回 .rag.json。
        # 必须在读 .rag.json 之前跑（它负责把文件建出来）
        self._migrate_from_chroma(user_id, character_id, data)

        # 兼容：老 JSON 里可能还留着这三个字段（历史遗留），搬进 .rag.json 后就地删掉
        self._absorb_legacy_rag_fields(user_id, character_id, data)

        # 一次性迁移：旧单剧情 story dict → 新多剧情 stories 数组
        self._migrate_story_format(data)

        # 补字段：self_awareness（旧记忆文件无此字段）
        self._ensure_self_awareness(data)

        # 补字段：seen_world_event_ids（旧记忆文件无此字段）
        data.setdefault("seen_world_event_ids", [])

        # 检索型字段：从 .rag.json 读（**不是**从向量库 —— 向量库只是索引）
        rag = self._load_rag(user_id, character_id)
        data["long_memory"] = list(rag.get("long_memory") or [])
        data["events"] = list(rag.get("events") or [])[-50:]
        data["chat_summary"] = list(rag.get("chat_summary") or [])[-10:]

        return data

    def _absorb_legacy_rag_fields(self, user_id, character_id, data):
        """把老 JSON 里残留的三个字段搬进 `.rag.json`，并从 data 里删掉。

        `.rag.json` 已有内容时**以它为准**（它是真源），老 JSON 里的直接丢弃 ——
        否则每次 load 都会把历史残留重新灌回去，覆盖用户后续的修改。
        """
        legacy = {k: data.pop(k, None) for k in _CHROMA_FIELDS}
        if not any(legacy.values()):
            return

        rag_path = self._get_rag_path(user_id, character_id)
        if os.path.isfile(rag_path):
            return

        rag = create_default_rag()
        if isinstance(legacy.get("long_memory"), list):
            rag["long_memory"] = [str(x) for x in legacy["long_memory"] if x]
        if isinstance(legacy.get("events"), list):
            rag["events"] = [x for x in legacy["events"] if x]
        if isinstance(legacy.get("chat_summary"), list):
            rag["chat_summary"] = [str(x) for x in legacy["chat_summary"] if x]
        if any(rag[k] for k in _CHROMA_FIELDS):
            self._save_rag(user_id, character_id, rag)

    def _migrate_from_chroma(self, user_id, character_id, data):
        """一次性**反向**迁移：早年把 long_memory/events/chat_summary 搬进了向量库，
        这里把它们捞回 `.rag.json`。

        （历史函数叫 `_migrate_to_chroma`，方向是反的 —— 正是它造成了
        "向量库被隔离 = 数据丢失"。2026-10-14 改回来。）

        **幂等**：`.rag.json` 已有内容就跳过。
        **读不到向量库时什么都不做** —— 绝不能把"读不到"当成"没有"而写出一个空文件，
        那等于用一次读取失败把真源抹掉。
        """
        rag_path = self._get_rag_path(user_id, character_id)
        if os.path.isfile(rag_path):
            return

        from funcation import memory_rag

        try:
            long_items = memory_rag.list_all_memories(user_id, character_id, "long_memory")
            event_items = memory_rag.list_all_memories(user_id, character_id, "events")
            summary_items = memory_rag.list_all_memories(user_id, character_id, "chat_summary")
        except (Exception, SystemExit) as e:  # noqa: BLE001
            # 向量库坏了/被隔离 → 不写文件，留给人工或重建流程
            import logging

            logging.getLogger(__name__).warning(
                "[memory] 反向迁移读不到向量库，跳过（不会写出空真源）: %s", e
            )
            return

        rag = create_default_rag()
        rag["long_memory"] = [it["text"] for it in long_items if it.get("text")]
        rag["events"] = [
            {"time": (it.get("metadata") or {}).get("time", ""), "event": it["text"]}
            for it in event_items
            if it.get("text")
        ]
        rag["events"].sort(key=lambda x: x.get("time", ""))
        rag["chat_summary"] = [it["text"] for it in summary_items if it.get("text")]

        if any(rag[k] for k in _CHROMA_FIELDS):
            self._save_rag(user_id, character_id, rag)

    def _migrate_story_format(self, data):
        """一次性迁移：旧 story dict → 新 stories 数组

        旧格式: data["story"] = {story_id, title, description, stage, max_stage, stages, last_update_date}
        新格式: data["stories"] = [{id, title, type="main", status, stage, max_stage, stages, ...}, ...]

        迁移规则:
        - 旧 story 已有 story_id 且 stages 非空 → 转成 stories[0] (type="main", status="active")
        - 旧 story 已完成（stage >= max_stage）→ 转成 stories[0] (status="completed")
        - 迁移后保留旧 story 字段（兼容外部读取），但下次 save 时不写回 JSON（_CHROMA_FIELDS 外的都会写，所以需要清理）

        本方法幂等：已迁移过（data 有非空 stories）时直接返回。
        """
        from datetime import datetime as _dt
        # 已有 stories 数组 → 已迁移
        if data.get("stories"):
            return

        old_story = data.get("story", {})
        if not old_story or not old_story.get("story_id") or not old_story.get("stages"):
            data.setdefault("stories", [])
            return

        stage = old_story.get("stage", 0)
        max_stage = old_story.get("max_stage", 0)
        status = "completed" if stage >= max_stage else "active"

        migrated = {
            "id": old_story.get("story_id", ""),
            "title": old_story.get("title", ""),
            "description": old_story.get("description", ""),
            "type": "main",
            "status": status,
            "stage": stage,
            "max_stage": max_stage,
            "stages": old_story.get("stages", []),
            "branch_points": [],
            "tags": [],
            "started_at": old_story.get("last_update_date", _dt.now().strftime("%Y-%m-%d")),
            "last_advance_date": old_story.get("last_update_date", _dt.now().strftime("%Y-%m-%d")),
        }
        data["stories"] = [migrated]
        # 清空旧的 story dict（避免下次 save 时重复写入 JSON）
        data["story"] = {}

    def _ensure_self_awareness(self, data):
        """补 self_awareness 字段（旧记忆文件可能没有）。幂等。

        若字段缺失，用当前好感度作为峰值/低谷初值，避免后续比较时基准错误。
        """
        sa = data.get("self_awareness")
        if isinstance(sa, dict) and "milestones" in sa:
            return
        fav = data.get("favorability", 50)
        data["self_awareness"] = {
            "first_chat_date": "",
            "peak_favorability": fav,
            "peak_fav_date": "",
            "min_favorability": fav,
            "min_fav_date": "",
            "milestones": [],
            "fav_trail": [],
        }

    def save_memory(self, user_id, character_id, data):
        """保存角色的**小状态**到 `.json`。

        三个检索型字段（`_CHROMA_FIELDS`）**不走这里** —— 它们的真源是 `.rag.json`，
        由 `add_*` / `update_*` 自己维护（见模块 docstring 的"为什么另起一个文件"）。
        这里显式剔除它们，免得调用方手上的旧快照把 `.rag.json` 的内容也一起带偏。
        """
        path = self._get_memory_path(user_id, character_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        json_data = {k: v for k, v in data.items() if k not in _CHROMA_FIELDS}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)

    # ========== 用户画像 ==========

    def get_profile(self, user_id, character_id):
        """获取角色的用户画像"""
        mem = self.load_memory(user_id, character_id)
        return mem.get("profile", {})

    def update_profile(self, user_id, user_input, character_id):
        """[DEPRECATED] 已被 update_state_unified() 替代。保留供兼容。"""
        from funcation import profile_agent

        mem = self.load_memory(user_id, character_id)
        profile = mem.setdefault("profile", {})

        # 用 AI agent 提取画像信息
        extracted = profile_agent.extract_profile(user_input, profile)

        # 合并提取结果
        if extracted:
            for key in ["name", "city", "job", "mood"]:
                if key in extracted and extracted[key]:
                    profile[key] = extracted[key]

        # 最近话题（保留旧逻辑，每次追加用户输入）
        profile.setdefault("recent_topics", [])
        profile["recent_topics"].append(user_input)
        profile["recent_topics"] = profile["recent_topics"][-5:]

        mem["profile"] = profile
        self.save_memory(user_id, character_id, mem)

    def get_caring_message(self, user_id, character_id):
        """根据画像生成关心消息（AI agent 智能生成）"""
        from funcation import profile_agent

        profile = self.get_profile(user_id, character_id)

        # 加载角色名
        try:
            character = self.load_character_by_id(character_id)
            character_name = character.get("name", "角色")
        except:
            character_name = "角色"

        return profile_agent.generate_caring_message(profile, character_name)

    # ========== 好感度 ==========

    def get_favorability(self, user_id, character_id):
        """获取角色的好感度"""
        mem = self.load_memory(user_id, character_id)
        return mem.get("favorability", 50)

    def update_favorability(self, user_id, user_input, character_id):
        """[DEPRECATED] 已被 update_state_unified() 替代。保留供兼容。"""
        from funcation import relationship_agent

        result = relationship_agent.update_relationship(
            self,
            user_id,
            character_id,
            user_input,
        )
        return result["favorability"]

    # ========== 长期记忆 ==========

    def get_long_memories(self, user_id, character_id):
        """获取长期记忆列表（真源：`.rag.json`）"""
        return list(self._load_rag(user_id, character_id).get("long_memory") or [])

    def _index_to_rag(self, user_id, character_id, collection_type):
        """把 `.rag.json` 的对应字段**全量重建**进向量库索引（best-effort）。

        为什么是全量而不是增量：向量库是**派生索引**，随时可能被清空/隔离，
        增量同步反而要维护"索引和真源是否一致"的状态。全量重建最省心
        （数据量本来就小：实测全库 37 条）。

        **失败只记日志，绝不向上抛** —— 真源已经写好了，索引坏了可以再建。
        """
        from funcation import memory_rag

        try:
            rag = self._load_rag(user_id, character_id)
            memory_rag.rebuild_collection_from_items(
                user_id, character_id, collection_type, rag.get(collection_type) or []
            )
        except (Exception, SystemExit) as e:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).warning(
                "[memory] 索引重建失败（不影响数据，可稍后重建）: %s", e
            )

    def add_long_memory(self, user_id, character_id, memory_text):
        """添加一条长期记忆（自动去重）。

        先写 `.rag.json`（**真源**），再重建向量库索引。
        """
        if not memory_text:
            return
        rag = self._load_rag(user_id, character_id)
        existing = rag.get("long_memory") or []
        if memory_text in existing:
            return
        rag["long_memory"] = [*existing, memory_text]
        self._save_rag(user_id, character_id, rag)
        self._index_to_rag(user_id, character_id, "long_memory")

    def update_long_memory(self, user_id, character_id, old_text, new_text):
        """更新一条长期记忆（真源：`.rag.json`）"""
        rag = self._load_rag(user_id, character_id)
        items = rag.get("long_memory") or []
        if old_text not in items:
            return
        rag["long_memory"] = [new_text if x == old_text else x for x in items]
        self._save_rag(user_id, character_id, rag)
        self._index_to_rag(user_id, character_id, "long_memory")

    def get_long_memories_text(self, user_id, character_id):
        """获取长期记忆的文本列表"""
        return self.get_long_memories(user_id, character_id)

    # ========== 事件 ==========

    def get_events(self, user_id, character_id):
        """获取事件列表（真源：`.rag.json`）"""
        items = list(self._load_rag(user_id, character_id).get("events") or [])
        items.sort(key=lambda x: (x or {}).get("time", ""))
        return items[-50:]  # 最多 50 条

    def add_event(self, user_id, character_id, event_text):
        """添加一个事件（真源：`.rag.json`；向量库只是索引）"""
        if not event_text:
            return
        rag = self._load_rag(user_id, character_id)
        events = list(rag.get("events") or [])
        events.append({
            "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "event": event_text,
        })
        rag["events"] = events
        self._save_rag(user_id, character_id, rag)
        self._index_to_rag(user_id, character_id, "events")

    # ========== 角色状态 ==========

    def get_character_state(self, user_id, character_id):
        """获取角色状态"""
        mem = self.load_memory(user_id, character_id)
        return mem.get("character_state", {})

    def update_character_state(self, user_id, character_id, state):
        """更新角色状态"""
        mem = self.load_memory(user_id, character_id)
        old_state = mem.get("character_state", {})
        old_mood = old_state.get("mood", "")
        new_mood = state.get("mood", "")

        # 心情变化标记
        if new_mood and new_mood != old_mood:
            state["mood_changed"] = True

        mem["character_state"] = state
        self.save_memory(user_id, character_id, mem)

    def update_state_unified(self, user_id, character_id, user_input, world=None):
        """统一更新：画像 + 好感度 + 角色状态，一次 LLM 调用完成。

        替代原来的 update_profile() + relationship_agent.update_relationship()
        + update_character_state() 三次独立调用，减少 2 次 LLM API 请求。
        """
        from funcation import unified_state_agent

        mem = self.load_memory(user_id, character_id)
        current_profile = mem.get("profile", {})
        favorability = mem.get("favorability", 50)
        current_state = mem.get("character_state", {})

        result = unified_state_agent.analyze_unified_state(
            user_input, current_profile, favorability, current_state, world
        )

        # ── 1. 画像更新 ──
        profile_updates = result.get("profile", {})
        if profile_updates:
            profile = mem.setdefault("profile", {})
            for key in ["name", "city", "job", "mood"]:
                val = profile_updates.get(key, "")
                if val:
                    profile[key] = val
            # 最近话题
            profile.setdefault("recent_topics", [])
            profile["recent_topics"].append(user_input)
            profile["recent_topics"] = profile["recent_topics"][-5:]

        # ── 2. 好感度更新 ──
        rel = result.get("relationship", {})
        delta = rel.get("delta", 0)
        reason = rel.get("reason", "")

        old_level = mem.get("relationship", {}).get("level", "普通")
        favorability = max(0, min(100, favorability + delta))
        mem["favorability"] = favorability

        from funcation import relationship_agent as _rel
        new_level = _rel.get_relationship_level(favorability)
        mem["relationship"] = {"level": new_level, "last_reason": reason}

        if old_level != new_level:
            mem["relationship"]["level_changed"] = True
            self.add_event(
                user_id, character_id,
                f"关系从{old_level}变成{new_level}",
            )

        # ── 2b. 自我意识轨迹（确定性，无额外 LLM 调用）──
        self._track_self_awareness(mem, old_level, new_level, favorability)

        # ── 3. 角色状态更新 ──
        cs = result.get("character_state", {})
        if cs and isinstance(cs, dict):
            old_mood = current_state.get("mood", "")
            new_mood = cs.get("mood", "")
            if new_mood and new_mood != old_mood:
                cs["mood_changed"] = True
            merged_state = {**current_state, **cs}
            mem["character_state"] = merged_state

        self.save_memory(user_id, character_id, mem)

    def _track_self_awareness(self, mem, old_level, new_level, favorability):
        """更新自我意识轨迹：关系里程碑 + 好感峰值/低谷 + 好感快照。

        纯确定性计算，在 update_state_unified 的 save 之前调用，
        随 mem 一起被 save_memory 落盘。
        """
        from datetime import datetime as _dt
        sa = mem.setdefault("self_awareness", {})
        sa.setdefault("milestones", [])
        sa.setdefault("fav_trail", [])
        today = _dt.now().strftime("%Y-%m-%d")

        # 首次聊天日期
        if not sa.get("first_chat_date"):
            sa["first_chat_date"] = today

        # 关系等级变化 → 记里程碑（最多保留 8 条）
        if old_level != new_level:
            sa["milestones"].append({"date": today, "from": old_level, "to": new_level})
            sa["milestones"] = sa["milestones"][-8:]

        # 好感峰值 / 低谷
        if favorability > sa.get("peak_favorability", favorability):
            sa["peak_favorability"] = favorability
            sa["peak_fav_date"] = today
        if favorability < sa.get("min_favorability", favorability):
            sa["min_favorability"] = favorability
            sa["min_fav_date"] = today

        # 好感快照：每天最多一条（同日覆盖），保留最近 10 条
        trail = sa["fav_trail"]
        if trail and trail[-1].get("date") == today:
            trail[-1]["value"] = favorability
        else:
            trail.append({"date": today, "value": favorability})
        sa["fav_trail"] = trail[-10:]

    # ========== 聊天摘要 ==========

    def get_chat_summary(self, user_id, character_id):
        """获取聊天摘要列表（真源：`.rag.json`）"""
        return list(self._load_rag(user_id, character_id).get("chat_summary") or [])[-10:]

    def update_chat_summary(self, user_id, character_id, summaries):
        """替换聊天摘要（真源：`.rag.json`）"""
        rag = self._load_rag(user_id, character_id)
        rag["chat_summary"] = [str(s) for s in (summaries or [])]
        self._save_rag(user_id, character_id, rag)
        self._index_to_rag(user_id, character_id, "chat_summary")

    def add_chat_summary(self, user_id, character_id, summary):
        """追加一条聊天摘要（真源：`.rag.json`，保留最近 10 条）"""
        if not summary:
            return
        rag = self._load_rag(user_id, character_id)
        items = [*list(rag.get("chat_summary") or []), str(summary)]
        rag["chat_summary"] = items[-10:]
        self._save_rag(user_id, character_id, rag)
        self._index_to_rag(user_id, character_id, "chat_summary")

    # ========== 索引重建（向量库是索引，坏了从真源重建） ==========

    def list_rag_characters(self) -> list[tuple[int, str]]:
        """列出所有**有真源文件**的 (user_id, character_id)。

        扫 `.rag.json` 而不是 `.json` —— 只有前者才代表"这里有需要索引的数据"。
        """
        result: list[tuple[int, str]] = []
        if not os.path.isdir(MEMORIES_DIR):
            return result
        for user_dir in sorted(os.listdir(MEMORIES_DIR)):
            if not user_dir.isdigit():
                continue
            full = os.path.join(MEMORIES_DIR, user_dir)
            if not os.path.isdir(full):
                continue
            for name in sorted(os.listdir(full)):
                if name.endswith(".rag.json"):
                    result.append((int(user_dir), name[: -len(".rag.json")]))
        return result

    def rebuild_rag_index(self, user_id: int, character_id: str) -> dict:
        """按真源重建这个 (用户, 角色) 的三个索引集合。

        向量库被隔离/清空后调它就能恢复检索能力 —— 数据本来就没丢，
        丢的只是索引。返回每个集合索引了多少条。
        """
        from funcation import memory_rag

        rag = self._load_rag(user_id, character_id)
        counts = {}
        for ctype in _CHROMA_FIELDS:
            items = rag.get(ctype) or []
            counts[ctype] = memory_rag.rebuild_collection_from_items(
                user_id, character_id, ctype, items
            )
        return counts

    def rebuild_all_rag_indexes(self) -> dict:
        """全量重建（给运维用）。返回 {"characters": n, "indexed": {...}}"""
        targets = self.list_rag_characters()
        summary: dict = {"characters": len(targets), "indexed": {}, "errors": []}
        for user_id, character_id in targets:
            try:
                summary["indexed"][f"u{user_id}/{character_id}"] = self.rebuild_rag_index(
                    user_id, character_id
                )
            except (Exception, SystemExit) as e:  # noqa: BLE001 - 单个失败不阻断整体
                summary["errors"].append(f"u{user_id}/{character_id}: {e}")
        return summary

    # ========== 最后聊天时间 ==========

    def update_last_chat_time(self, user_id, character_id):
        """更新最后聊天时间"""
        mem = self.load_memory(user_id, character_id)
        mem["last_chat_time"] = datetime.now().isoformat()
        self.save_memory(user_id, character_id, mem)

    def get_last_chat_time(self, user_id, character_id):
        """获取最后聊天时间"""
        mem = self.load_memory(user_id, character_id)
        return mem.get("last_chat_time")

    # ========== 角色管理 ==========

    def get_user_current_character_id(self, user_id):
        """获取该用户当前选中的角色 ID（per-user，存于 users 表）"""
        from funcation.auth import SessionLocal, User
        db = SessionLocal()
        try:
            u = db.query(User).filter(User.id == user_id).first()
            if u and u.current_character_id:
                return u.current_character_id
            return "linwan"
        finally:
            db.close()

    def set_user_current_character(self, user_id, character_id):
        """设置该用户当前选中的角色"""
        from funcation.auth import SessionLocal, User
        db = SessionLocal()
        try:
            u = db.query(User).filter(User.id == user_id).first()
            if u:
                u.current_character_id = character_id
                db.commit()
        finally:
            db.close()

    def load_user_current_character(self, user_id):
        """加载该用户当前角色的静态定义"""
        character_id = self.get_user_current_character_id(user_id)
        return self.load_character_by_id(character_id)

    # 角色文件缓存：{character_id: (data, mtime)}
    _character_cache: dict[str, tuple[dict, float]] = {}

    def load_character_by_id(self, character_id):
        """根据ID加载角色静态定义（带 mtime 缓存）"""
        path = os.path.join(CHARACTERS_DIR, f"{character_id}.json")
        if not os.path.exists(path):
            path = os.path.join("characters", f"{character_id}.json")
        try:
            mtime = os.path.getmtime(path)
            cached = self._character_cache.get(character_id)
            if cached and cached[1] == mtime:
                return cached[0]
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._character_cache[character_id] = (data, mtime)
            return data
        except:
            raise

    def save_character(self, character):
        """保存角色静态定义"""
        os.makedirs(CHARACTERS_DIR, exist_ok=True)
        character_id = character["id"]
        path = os.path.join(CHARACTERS_DIR, f"{character_id}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(character, f, ensure_ascii=False, indent=2)

    def get_all_characters(self, user_id: int | None = None):
        """获取所有角色列表（简要信息）。

        user_id=None（管理员或不传）：返回全部角色。
        user_id 指定时：返回内置角色（无 created_by）+ 该用户创建的角色。
        """
        characters = []

        # 优先从 data/characters/ 读取
        search_dirs = [CHARACTERS_DIR, "characters"]
        seen_ids = set()

        for search_dir in search_dirs:
            if not os.path.exists(search_dir):
                continue
            for file in os.listdir(search_dir):
                if file.endswith(".json"):
                    path = os.path.join(search_dir, file)
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        char_id = data.get("id")
                        if char_id and char_id not in seen_ids:
                            # 权限过滤：内置角色(无 created_by)所有人可见，否则仅创建者可见
                            created_by = data.get("created_by")
                            if user_id is not None and created_by is not None and created_by != user_id:
                                continue  # 跳过其他用户创建的角色
                            seen_ids.add(char_id)
                            from funcation import model3d as _model3d
                            characters.append({
                                "id": char_id,
                                "name": data.get("name", char_id),
                                "description": data.get("description", ""),
                                "avatar": data.get("avatar", ""),
                                "created_by": created_by,
                                "model3d": _model3d.config_summary(data),
                            })
                    except:
                        pass

        return characters

    # ========== 世界管理 ==========

    def get_user_current_world_id(self, user_id):
        """获取该用户当前选中的世界 ID（per-user）"""
        from funcation.auth import SessionLocal, User
        db = SessionLocal()
        try:
            u = db.query(User).filter(User.id == user_id).first()
            if u and u.current_world_id:
                return u.current_world_id
            return "campus"
        finally:
            db.close()

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

    def set_user_current_world(self, user_id, world_id):
        """设置该用户当前选中的世界"""
        from funcation.auth import SessionLocal, User
        db = SessionLocal()
        try:
            u = db.query(User).filter(User.id == user_id).first()
            if u:
                u.current_world_id = world_id
                db.commit()
        finally:
            db.close()

    def load_user_current_world(self, user_id):
        """加载该用户当前世界的静态定义"""
        world_id = self.get_user_current_world_id(user_id)
        return self.load_world_by_id(world_id)

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

    def load_world_by_id(self, world_id):
        """根据ID加载世界定义"""
        # 优先从 data/worlds/ 读取
        for search_dir in [WORLDS_DIR, "worlds"]:
            path = os.path.join(search_dir, f"{world_id}.json")
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                continue
        return None

    def get_all_worlds(self):
        """获取所有世界列表"""
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
                                "description": data.get("description", "")
                            })
                    except:
                        pass

        return worlds

    # ========== 世界动态状态 (world_state/{world_id}.json) ==========

    def _get_world_state_path(self, world_id, user_id=None, mode="public"):
        """公共：data/world_state/{world_id}.json
        私人：data/world_state/{user_id}/{world_id}.json"""
        if mode == "private" and user_id is not None:
            return os.path.join(WORLD_STATE_DIR, str(user_id), f"{world_id}.json")
        return os.path.join(WORLD_STATE_DIR, f"{world_id}.json")

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

    # ========== NPC 社交网络 (world_state.npc_registry) ==========

    def ensure_npc_registry(self, world_data):
        """确保 npc_registry 结构完整"""
        runtime = world_data.setdefault("world_state", {})
        registry = runtime.setdefault("npc_registry", {})
        registry.setdefault("relationships", {})
        registry.setdefault("recent_interactions", [])
        registry.setdefault("gossip", [])
        registry.setdefault("world_impacts", [])
        return registry

    def get_npc_relationships(self, world_id=None, user_id=None, mode="public"):
        """获取角色间关系矩阵"""
        world_data = self.load_world_state(world_id, user_id, mode)
        registry = self.ensure_npc_registry(world_data)
        return registry.get("relationships", {})

    def get_npc_relationship(self, world_id, from_id, to_id, user_id=None, mode="public"):
        """获取两个角色之间的关系，不存在时返回默认值"""
        relationships = self.get_npc_relationships(world_id, user_id, mode)
        default = {"favorability": 50, "trust": 50, "intimacy": 30}
        return relationships.get(from_id, {}).get(to_id, default)

    def update_npc_relationship(self, world_id, from_id, to_id, deltas, user_id=None, mode="public"):
        """手动更新角色间关系 delta"""
        world_data = self.load_world_state(world_id, user_id, mode)
        registry = self.ensure_npc_registry(world_data)
        rel = registry["relationships"].setdefault(from_id, {}).setdefault(
            to_id,
            {"favorability": 50, "trust": 50, "intimacy": 30},
        )
        for key in ("favorability", "trust", "intimacy"):
            if key in deltas:
                rel[key] = max(0, min(100, rel.get(key, 50) + int(deltas[key])))
        world_data["world_state"]["npc_registry"] = registry
        self.save_world_state(world_id, world_data, user_id, mode)
        return rel

    # ========== 主动消息 ==========

    def get_proactive_message(self, user_id, character_id):
        """
        根据状态变化标记生成主动消息。
        优先检查 story/relationship/mood 变更标记，
        有变更时用 proactive_agent 生成上下文相关消息并清除标记；
        无变更时回退到基于好感度和时间的随机消息。
        """
        mem = self.load_memory(user_id, character_id)

        # ── 检查变更标记（世界事件优先） ──
        world_notice = mem.get("world_event_notice", {})

        # 多剧情：检查任意一条 active 剧情是否 changed
        stories = mem.get("stories", [])
        story_changed = any(s.get("changed") for s in stories if s.get("status") == "active")
        # 兼容旧格式
        old_story = mem.get("story", {})
        story_changed = story_changed or old_story.get("changed", False)

        # 合并剧情上下文（主线 + 支线摘要）
        active_stories = [s for s in stories if s.get("status") == "active"]
        main_story = next((s for s in active_stories if s.get("type") == "main"), None)
        story_title = main_story.get("title", "") if main_story else old_story.get("title", "")
        stage_texts = main_story.get("stages", []) if main_story else old_story.get("stages", [])
        stage_idx = main_story.get("stage", 0) if main_story else old_story.get("stage", 0)
        current_stage = stage_texts[stage_idx] if 0 <= stage_idx < len(stage_texts) else ""

        rel = mem.get("relationship", {})
        state = mem.get("character_state", {})

        world_event_changed = world_notice.get("changed", False)
        level_changed = rel.get("level_changed", False)
        mood_changed = state.get("mood_changed", False)

        has_change = (
            world_event_changed
            or story_changed
            or level_changed
            or mood_changed
        )

        if has_change:
            from funcation import proactive_agent

            # 加载角色信息
            try:
                character = self.load_character_by_id(character_id)
                char_name = character.get("name", "角色")
                char_personality = character.get("personality", "")
            except:
                char_name = "角色"
                char_personality = ""

            msg = proactive_agent.generate_proactive_message(
                character_name=char_name,
                character_personality=char_personality,
                world_event_changed=world_event_changed,
                world_event_type=world_notice.get("type", ""),
                world_event_title=world_notice.get("title", ""),
                world_event_description=world_notice.get("description", ""),
                world_event_progress=world_notice.get("progress", 0),
                story_changed=story_changed,
                story_title=story_title,
                current_stage_text=current_stage,
                level_changed=level_changed,
                new_level=rel.get("level", ""),
                level_reason=rel.get("last_reason", ""),
                mood_changed=mood_changed,
                new_mood=state.get("mood", ""),
            )

            # 清除已消费的标记
            changed = False
            if world_event_changed:
                world_notice.pop("changed", None)
                mem["world_event_notice"] = world_notice
                changed = True
            if story_changed:
                for s in mem.get("stories", []):
                    s.pop("changed", None)
                mem["story"] = mem.get("story", {})
                mem["story"].pop("changed", None)
                changed = True
            if level_changed:
                rel.pop("level_changed", None)
                mem["relationship"] = rel
                changed = True
            if mood_changed:
                state.pop("mood_changed", None)
                mem["character_state"] = state
                changed = True

            if changed:
                self.save_memory(user_id, character_id, mem)

            if msg:
                return msg

        # ── 回退：基于好感度和时间的随机消息 ──
        favorability = mem.get("favorability", 50)
        last_time = mem.get("last_chat_time")

        minutes = 0
        if last_time:
            try:
                last = datetime.fromisoformat(last_time)
                diff = datetime.now() - last
                minutes = diff.total_seconds() / 60
            except:
                pass

        low_messages = [
            "哦，又来了。",
            "今天居然还在。",
            "……有事？",
        ]

        normal_messages = [
            "你来了。",
            "今天怎么样？",
            "在忙吗？",
        ]

        high_messages = [
            "终于来了。",
            "我刚刚还在想你。",
            "今天过得怎么样？",
            "怎么现在才来。",
        ]

        if minutes > 30:
            return "……你终于想起我了？"

        if favorability < 30:
            return random.choice(low_messages)
        elif favorability < 70:
            return random.choice(normal_messages)
        else:
            return random.choice(high_messages)
