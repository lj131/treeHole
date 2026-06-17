"""
角色生成 Agent

使用 DeepSeek 根据用户给出的关键词，自动生成一个完整、鲜活的 AI 角色人设。
生成内容包括：名字、简介、性格关键词、详尽的角色扮演指令（system_prompt）。
"""

import json
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("DEEPSEEK_API_KEY")

if not api_key:
    raise ValueError("DEEPSEEK_API_KEY 未配置")

client = OpenAI(
    api_key=api_key,
    base_url=os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com")
)


# 字段缺失时的兜底默认值
_DEFAULTS = {
    "name": "新角色",
    "description": "一个充满神秘色彩的角色",
    "personality": "独特",
    "system_prompt": "你是一个有个性的角色，会以独特的方式与用户交流。",
}


def generate_character(keyword: str) -> dict:
    """
    根据关键词生成完整角色人设。

    参数:
        keyword: 用户简短描述，如 "傲娇学姐，理工科，喜欢猫"

    返回:
        dict: {name, description, personality, system_prompt}
        失败（API 异常或解析失败）时返回空 dict {}
    """

    prompt = f"""
你是 AI 角色人设设计师。请根据下面的关键词，创造一个完整、鲜活、有记忆点的角色。

用户关键词：
{keyword}

请生成以下四个字段（返回纯 JSON，不要多余文字、不要 markdown 代码块）：

1. name: 角色名字（2-4 个中文字，符合角色气质，避免生僻字）
2. description: 一句话简介，10-20 字，概括角色最大特点（例："高冷学姐，嘴硬心软"）
3. personality: 2-4 个性格关键词，用顿号分隔（例："傲娇、理性、护短"）
4. system_prompt: 详尽的角色扮演指令（150-300 字）。必须包含：
   - 角色身份背景（年龄、身份、与用户的关系设定）
   - 说话风格（句长、语气、用词习惯）
   - 2-3 个标志性口癖或口头禅
   - 性格在对话中的具体表现（如何表达关心、如何拒绝、如何撒娇）
   - 内心独白与外在表达的差异（如有）
   - 至少一个独特的记忆点/小习惯

返回 JSON 格式：
{{
  "name": "...",
  "description": "...",
  "personality": "...",
  "system_prompt": "..."
}}
"""

    # DeepSeek 偶尔返回的 JSON 字符串内含未转义引号，json.loads 会失败。
    # 这里重试最多 2 次，第二次降温度并加严格约束。
    for attempt in range(2):
        try:
            response = client.chat.completions.create(
                model="deepseek-chat",
                response_format={"type": "json_object"},
                messages=[
                    {
                        "role": "system",
                        "content": "你是 AI 角色人设设计师。根据关键词生成完整角色，返回纯 JSON。system_prompt 字段内的所有双引号必须用中文引号「」或转义，不得出现未转义的半角双引号。",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.9 if attempt == 0 else 0.5,
                max_tokens=800,
            )

            raw = response.choices[0].message.content
            result = json.loads(raw)
            break

        except json.JSONDecodeError as e:
            print(f"[character_agent] JSON 解析失败 (attempt {attempt + 1}): {e}")
            if attempt == 1:
                return {}
            # 重试
            continue

        except Exception as e:
            print(f"[character_agent] generate_character 失败: {e}")
            return {}

    # 字段校验：缺失字段用默认值兜底
    for field, default in _DEFAULTS.items():
        value = result.get(field)
        if not value or not isinstance(value, str):
            result[field] = default

    return {
        "name": result["name"],
        "description": result["description"],
        "personality": result["personality"],
        "system_prompt": result["system_prompt"],
    }
