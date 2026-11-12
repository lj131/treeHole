import json
from openai import OpenAI
import os
from openai.types.chat import ChatCompletionUserMessageParam
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("DEEPSEEK_API_KEY")

if not api_key:
    raise ValueError(
        "DEEPSEEK_API_KEY 未配置"
    )

client = OpenAI(
    api_key=api_key,
    base_url=os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com")
)


def extract_memory(
        user_input,
        memories
):
    prompt = f"""
    你是长期记忆管理器。

    已有记忆：

    {memories}

    请分析用户最新发言。

    返回JSON。

    规则：

    0 **时间写法（最重要）**：
      记忆会被之后很多天的对话反复读到。里面禁止出现「明天」「后天」「下周」
      「一会儿」「待会」这类相对时间 —— 过几天再读，它会被当成"今天的明天"，
      角色就会把陈年旧约说成新约定（实测踩过）。
      需要写时间就写**绝对日期**（如「11月1日下午三点」）；不知道日期就干脆不写时间。
      还没发生的约定写成「曾约过…」，不要写成「约好了…要去…」。

    1 如果需要新增记忆：

    {{
        "action":"add",
        "memory":"..."
    }}

    2 如果需要更新旧记忆：

    {{
        "action":"update",
        "old_memory":"...",
        "new_memory":"..."
    }}

    3 如果无需保存：

    {{
        "action":"ignore"
    }}

    用户发言：

    {user_input}
    """

    messages: list[ChatCompletionUserMessageParam] = [
        {
            "role": "system",
            "content": "你是记忆管理器"
        },
        {
            "role": "user",
            "content": prompt
        }
    ]

    response = client.chat.completions.create(
        model="deepseek-chat",
        response_format={
            "type": "json_object"
        },
        messages=messages,
        temperature=0.9
    )

    content = response.choices[0].message.content

    try:

        result = json.loads(
            response.choices[0].message.content
        )
        return result

    except:

        return {
            "action": "ignore",
            "memory": ""
        }