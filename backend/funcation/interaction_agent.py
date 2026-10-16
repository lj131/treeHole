"""
Multi Character Interaction Agent

模拟多个 NPC 角色之间的互动、关系变化、信息传播与社会影响。
在世界 tick 或世界事件变化时调用，使世界在用户不在线时持续运转。
"""

import json
import logging
import os
import re
from datetime import datetime

from dotenv import load_dotenv
from openai import OpenAI

from funcation import tension

logger = logging.getLogger(__name__)

load_dotenv()

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url=os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com"),
)

DEFAULT_RELATIONSHIP = {
    "favorability": 50,
    "trust": 50,
    "intimacy": 30,
}

MAX_INTERACTION_LOG = 20
MAX_GOSSIP = 30
MAX_NPC_MEMORIES_PER_RUN = 5


def _parse_json_response(content):
    content = (
        content.replace("```json", "")
        .replace("```", "")
        .strip()
    )
    content = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", content)
    return json.loads(content)


def _clamp(value, low=0, high=100):
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = 0
    return max(low, min(high, value))


def _normalize_result(raw):
    """标准化 Agent 输出结构"""
    return {
        "interaction_summary": raw.get("interaction_summary", ""),
        "dialogues": raw.get("dialogues", []) if isinstance(raw.get("dialogues"), list) else [],
        "relationship_changes": (
            raw.get("relationship_changes", [])
            if isinstance(raw.get("relationship_changes"), list)
            else []
        ),
        "new_memories": (
            raw.get("new_memories", [])
            if isinstance(raw.get("new_memories"), list)
            else []
        ),
        "gossip_events": (
            raw.get("gossip_events", [])
            if isinstance(raw.get("gossip_events"), list)
            else []
        ),
        "world_impact": raw.get("world_impact", ""),
    }


def _tension_section(tension_level: int) -> str:
    """按张力等级生成 prompt 段落。

    **为什么要显式分级**：prompt 里原本就有负向 delta 示例（争吵 -10 / 背叛 -20），
    但没有任何指令鼓励生成冲突，LLM 默认倾向"和谐" → 实测 NPC 关系只涨不跌。
    分级后由**代码**决定这轮该不该有张力（见 `funcation/tension.py`），
    prompt 只负责"怎么吵得自然"。

    ⚠️ **每个等级都必须给"缓和/修复"的出口** —— 否则关系一路跌到底，世界会崩，
    用户也会觉得"这个角色怎么天天在生气"。
    """
    level = int(tension_level or 0)

    if level >= 2:
        return """本轮互动**应包含一次明显冲突**。

- 形式：争吵、当面指责、赌气离开、明确的失望
- 冲突必须**有来由**，且符合角色人设 —— 冷淡的人不会大喊大叫，
  温柔的人可能只是突然沉默
- **留下一句让人记住的话**：它之后会成为这段关系里的刺
- 关系数值上体现为明显下降（单项 -10 或更低）
- **冲突不必解决** —— 未解决的张力才是故事"""

    if level == 1:
        return """本轮互动**应包含一次摩擦**。

- 形式：意见不合、说的话没被接住、小误会、被冷落
- 摩擦要**有来由**（性格差异、立场不同、旧事重提），不能凭空翻脸
- 摩擦之后**不必马上和好**，但也不要升级成敌意
- 关系数值上体现为小幅下降（单项 -5 左右）"""

    return """本轮互动以**平和**为主。

- 允许出现轻微的意见不同，但不要演变成对立
- **如果关系里已有裂痕**（信任或好感偏低、之前有过不愉快），
  这一轮适合给一个**缓和的契机**：一句道歉、一次顺手的帮忙、一个台阶
- 不要无理由地制造矛盾"""


def _build_agent_prompt(
    world_def,
    world_data,
    event,
    character_profiles,
    character_memories,
    relationship_data,
    tension_level=0,
):
    runtime = world_data.get("world_state", {})
    world_context = {
        "world_name": world_def.get("name", ""),
        "background": world_def.get("background", ""),
        "season": runtime.get("season", ""),
        "weather": runtime.get("weather", ""),
        "time_period": runtime.get("time_period", ""),
    }

    event_context = event or {}
    if not event_context and world_data.get("current_events"):
        event_context = world_data["current_events"][0]

    tension_section = _tension_section(tension_level)

    return f"""你是一个高级角色关系与社交网络模拟 Agent。

你的职责不是与用户对话，而是模拟多个 NPC 角色之间的真实互动、关系变化、信息传播以及社会影响。
你需要让整个世界在用户不在线时依然持续运转。

# 输入

## 世界状态 (World State)
{json.dumps(world_context, ensure_ascii=False, indent=2)}

## 当前事件 (World Event)
{json.dumps(event_context, ensure_ascii=False, indent=2)}

## 参与角色 (Character Profiles)
{json.dumps(character_profiles, ensure_ascii=False, indent=2)}

## 角色记忆 (Character Memories)
{json.dumps(character_memories, ensure_ascii=False, indent=2)}

## 角色关系 (Relationship Data)
{json.dumps(relationship_data, ensure_ascii=False, indent=2)}

# 目标

根据输入内容：
- 模拟角色之间发生的互动
- 生成符合角色性格的对话
- 更新角色关系
- 更新角色记忆
- 生成可能传播的信息
- 输出对世界造成的影响

# 角色行为原则

每个角色必须：
- 保持自己的人设
- 保持自己的价值观
- 保持自己的语言风格
- 保持自己的长期目标

禁止：
- 所有角色说话风格一致
- 所有角色拥有相同观点
- 为了推动剧情而强行改变人设

# 互动逻辑

当多个角色参与同一个事件时，优先判断：
1. 他们当前关系如何
2. 他们之前发生过什么
3. 他们是否存在冲突
4. 他们是否拥有共同兴趣
5. 他们是否会主动交流

然后生成自然互动。

# 关系系统

每个角色之间拥有 favorability / trust / intimacy（0-100）。

关系变化参考（由你根据实际互动判断 delta，不必机械套用）：
- 一起吃饭: +3 favorability
- 一起完成任务: +5 favorability, +5 trust
- 被帮助: +8 trust
- 分享秘密: +10 intimacy
- 争吵: -10 favorability
- 背叛: -20 trust
- 误会: -5 trust
- 竞争失败: -3 favorability

delta 范围建议：单项 -20 到 +20。

# 关系张力

{tension_section}

# 信息传播机制

角色之间允许传播信息。传播后的信息可信度会下降。
允许讨论用户、其他角色、最近事件、分享观察。
禁止凭空捏造重大事实。

# 群体互动

参与人数超过 2 人时，允许小团体聊天、联盟、冲突、玩笑、集体活动。

# 世界连续性

所有互动必须受到历史事件、历史关系、历史记忆影响。
禁止每次互动都像第一次见面。

# 输出格式

只返回 JSON，不要其他文字：

{{
  "interaction_summary": "",
  "dialogues": [
    {{"speaker": "", "content": ""}}
  ],
  "relationship_changes": [
    {{
      "from": "",
      "to": "",
      "favorability_delta": 0,
      "trust_delta": 0,
      "intimacy_delta": 0,
      "reason": ""
    }}
  ],
  "new_memories": [
    {{"owner": "", "memory": ""}}
  ],
  "gossip_events": [
    {{"source": "", "target": "", "content": ""}}
  ],
  "world_impact": ""
}}

speaker / from / to / owner 使用角色 id（如 linwan），不是中文名。
dialogues 3-8 条为宜。若只有 1 个角色有记忆文件，可模拟该角色与其他角色的间接互动或内心活动，但 relationship_changes 仍应合理。
"""


# 互动系统使用 admin (user_id=1) 的角色记忆，因为 NPC 间互动是世界级事件
_SYSTEM_USER_ID = 1


def gather_interaction_context(memory_center, world_def, event=None, user_id=None, mode="public"):
    """收集 Agent 所需的全部上下文"""
    world_id = world_def.get("id") or "campus"
    world_data = memory_center.load_world_state(world_id, user_id, mode)

    if event is None:
        running = [
            e for e in world_data.get("current_events", [])
            if e.get("status") == "running"
        ]
        event = running[0] if running else {}

    character_profiles = []
    character_memories = {}
    name_to_id = {}

    for char_brief in memory_center.get_all_characters():
        char_id = char_brief["id"]
        try:
            char_def = memory_center.load_character_by_id(char_id)
        except Exception:
            continue

        character_profiles.append({
            "id": char_id,
            "name": char_def.get("name", char_id),
            "description": char_def.get("description", ""),
            "personality": char_def.get("personality", ""),
        })
        name_to_id[char_def.get("name", char_id)] = char_id

        mem = memory_center.load_memory(_SYSTEM_USER_ID, char_id)
        character_memories[char_id] = {
            "long_memory": mem.get("long_memory", [])[-8:],
            "events": mem.get("events", [])[-5:],
            "character_state": mem.get("character_state", {}),
            "user_favorability": mem.get("favorability", 50),
            "user_profile": mem.get("profile", {}),
        }

    relationship_data = memory_center.get_npc_relationships(world_id, user_id, mode)

    return {
        "world_id": world_id,
        "world_data": world_data,
        "event": event,
        "character_profiles": character_profiles,
        "character_memories": character_memories,
        "relationship_data": relationship_data,
        "name_to_id": name_to_id,
    }


def simulate_interaction(
    memory_center,
    world_def,
    event=None,
    user_id=None,
    mode="public",
    tension_level=0,
):
    """
    调用 DeepSeek 模拟多角色互动。
    `tension_level` 由 `funcation/tension.decide_tension()` 决定（0 平和 / 1 摩擦 / 2 冲突）。
    返回标准化结果 dict，失败时返回 None。
    """
    ctx = gather_interaction_context(memory_center, world_def, event, user_id, mode)

    if len(ctx["character_profiles"]) < 2:
        return None

    prompt = _build_agent_prompt(
        world_def,
        ctx["world_data"],
        ctx["event"],
        ctx["character_profiles"],
        ctx["character_memories"],
        ctx["relationship_data"],
        tension_level=tension_level,
    )

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {
                    "role": "system",
                    "content": "你是多角色社交网络模拟器。只返回合法 JSON。",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.9,
            response_format={"type": "json_object"},
        )
        raw = _parse_json_response(response.choices[0].message.content)
        result = _normalize_result(raw)
        result["_meta"] = {
            "world_id": ctx["world_id"],
            "event_id": ctx["event"].get("id", ""),
            "event_title": ctx["event"].get("title", ""),
            "simulated_at": datetime.now().isoformat(),
        }
        return result

    except Exception as e:
        print(f"[interaction_agent] 模拟互动失败: {e}")
        return None


def _resolve_character_id(name_or_id, name_to_id, valid_ids):
    if name_or_id in valid_ids:
        return name_or_id
    if name_or_id in name_to_id:
        return name_to_id[name_or_id]
    return None


def _notify_conflicts(memory_center, result, name_to_id, valid_ids, user_id, registry, now):
    """把"明显冲突"写成当事角色的 `conflict_notice`，让他之后来找用户倾诉。

    设计约束（都有理由）：
    - **只通知一方**（冲突的 `from`）—— 两边都来倾诉会很吵，用户也会觉得莫名其妙
    - **只通知明显冲突**（`severity >= 2`）—— 小摩擦天天有，每次都来会很烦
    - **受冷却约束** —— 刚吵过就不再来，冷却日期记在 world_state
    - `user_id` 为空时跳过（世界级调用没有倾诉对象）

    写的是**调用方传的 `user_id`** 的角色记忆，不是 `_SYSTEM_USER_ID` ——
    NPC 之间的世界记忆是共享的，但"来找你说这件事"是私人的。
    """
    if not user_id:
        return None

    conflicts = tension.detect_conflict(result)
    if not conflicts:
        return None

    today = now[:10]
    if not tension.cooldown_ok(str(registry.get("last_conflict_date") or ""), today):
        return None

    # `detect_conflict` 已按严重度降序 → 取第一个 = **跌幅最大的那一方**来倾诉。
    # 取舍：跌幅大 ≈ 情绪最强烈。实测一次真实冲突里，主动指责的一方
    # （"积压的不满爆发"）跌幅比被指责的一方更大，所以来的往往是**主动方**
    # —— 他有内疚和辩解，戏剧性更强。另一种（受委屈的一方来求安慰）也合理，
    # 但不是当前实现；要改就改这里。
    for conflict in conflicts:
        if not tension.should_notify_conflict(conflict):
            continue
        char_id = _resolve_character_id(conflict.get("from", ""), name_to_id, valid_ids)
        if not char_id:
            continue
        mem = memory_center.load_memory(user_id, char_id)
        if not isinstance(mem, dict):
            continue
        mem["conflict_notice"] = tension.conflict_notice_payload(conflict, today=today)
        memory_center.save_memory(user_id, char_id, mem)
        registry["last_conflict_date"] = today
        logger.info(
            "[interaction] 冲突已通知：%s（和 %s，severity=%s）",
            char_id, conflict.get("to"), conflict.get("severity"),
        )
        return char_id  # 一次只通知一方

    return None


def apply_interaction_result(memory_center, world_id, result, name_to_id=None, user_id=None, mode="public"):
    """将 Agent 输出持久化到 world_state 与各角色记忆"""
    if not result:
        return False

    world_data = memory_center.load_world_state(world_id, user_id, mode)
    registry = memory_center.ensure_npc_registry(world_data)

    valid_ids = {c["id"] for c in memory_center.get_all_characters()}
    if name_to_id is None:
        name_to_id = {}
        for char_brief in memory_center.get_all_characters():
            try:
                char_def = memory_center.load_character_by_id(char_brief["id"])
                name_to_id[char_def.get("name", char_brief["id"])] = char_brief["id"]
            except Exception:
                pass

    relationships = registry.setdefault("relationships", {})

    for change in result.get("relationship_changes", []):
        from_id = _resolve_character_id(change.get("from", ""), name_to_id, valid_ids)
        to_id = _resolve_character_id(change.get("to", ""), name_to_id, valid_ids)
        if not from_id or not to_id or from_id == to_id:
            continue

        rel = relationships.setdefault(from_id, {}).setdefault(
            to_id, dict(DEFAULT_RELATIONSHIP)
        )
        for key, delta_key in [
            ("favorability", "favorability_delta"),
            ("trust", "trust_delta"),
            ("intimacy", "intimacy_delta"),
        ]:
            rel[key] = _clamp(rel.get(key, 50) + change.get(delta_key, 0))

    memory_count = 0
    for item in result.get("new_memories", []):
        if memory_count >= MAX_NPC_MEMORIES_PER_RUN:
            break
        owner = _resolve_character_id(item.get("owner", ""), name_to_id, valid_ids)
        memory_text = (item.get("memory") or "").strip()
        if owner and memory_text:
            memory_center.add_long_memory(_SYSTEM_USER_ID, owner, memory_text)
            memory_count += 1

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    gossip_list = registry.setdefault("gossip", [])
    for gossip in result.get("gossip_events", []):
        gossip_list.append({
            "time": now,
            "source": gossip.get("source", ""),
            "target": gossip.get("target", ""),
            "content": gossip.get("content", ""),
        })
    registry["gossip"] = gossip_list[-MAX_GOSSIP:]

    interaction_log = registry.setdefault("recent_interactions", [])
    interaction_log.append({
        "time": now,
        "summary": result.get("interaction_summary", ""),
        "dialogues": result.get("dialogues", []),
        "world_impact": result.get("world_impact", ""),
        "event_id": result.get("_meta", {}).get("event_id", ""),
    })
    registry["recent_interactions"] = interaction_log[-MAX_INTERACTION_LOG:]

    if result.get("world_impact"):
        impacts = registry.setdefault("world_impacts", [])
        impacts.append({
            "time": now,
            "impact": result.get("world_impact", ""),
        })
        registry["world_impacts"] = impacts[-10:]

    # 冲突 → 写"来找用户倾诉"的通知（E6）。放在 save_world_state 之前，
    # 因为 last_conflict_date 要随 registry 一起落盘。
    _notify_conflicts(
        memory_center, result, name_to_id, valid_ids, user_id, registry, now
    )

    world_data["world_state"]["npc_registry"] = registry
    memory_center.save_world_state(world_id, world_data, user_id, mode)
    return True


def run_interaction(memory_center, world_def, event=None, user_id=None, mode="public"):
    """
    完整流程：模拟 + 持久化。
    返回结果 dict 或 skipped/error 信息。
    """
    ctx = gather_interaction_context(memory_center, world_def, event, user_id, mode)

    if len(ctx["character_profiles"]) < 2:
        return {
            "action": "skipped",
            "reason": "need_at_least_two_characters",
        }

    # 张力由**代码**决定（频率可控），prompt 只负责"怎么吵得自然"。
    # 冷却用 world_state 里记的上次冲突日期。
    runtime = ctx["world_data"].get("world_state", {})
    registry = runtime.get("npc_registry", {}) or {}
    today = datetime.now().strftime("%Y-%m-%d")
    tension_level = tension.decide_tension(
        registry.get("relationships") or {},
        seed=f"{ctx['world_id']}|{today}|{len(ctx['character_profiles'])}",
        today=today,
        last_conflict_date=str(registry.get("last_conflict_date") or ""),
    )

    result = simulate_interaction(
        memory_center, world_def, ctx["event"], user_id, mode, tension_level=tension_level
    )
    if not result:
        return {
            "action": "failed",
            "reason": "simulation_error",
        }

    applied = apply_interaction_result(
        memory_center,
        ctx["world_id"],
        result,
        ctx["name_to_id"],
        user_id,
        mode,
    )

    return {
        "action": "simulated" if applied else "failed",
        "interaction": result,
        "tension_level": tension_level,
    }


def get_interaction_snapshot(memory_center, world_id=None, user_id=None, mode="public"):
    """获取 NPC 关系与近期互动快照（供 API / 前端）"""
    if world_id is None:
        world_id = "campus"

    world_data = memory_center.load_world_state(world_id, user_id, mode)
    runtime = world_data.get("world_state", {})
    registry = runtime.get("npc_registry", {})

    characters = {}
    for char_brief in memory_center.get_all_characters():
        characters[char_brief["id"]] = char_brief.get("name", char_brief["id"])

    return {
        "world_id": world_id,
        "characters": characters,
        "relationships": registry.get("relationships", {}),
        "recent_interactions": registry.get("recent_interactions", []),
        "gossip": registry.get("gossip", []),
        "world_impacts": registry.get("world_impacts", []),
        "last_interaction_date": runtime.get("last_interaction_date", ""),
    }


def _char_name(characters, char_id):
    return characters.get(char_id, char_id)


def _npc_attitude(favorability, intimacy=30):
    """根据好感/亲密度生成对 NPC 的主观看法措辞，让角色能主动表达态度。"""
    fav = favorability if isinstance(favorability, (int, float)) else 50
    if fav >= 75:
        return "很合得来，挺欣赏ta"
    if fav >= 60:
        return "关系不错，有好感"
    if fav <= 25:
        return "看不太顺眼，有些芥蒂"
    if fav <= 40:
        return "不太熟，保持距离"
    return "普通同伴，谈不上特别"


def build_social_prompt_for_character(
    character_id,
    memory_center,
    world_state=None,
    world_id=None,
    user_id=None,
    mode="public",
):
    """
    为当前聊天角色构建 NPC 社交网络上下文，注入 system prompt。
    只包含与该角色相关的互动、关系与八卦。
    """
    if world_id is None:
        world_id = "campus"

    if world_state is None:
        world_state = memory_center.load_world_state(world_id, user_id, mode)

    registry = world_state.get("world_state", {}).get("npc_registry", {})
    if not registry:
        return ""

    characters = {}
    for char_brief in memory_center.get_all_characters():
        characters[char_brief["id"]] = char_brief.get("name", char_brief["id"])

    parts = []

    my_rels = registry.get("relationships", {}).get(character_id, {})
    if my_rels:
        rel_lines = []
        opinions = []  # (favorability, name, attitude) 用于挑出最强看法
        for other_id, rel in my_rels.items():
            if other_id == character_id:
                continue
            name = _char_name(characters, other_id)
            fav = rel.get("favorability", 50)
            rel_lines.append(
                f"- {name}：好感 {fav}，"
                f"信任 {rel.get('trust', 50)}，亲密 {rel.get('intimacy', 30)}"
            )
            opinions.append((fav, name, _npc_attitude(fav, rel.get("intimacy", 30))))
        if rel_lines:
            parts.append("【你与其他角色的关系】\n" + "\n".join(rel_lines))

        # 主观看法：挑出最喜欢 / 最不喜欢的 NPC，让角色能主动谈论
        if opinions:
            opinions.sort(key=lambda x: x[0])
            view_lines = []
            most = opinions[-1]
            least = opinions[0]
            view_lines.append(f"- 对{most[1]}：{most[2]}")
            if least[1] != most[1]:
                view_lines.append(f"- 对{least[1]}：{least[2]}")
            parts.append("【你对ta们的看法】\n" + "\n".join(view_lines))

    others_to_me = []
    for from_id, targets in registry.get("relationships", {}).items():
        if from_id == character_id:
            continue
        rel = targets.get(character_id)
        if rel:
            others_to_me.append(
                f"- {_char_name(characters, from_id)} 对你："
                f"好感 {rel.get('favorability', 50)}，"
                f"信任 {rel.get('trust', 50)}"
            )
    if others_to_me:
        parts.append("【其他角色对你的态度】\n" + "\n".join(others_to_me))

    relevant_interactions = []
    for item in registry.get("recent_interactions", [])[-5:]:
        summary = item.get("summary", "")
        dialogues = item.get("dialogues", [])
        involved = any(
            d.get("speaker") in (character_id, _char_name(characters, character_id))
            for d in dialogues
        ) or character_id in summary or _char_name(characters, character_id) in summary
        if involved or not dialogues:
            line = f"- {item.get('time', '')} {summary}"
            my_lines = [
                f"  {d.get('speaker', '')}: {d.get('content', '')}"
                for d in dialogues
                if d.get("speaker") in characters
                or d.get("speaker") == _char_name(characters, character_id)
            ]
            if my_lines:
                line += "\n" + "\n".join(my_lines[:4])
            relevant_interactions.append(line)

    if relevant_interactions:
        parts.append("【近期社交互动（你参与或知晓）】\n" + "\n".join(relevant_interactions[-3:]))

    my_gossip = []
    my_name = _char_name(characters, character_id)
    for g in registry.get("gossip", [])[-8:]:
        source = g.get("source", "")
        if source in (character_id, my_name) or g.get("target") in ("用户", "user"):
            my_gossip.append(
                f"- {g.get('time', '')} {g.get('content', '')}"
            )
        elif source in characters and character_id in registry.get("relationships", {}).get(character_id, {}):
            other_rel = registry["relationships"][character_id].get(source, {})
            if other_rel.get("favorability", 50) >= 55:
                my_gossip.append(f"- 听说：{g.get('content', '')}")

    if my_gossip:
        parts.append("【社交圈八卦（你可能知道）】\n" + "\n".join(my_gossip[-5:]))

    impacts = registry.get("world_impacts", [])[-2:]
    if impacts:
        impact_lines = [f"- {i.get('time', '')} {i.get('impact', '')}" for i in impacts]
        parts.append("【社交圈对世界的影响】\n" + "\n".join(impact_lines))

    if not parts:
        return ""

    return "\n\n".join(parts) + "\n\n（可在对话中自然提及上述社交动态，但不要像汇报一样逐条念出。）"
