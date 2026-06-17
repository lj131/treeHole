# 角色聊天历史模块（按用户隔离）
# 文件路径：data/chat_history/{user_id}/{character_id}.json

import json
import os

MEMORY_DIR = os.path.join("data", "chat_history")


def get_memory_path(user_id, character_id):
    """聊天历史按用户+角色隔离"""
    return os.path.join(MEMORY_DIR, str(user_id), f"{character_id}.json")


def load_memory(user_id, character_id):
    """加载某用户与某角色的聊天历史。文件不存在返回 []。"""
    path = get_memory_path(user_id, character_id)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []


def save_memory(user_id, character_id, messages):
    """保存聊天历史，自动创建目录"""
    path = get_memory_path(user_id, character_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(messages, f, ensure_ascii=False, indent=2)


def clear_memory(user_id, character_id):
    """清空某用户与某角色的聊天历史"""
    save_memory(user_id, character_id, [])


def delete_memory(user_id, character_id):
    """彻底删除聊天历史文件（角色删除时用）"""
    path = get_memory_path(user_id, character_id)
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
