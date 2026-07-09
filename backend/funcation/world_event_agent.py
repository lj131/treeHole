"""
World Event Agent - 世界事件管理

职责：
- 世界事件生成 / 推进 / 结束
- 影响角色状态 (character_state)
- 联动 StoryAgent
- 触发 ProactiveAgent 主动消息

数据统一存储于 MemoryCenter.load_world_state() → data/world_state/{world_id}.json
"""

import json
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

PROGRESS_STEP = 20
MAX_CONCURRENT_EVENTS = 2
VALID_MOODS = {"开心", "平静", "低落", "生气", "疲惫"}


# ============================================================
# 环境上下文
# ============================================================

def get_season():
    month = datetime.now().month
    if month in (3, 4, 5):
        return "春"
    if month in (6, 7, 8):
        return "夏"
    if month in (9, 10, 11):
        return "秋"
    return "冬"


def get_time_period():
    hour = datetime.now().hour
    if 5 <= hour < 12:
        return "上午"
    if 12 <= hour < 18:
        return "下午"
    if 18 <= hour < 22:
        return "傍晚"
    return "夜间"


def _season_weather_pool(season):
    pools = {
        "春": ["晴", "多云", "小雨", "微风"],
        "夏": ["晴", "高温", "雷阵雨", "闷热"],
        "秋": ["晴", "多云", "大风", "降温"],
        "冬": ["晴", "阴", "小雪", "寒冷"],
    }
    import random
    return random.choice(pools.get(season, ["晴"]))


def refresh_world_metadata(world_data):
    """更新世界运行时环境（季节、天气、时间段）"""
    runtime = world_data.setdefault("world_state", {})
    season = get_season()
    runtime["season"] = season
    runtime["time_period"] = get_time_period()
    if not runtime.get("weather"):
        runtime["weather"] = _season_weather_pool(season)
    return world_data


# ============================================================
# JSON 工具
# ============================================================

def _parse_json_response(content):
    content = (
        content.replace("```json", "")
        .replace("```", "")
        .strip()
    )
    content = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", content)
    return json.loads(content)


def _normalize_event(raw, world_id=""):
    """标准化事件结构"""
    importance = raw.get("importance", 5)
    try:
        importance = int(importance)
    except (TypeError, ValueError):
        importance = 5
    importance = max(1, min(10, importance))

    progress = raw.get("progress", 0)
    try:
        progress = int(progress)
    except (TypeError, ValueError):
        progress = 0
    progress = max(0, min(100, progress))

    status = raw.get("status", "running")
    if status not in ("running", "finished"):
        status = "running"

    impact = raw.get("impact", [])
    if not isinstance(impact, list):
        impact = [str(impact)] if impact else []

    now = datetime.now().strftime("%Y-%m-%d")

    return {
        "id": raw.get("id") or str(uuid.uuid4()),
        "title": raw.get("title", "未命名事件"),
        "description": raw.get("description", ""),
        "importance": importance,
        "status": status,
        "progress": progress,
        "impact": impact,
        "world_id": raw.get("world_id", world_id),
        "created_at": raw.get("created_at", now),
        "finished_at": raw.get("finished_at", ""),
    }


# ============================================================
# 事件生成
# ============================================================

def generate_world_event(world_def, world_data):
    """
    根据世界设定、历史、季节、天气、时间段生成新事件。
    返回标准化事件 dict，失败时返回 None。
    """
    runtime = world_data.get("world_state", {})
    current_titles = [
        e.get("title", "")
        for e in world_data.get("current_events", [])
        if e.get("status") == "running"
    ]
    history_titles = [
        e.get("title", "")
        for e in world_data.get("history_events", [])[-10:]
    ]

    prompt = f"""
你是世界观事件设计师。

世界名称：{world_def.get("name", "")}
世界背景：{world_def.get("background", "")}
世界描述：{world_def.get("description", "")}

当前环境：
- 季节：{runtime.get("season", get_season())}
- 天气：{runtime.get("weather", "晴")}
- 时间段：{runtime.get("time_period", get_time_period())}

正在进行的事件：{json.dumps(current_titles, ensure_ascii=False)}
近期历史事件：{json.dumps(history_titles, ensure_ascii=False)}

请生成一个符合该世界观的新世界事件（不是单个角色的私事，而是影响整个环境的大事件）。

返回 JSON：
{{
    "title": "",
    "description": "",
    "importance": 5,
    "impact": ["对角色的可能影响1", "对角色的可能影响2"]
}}

规则：
1. importance 范围 1~10
2. 禁止生成不符合世界观的事件
3. 不要与正在进行的事件重复
4. 校园世界示例：运动会、期末周、社团招新、停电、校庆
5. 都市世界示例：音乐节、台风、商场活动、地铁故障
6. 只返回 JSON
"""

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=1,
            response_format={"type": "json_object"},
        )
        data = _parse_json_response(response.choices[0].message.content)
        event = _normalize_event(data, world_def.get("id", ""))
        event["status"] = "running"
        event["progress"] = 0
        return event
    except Exception as e:
        print(f"[world_event_agent] 生成事件失败: {e}")
        return None


# ============================================================
# 事件推进与归档
# ============================================================

def advance_event(event):
    """推进单个事件进度，返回 (event, notification_type | None)"""
    if event.get("status") != "running":
        return event, None

    old_progress = event.get("progress", 0)
    new_progress = min(100, old_progress + PROGRESS_STEP)
    event["progress"] = new_progress

    if new_progress >= 100:
        event["status"] = "finished"
        event["finished_at"] = datetime.now().strftime("%Y-%m-%d")
        return event, "finished"

    if new_progress != old_progress:
        return event, "advanced"

    return event, None


def archive_finished_event(world_data, event):
    """将已结束事件移入历史"""
    world_data.setdefault("history_events", []).append(event)
    world_data["current_events"] = [
        e for e in world_data.get("current_events", [])
        if e.get("id") != event.get("id")
    ]
    if len(world_data["history_events"]) > 100:
        world_data["history_events"] = world_data["history_events"][-100:]
    return world_data


def count_running_events(world_data):
    return sum(
        1 for e in world_data.get("current_events", [])
        if e.get("status") == "running"
    )


# ============================================================
# 角色影响
# ============================================================

def apply_character_impact(memory_center, user_id, character, event, world_def):
    """世界事件影响角色 character_state（结合性格、当前状态、剧情）"""
    character_id = character["id"]
    memory_data = memory_center.load_memory(user_id, character_id)
    state = memory_data.get("character_state", {})
    story = memory_data.get("story", {})

    old_mood = state.get("mood", "开心")

    prompt = f"""
你是角色状态分析器。

角色：
- 名字：{character.get("name", "")}
- 性格：{character.get("personality", "")}
- 设定：{character.get("description", "")}

当前状态：
{json.dumps(state, ensure_ascii=False)}

当前剧情：
- 标题：{story.get("title", "")}
- 阶段：{story.get("stage", 0)}

世界：{world_def.get("name", "")}

世界事件：
- 标题：{event.get("title", "")}
- 描述：{event.get("description", "")}
- 重要度：{event.get("importance", 5)}
- 可能影响：{json.dumps(event.get("impact", []), ensure_ascii=False)}

请分析该世界事件对此角色的影响，返回 JSON：
{{
    "mood": "开心",
    "energy_delta": 0,
    "personal_reaction": "角色对此事件的个人感受（一句话）",
    "current_event_title": "角色正在经历的具体事情",
    "current_event_description": "详细说明"
}}

规则：
1. mood 只能是：开心、平静、低落、生气、疲惫
2. energy_delta 范围 -30 到 30
3. 不同性格的角色对同一事件应有不同反应
4. 只返回 JSON
"""

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            response_format={"type": "json_object"},
        )
        result = _parse_json_response(response.choices[0].message.content)

        mood = result.get("mood", old_mood)
        if mood not in VALID_MOODS:
            mood = old_mood

        energy = state.get("energy", 80)
        try:
            delta = int(result.get("energy_delta", 0))
        except (TypeError, ValueError):
            delta = 0
        energy = max(0, min(100, energy + delta))

        state["mood"] = mood
        state["energy"] = energy
        if mood != old_mood:
            state["mood_changed"] = True

        state["current_event"] = {
            "title": result.get("current_event_title", event.get("title", "")),
            "description": result.get(
                "current_event_description",
                event.get("description", ""),
            ),
            "world_event_id": event.get("id", ""),
            "world_event_title": event.get("title", ""),
            "impact": delta,
            "event_date": datetime.now().strftime("%Y-%m-%d"),
        }

        memory_data["character_state"] = state
        memory_center.save_memory(user_id, character_id, memory_data)
        return result

    except Exception as e:
        print(f"[world_event_agent] 角色影响分析失败: {e}")
        return None


# ============================================================
# 剧情联动
# ============================================================

def link_story(memory_center, user_id, character, event, notification_type, world_def):
    """
    世界事件推动个人剧情（多剧情版）。

    逻辑:
    - 高重要度(≥7)或事件结束/新建时，触发联动
    - 1) 先用 LLM 判断是否推动现有主线
    - 2) 如果重要度极高(≥8)或主线没法推，再考虑生成一条支线剧情
    """
    character_id = character["id"]
    memory_data = memory_center.load_memory(user_id, character_id)
    stories = memory_data.get("stories", [])

    # 取主线 active
    main_story = next(
        (s for s in stories if s.get("type") == "main" and s.get("status") == "active"),
        None,
    )

    importance = event.get("importance", 5)
    should_link = (
        importance >= 7
        or notification_type == "finished"
        or notification_type == "created"
    )

    if not should_link:
        return False

    advanced_main = False
    side_created = False

    # ── 1) 尝试推动主线 ──
    if main_story:
        advanced_main = _try_advance_main_story(
            memory_center, user_id, character_id, character,
            main_story, event, notification_type, world_def, memory_data,
        )

    # ── 2) 重要度极高或主线已结束/无法推动 → 生成支线 ──
    if importance >= 8 or (not advanced_main and importance >= 7):
        try:
            from funcation import story_agent
            side = story_agent.trigger_side_story(
                memory_center, user_id, character, world_def, event, notification_type,
            )
            side_created = side is not None
        except Exception as exc:
            print(f"[world_event_agent] 触发支线失败: {exc}")

    return advanced_main or side_created


def _try_advance_main_story(
    memory_center, user_id, character_id, character,
    main_story, event, notification_type, world_def, memory_data,
):
    """LLM 判断是否推动主线，并执行 stage+1。返回 True/False。"""
    prompt = f"""
你是剧情联动设计师。

角色：{character.get("name", "")}（{character.get("personality", "")}）
世界：{world_def.get("name", "")}

世界事件：{event.get("title", "")} — {event.get("description", "")}
事件状态：{notification_type}（progress={event.get("progress", 0)}）

当前主线剧情：
- 标题：{main_story.get("title", "")}
- 当前阶段 index：{main_story.get("stage", 0)}
- 阶段内容：{main_story.get("stages", [])}

判断此世界事件是否应推动角色主线剧情。

返回 JSON：
{{
    "should_advance": true,
    "reason": "简短原因"
}}

规则：
1. 只有事件与角色剧情有合理关联时才 advance
2. 只返回 JSON
"""

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            response_format={"type": "json_object"},
        )
        result = _parse_json_response(response.choices[0].message.content)

        if not result.get("should_advance"):
            return False

        max_stage = main_story.get("max_stage", 0)
        current = main_story.get("stage", 0)
        if current < max_stage:
            main_story["stage"] = current + 1
            main_story["changed"] = True
            main_story["world_event_link"] = {
                "event_id": event.get("id", ""),
                "event_title": event.get("title", ""),
                "reason": result.get("reason", ""),
            }
            from datetime import datetime as _dt
            main_story["last_advance_date"] = _dt.now().strftime("%Y-%m-%d")

            # 写回 stories 数组
            stories = memory_data.get("stories", [])
            for i, s in enumerate(stories):
                if s.get("id") == main_story.get("id"):
                    stories[i] = main_story
                    break
            memory_data["stories"] = stories
            memory_center.save_memory(user_id, character_id, memory_data)
            return True

    except Exception as e:
        print(f"[world_event_agent] _try_advance_main_story 失败: {e}")

    return False


# ============================================================
# 主动消息标记
# ============================================================

def mark_proactive_notice(memory_center, user_id, character_id, notification_type, event):
    """在世界事件变化时标记 proactive 触发"""
    memory_data = memory_center.load_memory(user_id, character_id)
    memory_data["world_event_notice"] = {
        "changed": True,
        "type": notification_type,
        "title": event.get("title", ""),
        "description": event.get("description", ""),
        "progress": event.get("progress", 0),
        "importance": event.get("importance", 5),
    }
    memory_center.save_memory(user_id, character_id, memory_data)


def apply_world_impact_to_user(memory_center, user_id, character, world_def, notifications, mode="public"):
    """对单个用户应用世界事件影响：角色状态 + 剧情 + proactive。
    公共世界（mode='public'）用角色 memory 的 seen_world_event_ids 去重，只对未见事件补影响。
    私人世界（mode='private'）演化即影响，不做去重。"""
    if not notifications:
        return {"applied": 0}

    character_id = character["id"]

    if mode == "public":
        memory_data = memory_center.load_memory(user_id, character_id)
        seen = set(memory_data.get("seen_world_event_ids", []))
        unseen = [
            n for n in notifications
            if n.get("event", {}).get("id") not in seen
        ]
    else:
        unseen = list(notifications)

    applied = 0
    for notif in unseen:
        event = notif["event"]
        notif_type = notif["type"]
        apply_character_impact(memory_center, user_id, character, event, world_def)
        link_story(memory_center, user_id, character, event, notif_type, world_def)
        mark_proactive_notice(memory_center, user_id, character_id, notif_type, event)
        applied += 1

    # 公共世界：把已处理事件 id 追加到 seen_world_event_ids（FIFO，最多保留 200 条）
    if mode == "public" and unseen:
        memory_data = memory_center.load_memory(user_id, character_id)
        seen_list = memory_data.get("seen_world_event_ids", [])
        for n in unseen:
            eid = n.get("event", {}).get("id")
            if eid and eid not in seen_list:
                seen_list.append(eid)
        memory_data["seen_world_event_ids"] = seen_list[-200:]
        memory_center.save_memory(user_id, character_id, memory_data)

    return {"applied": applied}


def process_notifications(memory_center, user_id, character, world_def, notifications):
    """处理 tick 产生的所有通知：角色影响 + 剧情 + proactive"""
    for notif in notifications:
        event = notif["event"]
        notif_type = notif["type"]
        apply_character_impact(memory_center, user_id, character, event, world_def)
        link_story(memory_center, user_id, character, event, notif_type, world_def)
        mark_proactive_notice(
            memory_center,
            user_id,
            character["id"],
            notif_type,
            event,
        )


# ============================================================
# 核心 Tick
# ============================================================

def evolve_world(memory_center, world_def, user_id, mode, force=False):
    """纯世界演化：推进事件 + 生成新事件 + 环境更新 + NPC 互动。
    不碰角色记忆。公共世界按 last_tick_date 当天幂等（避免多用户重复演化）。

    返回 {action, world_id, mode, notifications, current_events, world_state, npc_interaction?}
    """
    world_id = world_def.get("id") or "campus"
    world_data = memory_center.load_world_state(world_id, user_id, mode)
    world_data = refresh_world_metadata(world_data)

    today = datetime.now().strftime("%Y-%m-%d")
    runtime = world_data.setdefault("world_state", {})
    last_tick = runtime.get("last_tick_date", "")

    if not force and last_tick == today:
        return {
            "action": "skipped",
            "reason": "already_ticked_today",
            "world_id": world_id,
            "mode": mode,
            "notifications": [],
            "current_events": world_data.get("current_events", []),
            "world_state": runtime,
        }

    notifications = []
    updated_events = []

    for event in list(world_data.get("current_events", [])):
        if event.get("status") != "running":
            updated_events.append(event)
            continue

        event, notif_type = advance_event(event)

        if notif_type == "finished":
            notifications.append({"type": "finished", "event": dict(event)})
            world_data = archive_finished_event(world_data, event)
        else:
            updated_events.append(event)
            if notif_type:
                notifications.append({"type": notif_type, "event": dict(event)})

    world_data["current_events"] = updated_events

    if count_running_events(world_data) < MAX_CONCURRENT_EVENTS:
        new_event = generate_world_event(world_def, world_data)
        if new_event:
            world_data.setdefault("current_events", []).append(new_event)
            notifications.append({"type": "created", "event": dict(new_event)})
            runtime["last_event_gen_date"] = today

    runtime["last_tick_date"] = today
    world_data["world_state"] = runtime
    memory_center.save_world_state(world_id, world_data, user_id, mode)

    result = {
        "action": "ticked",
        "world_id": world_id,
        "mode": mode,
        "notifications": notifications,
        "current_events": world_data.get("current_events", []),
        "world_state": runtime,
    }

    # NPC 互动（纯世界层，每天一次）
    if notifications:
        last_interaction = runtime.get("last_interaction_date", "")
        if last_interaction != today:
            from funcation import interaction_agent

            trigger_event = notifications[-1]["event"]
            interaction_result = interaction_agent.run_interaction(
                memory_center,
                world_def,
                trigger_event,
                user_id,
                mode,
            )
            if interaction_result.get("action") == "simulated":
                runtime["last_interaction_date"] = today
                world_data["world_state"] = runtime
                memory_center.save_world_state(world_id, world_data, user_id, mode)
            result["npc_interaction"] = interaction_result

    return result


def tick(memory_center, user_id, character, world_def, force=False):
    """兼容 shim：按用户当前 world mode 路由。
    公共世界 → evolve_world（首个触发者演化，其余当天幂等）+ apply_world_impact_to_user（未见事件去重）
    私人世界 → evolve_world + apply_world_impact_to_user（全量影响）

    调用方（/chat、/chat/stream、调度器、/world/tick）无需感知 mode。
    """
    mode = memory_center.get_user_world_mode(user_id)
    world_id = world_def.get("id") or "campus"

    evolve_result = evolve_world(memory_center, world_def, user_id, mode, force=force)

    notifications = evolve_result.get("notifications", [])
    if notifications and character:
        apply_world_impact_to_user(
            memory_center, user_id, character, world_def, notifications, mode
        )

    return {
        "action": evolve_result.get("action"),
        "world_id": world_id,
        "mode": mode,
        "notifications": notifications,
        "current_events": evolve_result.get("current_events", []),
        "world_state": evolve_result.get("world_state", {}),
    }


# ============================================================
# CRUD（供 API 调用）
# ============================================================

def create_event(memory_center, world_def, event_data=None, auto_generate=False, user_id=None, mode="public"):
    """手动创建或 AI 自动生成世界事件"""
    world_id = world_def.get("id") or "campus"
    world_data = memory_center.load_world_state(world_id, user_id, mode)
    world_data = refresh_world_metadata(world_data)

    if auto_generate or not event_data:
        event = generate_world_event(world_def, world_data)
        if not event:
            return None, world_data
    else:
        event = _normalize_event(event_data, world_id)
        event["status"] = "running"

    world_data.setdefault("current_events", []).append(event)
    memory_center.save_world_state(world_id, world_data, user_id, mode)
    return event, world_data


def update_event(memory_center, world_id, event_id, updates, user_id=None, mode="public"):
    """更新指定世界事件"""
    world_data = memory_center.load_world_state(world_id, user_id, mode)
    found = None

    for event in world_data.get("current_events", []):
        if event.get("id") == event_id:
            found = event
            break

    if not found:
        return None, world_data, None

    if "title" in updates and updates["title"] is not None:
        found["title"] = updates["title"]
    if "description" in updates and updates["description"] is not None:
        found["description"] = updates["description"]
    if "importance" in updates and updates["importance"] is not None:
        found["importance"] = max(1, min(10, int(updates["importance"])))
    if "progress" in updates and updates["progress"] is not None:
        found["progress"] = max(0, min(100, int(updates["progress"])))
    if "status" in updates and updates["status"] is not None:
        found["status"] = updates["status"]
        if found["status"] == "finished" and found["progress"] < 100:
            found["progress"] = 100

    notification_type = None
    if found.get("status") == "finished" and found.get("progress", 0) >= 100:
        notification_type = "finished"
        world_data = archive_finished_event(world_data, found)
    elif "progress" in updates:
        notification_type = "advanced"

    memory_center.save_world_state(world_id, world_data, user_id, mode)
    return found, world_data, notification_type


def get_world_snapshot(memory_center, world_def, user_id=None, mode="public"):
    """获取世界静态定义 + 动态状态完整快照"""
    world_id = world_def.get("id") or "campus"
    world_data = memory_center.load_world_state(world_id, user_id, mode)
    world_data = refresh_world_metadata(world_data)
    memory_center.save_world_state(world_id, world_data, user_id, mode)

    return {
        "world": world_def,
        "world_id": world_id,
        "world_state": world_data.get("world_state", {}),
        "current_events": world_data.get("current_events", []),
        "history_events": world_data.get("history_events", []),
    }
