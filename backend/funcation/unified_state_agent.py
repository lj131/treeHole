"""
统一状态分析 Agent

将 profile_agent、relationship_agent、state_agent 合并为一次 LLM 调用。
一次调用完成：用户画像提取、好感度分析、角色状态评估。

节省 2 次 LLM 调用（从 3 次 → 1 次），降低延迟和 token 消耗。
"""

import json
import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

api_key = os.getenv("DEEPSEEK_API_KEY")
if not api_key:
    raise ValueError("DEEPSEEK_API_KEY 未配置")

client = OpenAI(
    api_key=api_key,
    base_url=os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com"),
)


def analyze_unified_state(
    user_input: str,
    current_profile: dict,
    favorability: int,
    current_state: dict,
    world: dict | None = None,
) -> dict:
    """
    统一分析：画像 + 关系 + 状态，一次 LLM 调用完成。

    参数:
        user_input: 用户最新发言
        current_profile: 当前画像 dict {"name":..., "city":..., "job":..., "mood":...}
        favorability: 当前好感度 int (0-100)
        current_state: 当前角色状态 dict {"mood":..., "energy":..., "current_event":...}
        world: 世界定义 dict (可选，取 name 用于上下文)

    返回:
        dict: {
            "profile": {"name":..., "city":..., "job":..., "mood":...},
            "relationship": {"delta": -10..10, "reason": "..."},
            "character_state": {"mood": "开心/平静/低落/生气/疲惫", "energy": 0-100,
                                "current_event": ""}
        }

    异常时返回安全默认值（空 profile、delta=0、current_state 原样）。
    """
    world_name = world.get("name", "无") if world else "无"

    prompt = f"""你是角色状态统一分析器。请一次性完成三个独立的分析任务，返回纯JSON。

【当前数据】
用户画像：{json.dumps(current_profile, ensure_ascii=False)}
好感度：{favorability}/100
角色状态：{json.dumps(current_state, ensure_ascii=False)}
世界背景：{world_name}

【用户最新消息】
{user_input}

【必须返回的JSON结构】
{{
  "profile": {{
    "name": "",
    "city": "",
    "job": "",
    "mood": ""
  }},
  "relationship": {{
    "delta": 0,
    "reason": ""
  }},
  "character_state": {{
    "mood": "平静",
    "energy": 80,
    "current_event": ""
  }}
}}

【任务一：画像提取】
从用户消息中提取 name/city/job/mood。
- 只提取明确提到的信息，不猜测
- 无新信息时对应字段留空字符串 ""
- 如果用户说了和现有画像矛盾的信息，用新的替换
- mood 可选：开心、难过、疲惫、焦虑、平静、兴奋、无聊

【任务二：好感度分析】
判断用户这句话会让角色好感度变化多少。
- delta 范围 -10 到 10
- 感谢/关心/赞美/表达好感 → 增加(1~8)
- 攻击/辱骂/不尊重 → 减少(-10~-1)
- 普通闲聊/问好/陈述 → 0
- reason 简短说明原因（delta为0时可写"无变化"，不超过15字）

【任务三：角色状态分析】
判断角色当前应该处于什么状态。
- mood 只能是：开心 / 平静 / 低落 / 生气 / 疲惫
- energy 范围 0~100，根据对话情境合理调整（积极互动→提升，消极互动→降低，普通闲聊→轻微浮动）
- current_event：如果用户提到当前具体活动（如"今天去逛街了""刚考完试"），则填入简短描述；否则留空

只返回JSON，不要任何额外文字。"""

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {
                    "role": "system",
                    "content": "你是角色状态统一分析器。只返回JSON，不要任何额外文字。",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content.strip()
        result = json.loads(content)

        # 确保返回结构完整
        result.setdefault("profile", {})
        result.setdefault("relationship", {"delta": 0, "reason": ""})
        result.setdefault("character_state", current_state)

        return result

    except Exception as e:
        print(f"[unified_state_agent] analyze_unified_state 失败: {e}")
        return {
            "profile": {},
            "relationship": {"delta": 0, "reason": "分析失败"},
            "character_state": current_state,
        }
