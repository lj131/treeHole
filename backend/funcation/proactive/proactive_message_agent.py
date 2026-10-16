import os

from dotenv import load_dotenv

from openai import OpenAI

load_dotenv()

client = OpenAI(
    api_key=os.getenv(
        "DEEPSEEK_API_KEY"
    ),
    base_url=os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com")
)


def generate_message(

        trigger,

        character,

        world,

        memory_data

):
    state = memory_data.get(
        "character_state",
        {}
    )

    profile = memory_data.get(
        "profile",
        {}
    )

    story = memory_data.get(
        "story",
        {}
    )

    relationship = memory_data.get(
        "relationship",
        {}
    )

    world_event_context = ""
    if trigger.get("trigger") == "world_event":
        we = trigger.get("world_event", {})
        world_event_context = f"""
世界事件：{we.get("title", "")}
描述：{we.get("description", "")}
状态：{we.get("type", "")}（进度 {we.get("progress", 0)}%）
"""

    # 梦境走单独的 prompt：素材是**写好的一场梦**，
    # 这里要它"用自己的话说出来"，而不是重写梦境。
    dream_context = ""
    dream_extra_rules = ""
    if trigger.get("trigger") == "dream":
        dream = trigger.get("dream", {})
        dream_context = f"""
你昨晚做的梦：
{dream.get("text", "")}
"""
        dream_extra_rules = """
6 这是转述自己的梦：用"我昨晚梦到……"开头
7 梦里的画面要说具体，不要总结
"""

    conflict_context = ""
    conflict_extra_rules = ""
    if trigger.get("trigger") == "conflict":
        c = trigger.get("conflict", {}) or {}
        with_name = c.get("with", "")
        severity = int(c.get("severity") or 1)
        conflict_context = f"""
你刚和「{with_name}」闹得不愉快：

{c.get("summary", "")}

严重程度：{"闹得挺僵" if severity >= 2 else "有点不痛快"}
"""
        # 要的是**吐槽/倾诉**，不是"事件报告"。不说清的话 LLM 会写成新闻播报。
        conflict_extra_rules = """
6 你在**倾诉**，不是汇报事件 —— 说你的感受，不是事情的经过
7 不要复述完整对话，最多带一句对方说的话
8 不要要求用户评理、不要问"你说我错了吗"
9 允许语气冲一点、带情绪，这比客客气气更像真人
"""

    prompt = f"""
你正在主动联系用户。

角色：

{character.get("name")}

角色设定：

{character.get("description")}

当前世界：

{world.get("name","")}

当前剧情：

{story}

当前状态：

{state}

关系：

{relationship}

用户画像：

{profile}

触发原因：

{trigger["reason"]}
{world_event_context}
{dream_context}
{conflict_context}

要求：

1 像真人

2 不超过3句话

3 不打招呼

4 不要说在吗

5 不像客服
{dream_extra_rules}
{conflict_extra_rules}
直接输出内容
"""

    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=1
    )

    return response.choices[
        0
    ].message.content