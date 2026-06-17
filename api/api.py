import asyncio
import json
import logging
import os
import shutil
import uuid

from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from pydantic import BaseModel

from funcation import memory, prompt
from funcation import memory_agent
from funcation import memory_rag
from funcation import recall_agent
from funcation import relationship_agent
from funcation import state_agent
from funcation import story_agent
from funcation import world_event_agent
from funcation import character_agent
from funcation import interaction_agent
from funcation.embedding_manager import preload
from funcation.memory_center import MemoryCenter
from funcation.proactive import proactive_engine
from funcation.conversation_manager import conversation_manager
from funcation.utils import retry_sync

load_dotenv()

from . import websocket


@asynccontextmanager
async def lifespan(application: FastAPI):
    # Startup
    tts_task = asyncio.create_task(conversation_manager.process_tts_queue())
    print("[Startup] TTS 语音合成队列已启动")
    yield
    # Shutdown
    tts_task.cancel()
    try:
        await tts_task
    except asyncio.CancelledError:
        pass


app = FastAPI(lifespan=lifespan)

# 静态文件服务：角色头像
AVATARS_DIR = os.path.join("data", "avatars")
os.makedirs(AVATARS_DIR, exist_ok=True)
app.mount("/avatars", StaticFiles(directory=AVATARS_DIR), name="avatars")

# 启动时预热 Embedding 模型，避免首次请求等待
try:
    preload()
except Exception as e:
    print(f"[Startup] Embedding 预热失败（将在首次请求时重试）: {e}")

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# 新增：WebSocket路由
# ============================================================

# 包含WebSocket路由
app.include_router(websocket.router)

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url=os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com")
)

# 数据中心单例
mc = MemoryCenter()

logger = logging.getLogger(__name__)


def _safe(label, fn, default=None):
    """非关键路径降级包装：失败时记 warning 并返回 default，不阻断主流程。"""
    try:
        return fn()
    except Exception as e:
        logger.warning("[chat] %s 降级跳过: %s", label, e)
        return default


class ChatRequest(BaseModel):
    message: str


class SwitchCharacterRequest(BaseModel):
    character_id: str


class CharacterCreateRequest(BaseModel):
    keyword: str
    name: str | None = None


# 健康检查（Docker / 负载均衡用）
@app.get("/health")
def health():
    return {"status": "ok"}


# 聊天接口
@app.post("/chat")
def chat(req: ChatRequest):
    """分层降级：关键路径(文件IO/Prompt/DeepSeek/记忆)失败返回 error；
    非关键 agent(事件/剧情/RAG/画像/好感度/状态/向量同步)失败静默跳过。"""
    try:
        user_input = req.message

        # --- 关键路径：加载数据（带兜底）---
        try:
            character = mc.load_current_character()
            char_id = character["id"]
        except Exception as e:
            logger.error("[chat] 加载角色失败: %s", e)
            return {"error": "角色数据异常，请刷新后重试"}

        messages = _safe("加载聊天历史", lambda: memory.load_memory(char_id), default=[]) or []
        mem = _safe("加载记忆", lambda: mc.load_memory(char_id), default={}) or {}
        world = _safe("加载世界观", lambda: mc.load_current_world(), default=None)
        world_id = world.get("id") if world else None

        # --- 非关键 agent：世界事件 / 剧情（失败跳过）---
        _safe("世界事件tick", lambda: world_event_agent.tick(mc, character, world))

        def _story_block():
            story_agent.check_story(mc, character, world)
            memory_data = mc.load_memory(char_id)
            memory_data = story_agent.sync_story_to_state(memory_data)
            mc.save_memory(char_id, memory_data)
            _sync_story_to_rag(char_id, mc, world_id)

        _safe("剧情推进", _story_block)

        # 角色状态（剧情降级后重新读，读不到就用空）
        memory_data = _safe("加载记忆(状态)", lambda: mc.load_memory(char_id), default={}) or {}
        current_state = memory_data.get("character_state", {})

        # --- 构建 Prompt（关键）---
        try:
            world_state_data = _safe(
                "世界状态", lambda: mc.load_world_state(world.get("id")) if world else None, default=None
            )
            npc_social = _safe(
                "NPC社交上下文",
                lambda: interaction_agent.build_social_prompt_for_character(char_id, mc, world_state_data),
                default=None,
            )

            # RAG 检索（非关键，失败用空）
            recalled_collections = _safe(
                "记忆范围识别",
                lambda: recall_agent.detect_memory_scope(user_input, char_id),
                default=[],
            ) or []
            retrieved = _safe(
                "RAG检索",
                lambda: memory_rag.retrieve_memories(
                    char_id, user_input, top_k=10, world_id=world_id,
                    collections=recalled_collections,
                ),
                default=[],
            ) or []

            system_prompt = prompt.build_system_prompt(
                character_id=char_id,
                memory_data=mem,
                world=world,
                messages=messages,
                world_state=world_state_data,
                npc_social_context=npc_social,
                retrieved_memories=retrieved,
            )
        except Exception as e:
            logger.error("[chat] 构建 Prompt 失败: %s", e)
            return {"error": "对话上下文构建失败，请重试"}

        if messages and messages[0]["role"] == "system":
            messages[0]["content"] = system_prompt
        else:
            messages.insert(0, {
                "role": "system",
                "content": system_prompt
            })

        # --- 非关键 agent：画像 / 好感度 / 状态 / 向量同步（失败跳过）---
        _safe("更新画像", lambda: mc.update_profile(user_input, char_id))
        _safe("画像同步RAG", lambda: _sync_profile_to_rag(char_id, mc, world_id))
        _safe("更新好感度", lambda: relationship_agent.update_relationship(mc, char_id, user_input))
        _safe("关系同步RAG", lambda: _sync_relationship_to_rag(char_id, mc, world_id))
        _safe(
            "更新角色状态",
            lambda: mc.update_character_state(
                char_id, state_agent.analyze_state(user_input, current_state, world)
            ),
        )

        messages.append({
            "role": "user",
            "content": user_input
        })

        # --- 关键路径：DeepSeek 主回复 ---
        try:
            response = retry_sync(
                lambda: client.chat.completions.create(
                    model="deepseek-chat",
                    messages=messages,
                    temperature=0.9,
                ),
                max_retries=3,
            )
            ai_reply = response.choices[0].message.content
        except Exception as e:
            logger.error("[chat] DeepSeek 主回复失败: %s", e)
            return {"error": "AI 服务繁忙，请稍后重试"}

        messages.append({
            "role": "assistant",
            "content": ai_reply
        })

        # --- 关键路径：保存 + 记忆提取 ---
        _safe("更新最后聊天时间", lambda: mc.update_last_chat_time(char_id))
        try:
            memory.save_memory(char_id, messages)
        except Exception as e:
            logger.error("[chat] 保存聊天历史失败: %s", e)

        # 记忆提取（关键：保证不忘事，但失败不阻断回复）
        def _memory_extract():
            current_memories = mc.get_long_memories_text(char_id)
            memory_result = memory_agent.extract_memory(user_input, current_memories)
            action = memory_result.get("action", "ignore")
            if action == "add":
                mc.add_long_memory(char_id, memory_result["memory"])
            elif action == "update":
                mc.update_long_memory(
                    char_id,
                    memory_result.get("old_memory", ""),
                    memory_result.get("new_memory", "")
                )

        _safe("长期记忆提取", _memory_extract)

        return {
            "reply": ai_reply,
            "favorability": mc.get_favorability(char_id)
        }

    except Exception as e:
        # 最后兜底：任何未预期的异常都不返回裸 500
        logger.exception("[chat] 未预期异常: %s", e)
        return {"error": "服务器内部错误，请重试"}


# ============================================================
# RAG 同步辅助函数
# ============================================================


def _sync_profile_to_rag(char_id: str, mc: MemoryCenter, world_id: str | None):
    """将当前画像字段同步到 profile 集合（upsert）"""
    profile = mc.get_profile(char_id)
    field_labels = {"name": "姓名", "city": "城市", "job": "职业", "mood": "情绪"}
    for field, label in field_labels.items():
        value = profile.get(field, "")
        text = f"用户{label}：{value}" if value else f"用户{label}：未知"
        memory_rag.upsert_memory(
            char_id, "profile", text,
            doc_id=f"{char_id}_profile_{field}",
            metadata={"field": field, "world_id": world_id or ""},
        )


def _sync_story_to_rag(char_id: str, mc: MemoryCenter, world_id: str | None):
    """将当前剧情同步到 story 集合（upsert 概览 + 各阶段）"""
    mem = mc.load_memory(char_id)
    story = mem.get("story", {})
    if not story or not story.get("story_id"):
        return

    # 剧情概览
    overview = f"剧情：{story.get('title', '')}。{story.get('description', '')}"
    memory_rag.upsert_memory(
        char_id, "story", overview,
        doc_id=f"{char_id}_story_overview",
        metadata={"story_id": story.get("story_id", ""), "world_id": world_id or ""},
    )

    # 各阶段（当前阶段标注）
    stages = story.get("stages", [])
    current_stage = story.get("stage", 0)
    for i, stage_text in enumerate(stages):
        prefix = "【当前阶段】" if i == current_stage else ""
        memory_rag.upsert_memory(
            char_id, "story", f"{prefix}{stage_text}",
            doc_id=f"{char_id}_story_stage_{i}",
            metadata={
                "story_id": story.get("story_id", ""),
                "stage_index": i,
                "is_current": i == current_stage,
                "world_id": world_id or "",
            },
        )


def _sync_relationship_to_rag(char_id: str, mc: MemoryCenter, world_id: str | None):
    """将当前关系同步到 relationship 集合（upsert）"""
    mem = mc.load_memory(char_id)
    rel = mem.get("relationship", {})
    level = rel.get("level", "普通")
    reason = rel.get("last_reason", "")
    fav = mem.get("favorability", 50)
    if reason:
        text = f"关系等级：{level}（好感度：{fav}），最近变化原因：{reason}"
    else:
        text = f"关系等级：{level}（好感度：{fav}）"
    memory_rag.upsert_memory(
        char_id, "relationship", text,
        doc_id=f"{char_id}_relationship",
        metadata={"level": level, "favorability": fav, "world_id": world_id or ""},
    )


# 获取好感度
@app.get("/favorability")
def favorability():
    char_id = mc.get_current_character_id()
    return {
        "favorability": mc.get_favorability(char_id)
    }


# 获取用户画像
@app.get("/profile")
def profile():
    char_id = mc.get_current_character_id()
    return {
        "profile": mc.get_profile(char_id)
    }


# 保存用户画像
@app.post("/profile")
def save_profile(req: ChatRequest):
    char_id = mc.get_current_character_id()
    try:
        profile = json.loads(req.message)
        mem = mc.load_memory(char_id)
        mem["profile"] = profile
        mc.save_memory(char_id, mem)
    except:
        pass
    return {
        "message": "保存成功"
    }


# 获取历史记录
@app.get("/history")
def history():
    character = mc.load_current_character()
    messages = memory.load_memory(character["id"])
    return {
        "messages": messages[-10:]
    }


# 获取记忆
@app.get("/memory")
def get_memory():
    character = mc.load_current_character()
    messages = memory.load_memory(character["id"])
    user_messages = [
        msg["content"]
        for msg in messages
        if msg["role"] == "user"
    ]
    return {
        "memory": user_messages
    }


# 清空记忆
@app.post("/clear-memory")
def clear_memory():
    character = mc.load_current_character()
    memory.clear_memory(character["id"])
    return {
        "message": "清空成功"
    }


# 获取角色列表
@app.get("/characters")
def get_characters():
    return {
        "characters": mc.get_all_characters()
    }


# 切换角色
@app.post("/character/switch")
def switch_character(req: SwitchCharacterRequest):
    mc.set_current_character(req.character_id)
    return {
        "message": "切换成功"
    }


# 获取世界列表
@app.get("/worlds")
def get_worlds():
    return {
        "worlds": mc.get_all_worlds()
    }


# 切换世界
@app.post("/world/switch")
def switch_world(req: SwitchCharacterRequest):
    mc.set_current_world(req.character_id)
    return {
        "message": "切换成功"
    }


# 获取长期记忆
@app.get("/long-memory")
def get_long_memory():
    char_id = mc.get_current_character_id()
    return {
        "long_memory": mc.get_long_memories(char_id)
    }


# 获取事件
@app.get("/events")
def get_events():
    char_id = mc.get_current_character_id()
    return {
        "events": mc.get_events(char_id)
    }


# ============================================================
# 新增：角色信息
# ============================================================


# 获取当前角色详情
@app.get("/character/current")
def get_current_character():
    """获取当前角色的完整静态定义"""
    character = mc.load_current_character()
    return {
        "character": character
    }


# 上传角色头像
@app.post("/character/avatar")
async def upload_character_avatar(file: UploadFile = File(...)):
    """上传当前角色的头像图片"""
    char_id = mc.get_current_character_id()

    # 校验文件类型
    allowed_types = {"image/png", "image/jpeg", "image/gif", "image/webp"}
    if file.content_type not in allowed_types:
        return {"error": f"不支持的文件类型: {file.content_type}，仅支持 PNG/JPG/GIF/WebP"}

    # 生成唯一文件名
    ext = file.filename.split(".")[-1] if "." in (file.filename or "") else "png"
    filename = f"{char_id}_{uuid.uuid4().hex[:8]}.{ext}"
    filepath = os.path.join(AVATARS_DIR, filename)

    # 保存文件
    with open(filepath, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # 更新角色定义中的 avatar 字段
    character = mc.load_current_character()
    character["avatar"] = f"/avatars/{filename}"
    mc.save_character(character)

    return {"message": "头像上传成功", "avatar": character["avatar"]}


# 创建角色（关键词 + AI 生成完整人设）
@app.post("/character/create")
def create_character(req: CharacterCreateRequest):
    """根据关键词由 DeepSeek 生成一个新角色并保存"""
    data = character_agent.generate_character(req.keyword)
    if not data:
        return {"error": "角色生成失败，请重试"}

    # 用户自定义名字覆盖 AI 生成值
    if req.name:
        data["name"] = req.name

    # 生成唯一 ID（char_ + 8 位 hex），与头像命名风格一致；碰撞时循环兜底
    existing_ids = {c["id"] for c in mc.get_all_characters()}
    char_id = f"char_{uuid.uuid4().hex[:8]}"
    while char_id in existing_ids:
        char_id = f"char_{uuid.uuid4().hex[:8]}"

    character = {
        "id": char_id,
        "name": data["name"],
        "description": data["description"],
        "personality": data["personality"],
        "system_prompt": data["system_prompt"],
        "avatar": "",  # 空，后续可上传
    }

    mc.save_character(character)

    # 记忆文件无需手动创建：首次 /chat 时 load_memory() 会自动建默认记忆
    return {"character": character}


# 获取角色状态
@app.get("/character/state")
def get_character_state():
    """获取当前角色状态（心情、精力、当前事件）"""
    char_id = mc.get_current_character_id()
    return {
        "state": mc.get_character_state(char_id)
    }


# ============================================================
# 新增：关系信息
# ============================================================


# 获取关系信息
@app.get("/relationship")
def get_relationship():
    """获取当前角色与用户的关系（等级、最近变化原因）"""
    char_id = mc.get_current_character_id()
    mem = mc.load_memory(char_id)
    relationship = mem.get("relationship", {})
    return {
        "relationship": relationship,
        "favorability": mem.get("favorability", 50)
    }


# ============================================================
# 新增：剧情
# ============================================================


# 获取当前剧情
@app.get("/story")
def get_story():
    """获取当前剧情信息"""
    char_id = mc.get_current_character_id()
    mem = mc.load_memory(char_id)
    story = mem.get("story", {})
    return {
        "story": story
    }


# ============================================================
# 新增：聊天摘要
# ============================================================


# 获取聊天摘要
@app.get("/chat-summary")
def get_chat_summary():
    """获取聊天摘要列表"""
    char_id = mc.get_current_character_id()
    return {
        "chat_summary": mc.get_chat_summary(char_id)
    }


# ============================================================
# 新增：主动消息 & 关心消息
# ============================================================


# 获取主动消息
@app.get("/proactive-message")
def get_proactive_message():
    """获取角色的主动问候消息（基于好感度和离线时间）"""
    char_id = mc.get_current_character_id()
    return {
        "message": mc.get_proactive_message(char_id)
    }


# 获取关心消息
@app.get("/caring-message")
def get_caring_message():
    """获取角色的关心消息（基于用户画像）"""
    char_id = mc.get_current_character_id()
    msg = mc.get_caring_message(char_id)
    return {
        "message": msg
    }


# ============================================================
# 新增：事件管理
# ============================================================


class EventRequest(BaseModel):
    event: str


# 添加自定义事件
@app.post("/events")
def add_event(req: EventRequest):
    """手动添加一个事件"""
    char_id = mc.get_current_character_id()
    mc.add_event(char_id, req.event)
    return {
        "message": "事件已添加",
        "events": mc.get_events(char_id)
    }


# ============================================================
# 新增：长期记忆管理
# ============================================================


class MemoryItemRequest(BaseModel):
    memory: str


class MemoryUpdateRequest(BaseModel):
    old_memory: str
    new_memory: str


# 添加长期记忆
@app.post("/long-memory/add")
def add_long_memory(req: MemoryItemRequest):
    """手动添加一条长期记忆"""
    char_id = mc.get_current_character_id()
    mc.add_long_memory(char_id, req.memory)
    return {
        "message": "记忆已添加",
        "long_memory": mc.get_long_memories(char_id)
    }


# 更新长期记忆
@app.post("/long-memory/update")
def update_long_memory(req: MemoryUpdateRequest):
    """手动更新一条长期记忆"""
    char_id = mc.get_current_character_id()
    mc.update_long_memory(char_id, req.old_memory, req.new_memory)
    return {
        "message": "记忆已更新",
        "long_memory": mc.get_long_memories(char_id)
    }


# 删除长期记忆
@app.delete("/long-memory")
def delete_long_memory(req: MemoryItemRequest):
    """删除一条长期记忆（通过将其设为空来移除）"""
    char_id = mc.get_current_character_id()
    mem = mc.load_memory(char_id)
    memories = mem.get("long_memory", [])
    if req.memory in memories:
        memories.remove(req.memory)
        mem["long_memory"] = memories
        mc.save_memory(char_id, mem)
        return {
            "message": "记忆已删除",
            "long_memory": memories
        }
    return {
        "message": "未找到该记忆",
        "long_memory": memories
    }


# ============================================================
# RAG 记忆检索 (Memory RAG)
# ============================================================


class MemoryRagAddRequest(BaseModel):
    collection_type: str
    text: str
    metadata: dict | None = None


class MemoryRagUpdateRequest(BaseModel):
    collection_type: str
    old_text: str
    new_text: str


class MemoryRagDeleteRequest(BaseModel):
    collection_type: str
    text: str


@app.get("/memory/search")
def search_memory_rag(query: str, top_k: int = 5):
    """跨所有集合语义检索记忆"""
    char_id = mc.get_current_character_id()
    world_id = mc.get_current_world_id()
    results = memory_rag.retrieve_memories(
        char_id, query, top_k=top_k, world_id=world_id
    )
    return {"character_id": char_id, "query": query, "results": results}


@app.post("/memory/add")
def add_memory_rag(req: MemoryRagAddRequest):
    """向指定集合添加一条向量记忆"""
    char_id = mc.get_current_character_id()
    world_id = mc.get_current_world_id()
    if req.metadata is None:
        req.metadata = {}
    req.metadata.setdefault("world_id", world_id)
    doc_id = memory_rag.add_memory(
        char_id, req.collection_type, req.text, req.metadata
    )
    return {"message": "记忆已添加", "doc_id": doc_id}


@app.post("/memory/update")
def update_memory_rag(req: MemoryRagUpdateRequest):
    """更新向量记忆（删除旧文本，插入新文本）"""
    char_id = mc.get_current_character_id()
    world_id = mc.get_current_world_id()
    doc_id = memory_rag.update_memory(
        char_id, req.collection_type, req.old_text, req.new_text,
        metadata={"world_id": world_id},
    )
    return {"message": "记忆已更新", "doc_id": doc_id}


@app.post("/memory/delete")
def delete_memory_rag(req: MemoryRagDeleteRequest):
    """从向量存储中删除一条记忆"""
    char_id = mc.get_current_character_id()
    success = memory_rag.delete_memory(char_id, req.collection_type, req.text)
    return {"message": "记忆已删除" if success else "未找到匹配的记忆"}


@app.get("/memory/stats")
def memory_stats_rag():
    """获取当前角色各集合的文档数量"""
    char_id = mc.get_current_character_id()
    stats = memory_rag.get_collection_stats(char_id)
    return {"character_id": char_id, "collections": stats}


# ============================================================
# 新增：完整记忆数据
# ============================================================


# 获取完整记忆数据
@app.get("/memory/full")
def get_full_memory():
    """获取当前角色的完整记忆数据（所有动态状态）"""
    char_id = mc.get_current_character_id()
    mem = mc.load_memory(char_id)
    return {
        "memory": mem
    }


# ============================================================
# 新增：世界信息
# ============================================================


# 获取当前世界详情
@app.get("/world/current")
def get_current_world():
    """获取当前世界的完整定义"""
    world = mc.load_current_world()
    return {
        "world": world
    }


# ============================================================
# 世界事件系统 (World Event Agent)
# ============================================================


class WorldEventCreateRequest(BaseModel):
    title: str = ""
    description: str = ""
    importance: int = 5
    auto_generate: bool = False


class WorldEventUpdateRequest(BaseModel):
    event_id: str
    title: str | None = None
    description: str | None = None
    importance: int | None = None
    progress: int | None = None
    status: str | None = None


class WorldTickRequest(BaseModel):
    force: bool = False


@app.get("/world")
def get_world():
    """获取当前世界静态定义 + 动态状态（事件、环境）"""
    world = mc.load_current_world()
    if not world:
        return {"error": "world not found"}
    return world_event_agent.get_world_snapshot(mc, world)


@app.get("/world/events")
def get_world_events():
    """获取当前世界事件列表（进行中 + 历史）"""
    world_id = mc.get_current_world_id()
    return {
        "world_id": world_id,
        "current_events": mc.get_current_events(world_id),
        "history_events": mc.get_history_events(world_id),
        "world_state": mc.get_world_runtime_state(world_id),
    }


@app.post("/world/event/create")
def create_world_event(req: WorldEventCreateRequest):
    """创建世界事件（手动或 AI 自动生成）"""
    world = mc.load_current_world()
    character = mc.load_current_character()

    event_data = None
    if not req.auto_generate:
        event_data = {
            "title": req.title,
            "description": req.description,
            "importance": req.importance,
            "progress": 0,
            "status": "running",
            "impact": [],
        }

    event, world_data = world_event_agent.create_event(
        mc,
        world,
        event_data=event_data,
        auto_generate=req.auto_generate or not req.title,
    )

    if not event:
        return {"error": "事件创建失败"}

    world_event_agent.mark_proactive_notice(
        mc,
        character["id"],
        "created",
        event,
    )
    world_event_agent.apply_character_impact(mc, character, event, world)

    return {
        "message": "世界事件已创建",
        "event": event,
        "current_events": world_data.get("current_events", []),
    }


@app.post("/world/event/update")
def update_world_event(req: WorldEventUpdateRequest):
    """更新世界事件（进度、状态、标题等）"""
    world = mc.load_current_world()
    character = mc.load_current_character()
    world_id = world.get("id") or mc.get_current_world_id()

    updates = req.model_dump(exclude={"event_id"}, exclude_none=True)
    event, world_data, notification_type = world_event_agent.update_event(
        mc,
        world_id,
        req.event_id,
        updates,
    )

    if not event:
        return {"error": "事件不存在"}

    if notification_type:
        world_event_agent.mark_proactive_notice(
            mc,
            character["id"],
            notification_type,
            event,
        )
        world_event_agent.apply_character_impact(mc, character, event, world)
        if notification_type == "finished":
            world_event_agent.link_story(
                mc, character, event, "finished", world
            )

    return {
        "message": "世界事件已更新",
        "event": event,
        "current_events": world_data.get("current_events", []),
        "history_events": world_data.get("history_events", []),
    }


@app.post("/world/tick")
def world_tick(req: WorldTickRequest = WorldTickRequest()):
    """推进世界时间线：事件进度 + 自动生成 + 角色/剧情联动"""
    world = mc.load_current_world()
    character = mc.load_current_character()

    result = world_event_agent.tick(
        mc,
        character,
        world,
        force=req.force,
    )

    return result


@app.get("/world/interactions")
def get_world_interactions():
    """获取 NPC 间关系与近期互动记录"""
    world_id = mc.get_current_world_id()
    return interaction_agent.get_interaction_snapshot(mc, world_id)


@app.post("/world/interaction/simulate")
def simulate_world_interaction():
    """手动触发一次多角色互动模拟（基于当前世界事件）"""
    world = mc.load_current_world()
    result = interaction_agent.run_interaction(mc, world)
    return result


# ============================================================
# 主动问候
# ============================================================
@app.get("/proactive")
def proactive():
    character = mc.load_current_character()

    world = mc.load_current_world()

    message = proactive_engine.run(

        mc,

        character,

        world
    )

    return {
        "message": message
    }
