"""
Story Agent — 多剧情线管理

支持同时进行主线 + 支线，好感度/行为触发分支存档，world_event 联动生成支线。

数据模型:
  memory_data["stories"] = [Story1, Story2, ...]
  memory_data["story_history"] = [CompletedStory, ...]

Story dict:
  - id: str (uuid)
  - title: str
  - description: str
  - type: "main" | "side"
  - status: "active" | "paused" | "completed"
  - stage: int (当前阶段 index)
  - max_stage: int
  - stages: list[str]
  - branch_points: list[{stage, at, reason, favorability}]
  - tags: list[str]
  - started_at: str (ISO date)
  - last_advance_date: str (ISO date)
  - changed: bool (供 proactive 检测)
"""

import json
import logging
import os
import re
import uuid
from datetime import datetime

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url=os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com"),
)

logger = logging.getLogger(__name__)

# 好感度阈值（用于分支判定）
FAVOR_BRANCH_THRESHOLDS = [25, 50, 75]
# 每天最多推进多少个故事（防止一次 /chat 推进太多）
MAX_ADVANCE_PER_DAY = 2


# ============================================================
# 工具函数
# ============================================================

def _parse_json(content: str) -> dict | None:
    content = content.replace("```json", "").replace("```", "").strip()
    content = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", content)
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        logger.error("[story_agent] JSON 解析失败: %s", content[:200])
        return None


def _now_date() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _new_story(title, description, stages, story_type="main"):
    """创建标准化的故事 dict"""
    now = _now_date()
    return {
        "id": str(uuid.uuid4()),
        "title": title,
        "description": description,
        "type": story_type,
        "status": "active",
        "stage": 0,
        "max_stage": len(stages) - 1,
        "stages": stages,
        "branch_points": [],
        "tags": [],
        "started_at": now,
        "last_advance_date": now,
        "changed": True,
    }


# ============================================================
# LLM 生成
# ============================================================

def generate_story(character, world, existing_stories=None, story_type="main"):
    """LLM 生成新剧情。story_type="main" | "side"

    参数:
        existing_stories: 已有剧情列表（避免重复/冲突）
    """
    existing_titles = []
    if existing_stories:
        existing_titles = [s.get("title", "") for s in existing_stories if s.get("status") == "active"]

    type_hint = "主线" if story_type == "main" else "支线"
    type_desc = (
        "这是角色的主要剧情线，需要贯穿整个世界设定，有深度、有连续性。"
        if story_type == "main"
        else "这是由世界事件触发的支线剧情，可以短小一些（3~5阶段），与该世界事件相关。"
    )

    prompt = f"""
你是剧情设计师。

角色：
- 名字：{character.get("name", "")}
- 性格：{character.get("personality", "")}
- 设定：{character.get("description", "")}

世界：
- 名称：{world.get("name", "")}
- 背景：{world.get("background", "")}

已有{type_hint}：{json.dumps(existing_titles, ensure_ascii=False)}

请生成一条{type_hint}剧情。
{type_desc}

返回 JSON：
{{
    "title": "",
    "description": "",
    "stages": ["阶段1", "阶段2", ...],
    "tags": ["标签1", "标签2"]
}}

规则：
1. {type_hint}至少 5 个阶段（主线）或 3 个阶段（支线）
2. 阶段具有连续性，后一阶段基于前一阶段自然发展
3. 符合角色性格和世界观
4. 不要和已有剧情重复或冲突（可以是互补视角）
5. 只返回 JSON
"""
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=1,
            response_format={"type": "json_object"},
        )
        data = _parse_json(response.choices[0].message.content)
        if not data or not data.get("stages"):
            return None
        return _new_story(
            title=data["title"],
            description=data.get("description", ""),
            stages=data["stages"],
            story_type=story_type,
        )
    except Exception as e:
        logger.error("[story_agent] generate_story 失败: %s", e)
        return None


# ============================================================
# 推进与分支
# ============================================================

def get_current_stage(story):
    """获取当前阶段文本"""
    stages = story.get("stages", [])
    stage = story.get("stage", 0)
    if not stages:
        return ""
    if stage >= len(stages):
        stage = len(stages) - 1
    return stages[stage]


def is_story_finished(story):
    """判断剧情是否推进到了终点"""
    return story.get("stage", 0) >= story.get("max_stage", 0)


def archive_story(story):
    """完成一条剧情 → 移入 story_history 格式"""
    now = _now_date()
    return {
        "id": story.get("id", ""),
        "title": story.get("title", ""),
        "type": story.get("type", "main"),
        "stages": story.get("stages", []),
        "branch_points": story.get("branch_points", []),
        "total_stages": (story.get("max_stage", 0) + 1),
        "completed_at": story.get("last_advance_date", now),
    }


def advance_story(story, memory_data):
    """推进单条剧情 stage +1，检查是否触发分支。

    返回: (story, branch_created)
         branch_created: bool — 是否在此次推进中创建了分支点
    """
    if is_story_finished(story):
        return story, False

    old_stage = story.get("stage", 0)
    new_stage = old_stage + 1
    story["stage"] = new_stage
    story["last_advance_date"] = _now_date()
    story["changed"] = True

    # 分支判定
    branch_created = _check_branch_condition(story, memory_data)
    return story, branch_created


def _check_branch_condition(story, memory_data):
    """在推进时检查是否触发分支。

    触发条件（任一）:
    1. 好感度穿越阈值（25/50/75）
    2. 角色心情有 mood_changed 标记
    3. 当前 stage 已有分支点（不重复记录）

    返回 True 表示新建了一个分支点。
    """
    favorability = memory_data.get("favorability", 50)
    stage = story.get("stage", 0)
    branch_points = story.get("branch_points", [])

    # 检查此 stage 是否已有分支点
    for bp in branch_points:
        if bp.get("stage") == stage:
            return False

    # 好感度阈值穿越判定
    crossed = False
    for threshold in FAVOR_BRANCH_THRESHOLDS:
        # 如果好感度刚好接近阈值，触发分支
        if abs(favorability - threshold) <= 5:
            crossed = True
            break

    # 心情变化也触发
    state = memory_data.get("character_state", {})
    mood_changed = state.get("mood_changed", False)

    if not crossed and not mood_changed:
        return False

    if crossed:
        reason = f"好感度达到{favorability}，关系进入新阶段"
    else:
        mood = state.get("mood", "")
        reason = f"角色心情变化（{mood}），故事走向可能不同"

    # 用 LLM 确认分支方向
    _create_branch(story, stage, reason, favorability, memory_data)
    return True


def _create_branch(story, stage, reason, favorability, memory_data):
    """用 LLM 生成分支描述并记录"""
    current_stage_text = story["stages"][stage] if stage < len(story["stages"]) else ""
    next_stage_text = story["stages"][stage + 1] if stage + 1 < len(story["stages"]) else ""
    character_state = memory_data.get("character_state", {})
    profile = memory_data.get("profile", {})

    prompt = f"""
你是剧情分支分析师。

剧情：{story.get("title", "")}
当前阶段：{current_stage_text}
下一阶段（原路线）：{next_stage_text}

触发分支的原因：{reason}
当前好感度：{favorability}
角色心情：{character_state.get("mood", "未知")}
用户情绪：{profile.get("mood", "未知")}

请用一句话描述：如果好感度影响剧情走向，这条支线会是什么方向？
不要重写剧情，只需要给出分支方向的描述。

回复格式（只返回 JSON）：
{{"alt_direction": "基于当前情况，剧情可能走向浪漫/冲突/温馨 等方向..."}}
"""
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            response_format={"type": "json_object"},
        )
        data = _parse_json(response.choices[0].message.content)
        alt_direction = data.get("alt_direction", "") if data else ""

        branch_points = story.setdefault("branch_points", [])
        branch_points.append({
            "stage": stage,
            "at": _now_date(),
            "reason": reason,
            "favorability": favorability,
            "alt_direction": alt_direction,
        })
        logger.info("[story_agent] 分支存档: %s stage=%d reason=%s", story.get("title"), stage, reason)
    except Exception as e:
        logger.error("[story_agent] _create_branch 失败: %s", e)


# ============================================================
# sync: 将 active 剧情反映到 character_state
# ============================================================

def sync_stories_to_state(memory_data):
    """将当前激活的主线剧情反映到 character_state.current_event

    如果有 world event 激活，不覆盖。
    多剧情时只取主线（type="main"）。
    """
    state = memory_data.get("character_state", {})

    # 如果有 world event 占据 current_event，不覆盖
    current_event = state.get("current_event", {})
    if isinstance(current_event, dict) and current_event.get("world_event_id"):
        return memory_data

    stories = memory_data.get("stories", [])
    active_main = None
    for s in stories:
        if s.get("type") == "main" and s.get("status") == "active":
            active_main = s
            break

    if not active_main:
        return memory_data

    current_stage = get_current_stage(active_main)
    if current_stage:
        state["current_event"] = {
            "title": current_stage,
            "description": active_main.get("description", ""),
            "story_id": active_main.get("id", ""),
            "impact": 0,
        }

    memory_data["character_state"] = state
    return memory_data


# ============================================================
# 主入口: check_stories
# ============================================================

def check_stories(mc, user_id, character, world, force_advance=False):
    """主入口：推进已有故事 + 必要时生成新故事。

    Args:
        mc: MemoryCenter 实例
        force_advance: True=强制推进（后台 tick 用），False=按 last_advance_date 限流
    """
    character_id = character["id"]
    memory_data = mc.load_memory(user_id, character_id)

    today = _now_date()
    stories = memory_data.setdefault("stories", [])

    advanced_count = 0
    new_story_created = False
    completed_stories = []

    for story in list(stories):  # 遍历副本，因为可能修改列表
        if story.get("status") != "active":
            continue

        # 是否已处理过（同一天不重复推）
        if not force_advance and story.get("last_advance_date") == today:
            continue

        if is_story_finished(story):
            # 已完成的故事归档，后续生成新的替换
            completed_stories.append(story)
            memory_data["story_history"] = memory_data.setdefault("story_history", [])
            memory_data["story_history"].append(archive_story(story))
            continue

        # 推进
        if advanced_count >= MAX_ADVANCE_PER_DAY:
            break

        story, branch = advance_story(story, memory_data)
        advanced_count += 1

    # 移除已归档的故事
    for cs in completed_stories:
        stories.remove(cs)

    # 主线没了 → 生成新的
    has_active_main = any(s.get("type") == "main" and s.get("status") == "active" for s in stories)
    if not has_active_main:
        new_story = generate_story(character, world, stories, story_type="main")
        if new_story:
            stories.append(new_story)
            new_story_created = True
            logger.info("[story_agent] 新主线生成: %s", new_story.get("title"))

    memory_data["stories"] = stories
    mc.save_memory(user_id, character_id, memory_data)
    return {
        "advanced": advanced_count,
        "new_story": new_story_created,
        "completed": len(completed_stories),
        "active_count": len([s for s in stories if s.get("status") == "active"]),
    }


# ============================================================
# world_event 联动：生成支线
# ============================================================

def trigger_side_story(mc, user_id, character, world, event, notification_type):
    """从世界事件触发生成一条支线剧情。

    在 world_event_agent.link_story() 中调用。
    返回生成的 story dict 或 None。
    """
    character_id = character["id"]
    memory_data = mc.load_memory(user_id, character_id)
    stories = memory_data.get("stories", [])

    # 避免同一事件重复生成支线
    for s in stories:
        if s.get("world_event_id") == event.get("id"):
            return None

    # 已有过多 active 支线不生成
    active_side_count = sum(
        1 for s in stories if s.get("type") == "side" and s.get("status") == "active"
    )
    if active_side_count >= 3:
        return None

    # 构造"世界-角色联动" prompt
    prompt = f"""
你是剧情设计师。

角色：{character.get("name", "")}（{character.get("personality", "")}）
世界：{world.get("name", "")}

世界事件：{event.get("title", "")} — {event.get("description", "")}
事件状态：{notification_type}（进度 {event.get("progress", 0)}%）

已有剧情：{json.dumps([s.get("title") for s in stories if s.get("status") == "active"], ensure_ascii=False)}

请基于这个世界事件生成一条短支线剧情（3~5 阶段）：
- 这条支线描述该角色如何受世界事件影响
- 支线结束时应该自然回归主线

返回 JSON：
{{
    "title": "",
    "description": "",
    "stages": ["阶段1", "阶段2", ...],
    "tags": ["标签1"]
}}

规则：
1. 3~5 个阶段
2. 角色性格影响反应方式
3. 不要和已有剧情冲突
4. 只返回 JSON
"""
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=1,
            response_format={"type": "json_object"},
        )
        data = _parse_json(response.choices[0].message.content)
        if not data or not data.get("stages"):
            return None

        side = _new_story(
            title=data["title"],
            description=data.get("description", ""),
            stages=data["stages"],
            story_type="side",
        )
        side["world_event_id"] = event.get("id", "")
        side["tags"] = data.get("tags", ["世界事件"])

        stories.append(side)
        memory_data["stories"] = stories
        mc.save_memory(user_id, character_id, memory_data)

        logger.info("[story_agent] 支线生成（世界事件联动）: %s", side.get("title"))
        return side
    except Exception as e:
        logger.error("[story_agent] trigger_side_story 失败: %s", e)
        return None


# ============================================================
# 兼容旧调用（/chat 和 /chat/stream 仍调 check_story）
# ============================================================

# 下面保持旧的 check_story / sync_story_to_state 作为兼容垫片，
# 新代码应调 check_stories / sync_stories_to_state。


def check_story(mc, user_id, character, world):
    """[兼容] 旧 check_story → 新 check_stories，参数完全兼容。"""
    return check_stories(mc, user_id, character, world)


def sync_story_to_state(memory_data):
    """[兼容] 旧 sync_story_to_state → 新 sync_stories_to_state。"""
    return sync_stories_to_state(memory_data)