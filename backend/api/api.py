import asyncio
import json
import logging
import os
import shutil
import threading
import uuid

from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from pydantic import BaseModel

from funcation import memory, prompt
from funcation import memory_agent
from funcation import memory_rag
from funcation import recall_agent
from funcation import story_agent
from funcation import world_event_agent
from funcation import character_agent
from funcation.auth import get_current_user, get_db, require_admin, require_approved, require_auth, require_chat_quota
from funcation.usage import record_usage
from funcation import interaction_agent
from funcation.embedding_manager import preload
from funcation.memory_center import MemoryCenter
from funcation.proactive import proactive_engine
from funcation.conversation_manager import conversation_manager
from funcation.utils import retry_sync
from funcation.world_tick_scheduler import (
    start_world_tick_scheduler,
    stop_world_tick_scheduler,
)

load_dotenv()

from . import websocket
from .auth import router as auth_router


@asynccontextmanager
async def lifespan(application: FastAPI):
    # Startup
    tts_task = asyncio.create_task(conversation_manager.process_tts_queue())
    print("[Startup] TTS 语音合成队列已启动")
    tick_task = start_world_tick_scheduler()
    if tick_task:
        print("[Startup] 后台世界 tick 调度器已启动")
    yield
    # Shutdown
    tts_task.cancel()
    try:
        await tts_task
    except asyncio.CancelledError:
        pass
    await stop_world_tick_scheduler()


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
# 认证路由
app.include_router(auth_router, prefix="/auth")

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


def _check_character_access(character: dict, user) -> None:
    """检查用户是否有权限访问指定角色。

    内置角色（无 created_by）所有人可访问；
    用户自己的角色可访问；
    管理员可访问全部；
    否则抛出 403。
    """
    created_by = character.get("created_by")
    if created_by is None:
        return  # 内置角色，所有人可访问
    if user.is_admin:
        return  # 管理员可访问全部
    if created_by == user.id:
        return  # 创建者本人
    raise HTTPException(status_code=403, detail="无权访问该角色")


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
def chat(req: ChatRequest, user = Depends(require_chat_quota), db = Depends(get_db)):
    """分层降级：关键路径(文件IO/Prompt/DeepSeek/记忆)失败返回 error；
    非关键 agent(事件/剧情/RAG/画像/好感度/状态/向量同步)失败静默跳过。"""
    try:
        user_input = req.message

        # --- 关键路径：加载数据（带兜底）---
        try:
            character = mc.load_user_current_character(user.id)
            char_id = character["id"]
            _check_character_access(character, user)
        except Exception as e:
            logger.error("[chat] 加载角色失败: %s", e)
            return {"error": "角色数据异常，请刷新后重试"}

        messages = _safe("加载聊天历史", lambda: memory.load_memory(user.id, char_id), default=[]) or []
        mem = _safe("加载记忆", lambda: mc.load_memory(user.id, char_id), default={}) or {}
        world = _safe("加载世界观", lambda: mc.load_user_current_world(user.id), default=None)
        world_id = world.get("id") if world else None

        # --- 非关键 agent：世界事件 / 剧情（失败跳过）---
        _safe("世界事件tick", lambda: world_event_agent.tick(mc, user.id, character, world))

        def _story_block():
            story_agent.check_stories(mc, user.id, character, world)
            memory_data = mc.load_memory(user.id, char_id)
            memory_data = story_agent.sync_stories_to_state(memory_data)
            mc.save_memory(user.id, char_id, memory_data)
            _sync_story_to_rag(user.id, char_id, mc, world_id)

        _safe("剧情推进", _story_block)

        # 角色状态（剧情降级后重新读，读不到就用空）
        memory_data = _safe("加载记忆(状态)", lambda: mc.load_memory(user.id, char_id), default={}) or {}
        current_state = memory_data.get("character_state", {})

        # --- 构建 Prompt（关键）---
        try:
            _ws_mode = mc.get_user_world_mode(user.id)
            world_state_data = _safe(
                "世界状态",
                lambda: mc.load_world_state(world.get("id"), user.id, _ws_mode) if world else None,
                default=None,
            )
            npc_social = _safe(
                "NPC社交上下文",
                lambda: interaction_agent.build_social_prompt_for_character(
                    char_id, mc, world_state_data, world.get("id") if world else None, user.id, _ws_mode
                ),
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
                    user.id, char_id, user_input, top_k=10, world_id=world_id,
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

        # --- 非关键 agent：统一状态更新（画像+好感度+状态）+ RAG同步（失败跳过）---
        def _unified_block():
            mc.update_state_unified(user.id, char_id, user_input, world)
            _sync_profile_to_rag(user.id, char_id, mc, world_id)
            _sync_relationship_to_rag(user.id, char_id, mc, world_id)

        _safe("统一状态更新", _unified_block)

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
            # 记录用量
            usage = response.usage
            if usage:
                _safe("记录用量", lambda: record_usage(
                    user.id, "chat",
                    tokens_in=usage.prompt_tokens,
                    tokens_out=usage.completion_tokens,
                    db_session=db,
                ))
        except Exception as e:
            logger.error("[chat] DeepSeek 主回复失败: %s", e)
            return {"error": "AI 服务繁忙，请稍后重试"}

        messages.append({
            "role": "assistant",
            "content": ai_reply
        })

        # --- 关键路径：保存 + 记忆提取 ---
        _safe("更新最后聊天时间", lambda: mc.update_last_chat_time(user.id, char_id))
        try:
            memory.save_memory(user.id, char_id, messages)
        except Exception as e:
            logger.error("[chat] 保存聊天历史失败: %s", e)

        # 记忆提取（关键：保证不忘事，但失败不阻断回复）
        def _memory_extract():
            current_memories = mc.get_long_memories_text(user.id, char_id)
            memory_result = memory_agent.extract_memory(user_input, current_memories)
            action = memory_result.get("action", "ignore")
            if action == "add":
                mc.add_long_memory(user.id, char_id, memory_result["memory"])
            elif action == "update":
                mc.update_long_memory(
                    user.id,
                    char_id,
                    memory_result.get("old_memory", ""),
                    memory_result.get("new_memory", "")
                )

        _safe("长期记忆提取", _memory_extract)

        return {
            "reply": ai_reply,
            "favorability": mc.get_favorability(user.id, char_id)
        }

    except Exception as e:
        # 最后兜底：任何未预期的异常都不返回裸 500
        logger.exception("[chat] 未预期异常: %s", e)
        return {"error": "服务器内部错误，请重试"}


# ============================================================
# SSE 流式聊天（POST /chat/stream）
# ============================================================


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest, user=Depends(require_chat_quota), db=Depends(get_db)):
    """流式聊天：主回复逐 token 推送（SSE），非关键 agent 后台异步执行。

    事件格式:
        data: {"token":"你"}       — 单个 token
        data: {"done":true,"favorability":75}  — 完成
        data: {"error":"..."}      — 错误
    """
    loop = asyncio.get_event_loop()
    user_input = req.message

    # ── Phase 1: 关键路径 — 加载数据 ──
    try:
        character = await loop.run_in_executor(
            None, lambda: mc.load_user_current_character(user.id)
        )
        char_id = character["id"]
        _check_character_access(character, user)
    except Exception as e:
        logger.error("[chat/stream] 加载角色失败: %s", e)

        async def _err_gen():
            yield f"data: {json.dumps({'error': '角色数据异常，请刷新后重试'})}\n\n"

        return StreamingResponse(_err_gen(), media_type="text/event-stream")

    # ── Phase 1+2: 关键路径 — 加载数据 + 构建 Prompt（按依赖图并发） ──
    #
    # 依赖图：
    #   轮 1：messages | mem | world | recalled  ← 4 个任务无相互依赖，同时跑
    #         （recalled = recall_agent LLM 调用 ~300ms，是这一轮的瓶颈；
    #           IO 可被它的延迟完全吸收）
    #   轮 2：world_state | retrieved            ← world_state 依赖 world，
    #                                              retrieved 依赖 recalled+world_id
    #   轮 3：npc_social                         ← 依赖 world_state + char_id
    #   轮 4：build_system_prompt                ← 依赖以上全部
    try:
        # ── 轮 1 ──
        # recall_agent 改为：先 peek 缓存（同步几 ms），未命中则用 FALLBACK 跑 RAG
        # 不阻塞首 token，LLM 调用放后台 warm 缓存供下一轮。
        in_executor = lambda fn: loop.run_in_executor(None, fn)
        recalled = recall_agent.peek_cached_scope(user_input, char_id)
        if recalled is None:
            recalled = list(recall_agent.FALLBACK_COLLECTIONS)
            # 后台调 LLM 写缓存：run_in_executor 一调用就在 loop 里跑了，
            # 不 await 即 fire-and-forget。warm_cache_async 内部吞所有异常，
            # 所以即使 Future 没人 await 也不会冒出 "Future exception was never retrieved" 警告。
            loop.run_in_executor(
                None,
                lambda: recall_agent.warm_cache_async(user_input, char_id),
            )

        messages, mem, world = await asyncio.gather(
            in_executor(lambda: _safe("加载聊天历史", lambda: memory.load_memory(user.id, char_id), default=[]) or []),
            in_executor(lambda: _safe("加载记忆", lambda: mc.load_memory(user.id, char_id), default={}) or {}),
            in_executor(lambda: _safe("加载世界观", lambda: mc.load_user_current_world(user.id), default=None)),
        )
        world_id = world.get("id") if world else None
        _ws_mode = mc.get_user_world_mode(user.id)

        # ── 轮 2 ──
        world_state_data, retrieved = await asyncio.gather(
            in_executor(lambda: _safe("世界状态",
                                      lambda: mc.load_world_state(world.get("id"), user.id, _ws_mode) if world else None,
                                      default=None)),
            in_executor(lambda: _safe(
                "RAG检索",
                lambda: memory_rag.retrieve_memories(
                    user.id, char_id, user_input, top_k=10, world_id=world_id,
                    collections=recalled,
                ),
                default=[],
            ) or []),
        )

        # ── 轮 3 ──
        npc_social = await in_executor(lambda: _safe(
            "NPC社交上下文",
            lambda: interaction_agent.build_social_prompt_for_character(
                char_id, mc, world_state_data, world.get("id") if world else None, user.id, _ws_mode
            ),
            default=None,
        ))

        # ── 轮 4 ──
        system_prompt = await in_executor(lambda: prompt.build_system_prompt(
            character_id=char_id,
            memory_data=mem,
            world=world,
            messages=messages,
            world_state=world_state_data,
            npc_social_context=npc_social,
            retrieved_memories=retrieved,
        ))
    except Exception as e:
        logger.error("[chat/stream] 构建 Prompt 失败: %s", e)

        async def _err_gen2():
            yield f"data: {json.dumps({'error': '对话上下文构建失败，请重试'})}\n\n"

        return StreamingResponse(_err_gen2(), media_type="text/event-stream")

    if messages and messages[0]["role"] == "system":
        messages[0]["content"] = system_prompt
    else:
        messages.insert(0, {"role": "system", "content": system_prompt})

    messages.append({"role": "user", "content": user_input})

    # ── Phase 3: 启动后台非关键 agent ──
    async def _bg_agents():
        """后台异步执行：世界事件 / 剧情 / 统一状态更新 + RAG 同步"""
        try:
            await loop.run_in_executor(
                None,
                lambda: _safe("世界事件tick",
                              lambda: world_event_agent.tick(mc, user.id, character, world)),
            )
        except Exception:
            pass
        try:
            await loop.run_in_executor(
                None,
                lambda: _safe("剧情推进", lambda: (
                    story_agent.check_story(mc, user.id, character, world),
                    _updated := mc.load_memory(user.id, char_id),
                    _updated := story_agent.sync_story_to_state(_updated),
                    mc.save_memory(user.id, char_id, _updated),
                    _sync_story_to_rag(user.id, char_id, mc, world_id),
                )),
            )
        except Exception:
            pass
        try:

            def _unified_with_rag():
                mc.update_state_unified(user.id, char_id, user_input, world)
                _sync_profile_to_rag(user.id, char_id, mc, world_id)
                _sync_relationship_to_rag(user.id, char_id, mc, world_id)

            await loop.run_in_executor(
                None,
                lambda: _safe("统一状态更新", _unified_with_rag),
            )
        except Exception:
            pass

    bg_task = asyncio.create_task(_bg_agents())

    # ── Phase 4: SSE 流式生成 ──
    #
    # 流水线设计（避免轮询，让 token 真正即时下发）：
    # _stream_producer 在独立线程跑 DeepSeek streaming，每拿到一个 token 就通过
    # loop.call_soon_threadsafe 把它 put 进 asyncio.Queue；_stream_generator 协程
    # await queue.get() 真正阻塞唤醒，没有 sleep 轮询。

    token_queue: asyncio.Queue = asyncio.Queue()

    def _stream_producer():
        """在独立线程中调用 DeepSeek streaming，将 token 投递到事件循环的 asyncio.Queue。"""
        try:
            stream = client.chat.completions.create(
                model="deepseek-chat",
                messages=messages,
                temperature=0.9,
                stream=True,
            )
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    loop.call_soon_threadsafe(
                        token_queue.put_nowait, ("token", chunk.choices[0].delta.content)
                    )
            loop.call_soon_threadsafe(token_queue.put_nowait, ("done", None))
        except Exception as exc:
            loop.call_soon_threadsafe(token_queue.put_nowait, ("error", str(exc)))

    async def _post_process(full_reply: str):
        """SSE 关闭后在后台跑：保存历史 + 记忆提取 + 记录用量 + 等待 bg_agents。

        前端在 done 那一刻就拿到 favorability，loading 立刻消失；不阻塞 SSE 关闭。
        """
        messages.append({"role": "assistant", "content": full_reply})
        try:
            await loop.run_in_executor(
                None,
                lambda: (
                    mc.update_last_chat_time(user.id, char_id),
                    memory.save_memory(user.id, char_id, messages),
                ),
            )
        except Exception as e:
            logger.warning("[chat/stream] 保存历史失败: %s", e)

        def _memory_extraction():
            current_memories = mc.get_long_memories_text(user.id, char_id)
            mr = memory_agent.extract_memory(user_input, current_memories)
            action = mr.get("action", "ignore")
            if action == "add":
                mc.add_long_memory(user.id, char_id, mr["memory"])
            elif action == "update":
                mc.update_long_memory(
                    user.id, char_id,
                    mr.get("old_memory", ""),
                    mr.get("new_memory", ""),
                )

        await loop.run_in_executor(
            None, lambda: _safe("长期记忆提取", _memory_extraction)
        )
        await loop.run_in_executor(
            None,
            lambda: _safe("记录用量", lambda: record_usage(
                user.id, "chat", db_session=db,
            )),
        )
        try:
            await asyncio.wait_for(bg_task, timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("[chat/stream] 后台 agent 未在 5s 内完成，已跳过")

    async def _stream_generator():
        full_reply = ""
        stream_thread = threading.Thread(target=_stream_producer, daemon=True)
        stream_thread.start()

        # 真正阻塞等待 token，不轮询
        while True:
            msg_type, data = await token_queue.get()
            if msg_type == "token":
                full_reply += data
                yield f"data: {json.dumps({'token': data}, ensure_ascii=False)}\n\n"
            elif msg_type == "done":
                break
            elif msg_type == "error":
                logger.error("[chat/stream] DeepSeek 流式失败: %s", data)
                yield f"data: {json.dumps({'error': 'AI 服务繁忙，请稍后重试'})}\n\n"
                # 错误也要把 bg_task 收尾，不然会泄漏
                asyncio.create_task(_drain_bg_task(bg_task))
                return

        # 发送 done + favorability，然后立即关闭 SSE。后处理放后台跑。
        favorability = await loop.run_in_executor(
            None, lambda: mc.get_favorability(user.id, char_id)
        )
        yield f"data: {json.dumps({'done': True, 'favorability': favorability})}\n\n"

        # 后处理（保存历史/记忆/用量）独立 task 跑，不阻塞 SSE 关闭
        asyncio.create_task(_post_process(full_reply))

    return StreamingResponse(
        _stream_generator(),
        media_type="text/event-stream",
        headers={
            # 关闭 nginx / 反向代理对 SSE 的缓冲，否则 token 会被攒着批量发
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


async def _drain_bg_task(bg_task: asyncio.Task):
    """错误路径下也消化 bg_task，避免 'Task was destroyed but it is pending' 警告。"""
    try:
        await asyncio.wait_for(bg_task, timeout=5.0)
    except (asyncio.TimeoutError, Exception):
        pass


# ============================================================
# RAG 同步辅助函数
# ============================================================


def _sync_profile_to_rag(user_id: int, char_id: str, mc: MemoryCenter, world_id: str | None):
    """将当前画像字段同步到 profile 集合（upsert）"""
    profile = mc.get_profile(user_id, char_id)
    field_labels = {"name": "姓名", "city": "城市", "job": "职业", "mood": "情绪"}
    for field, label in field_labels.items():
        value = profile.get(field, "")
        text = f"用户{label}：{value}" if value else f"用户{label}：未知"
        memory_rag.upsert_memory(
            user_id, char_id, "profile", text,
            doc_id=f"u{user_id}_{char_id}_profile_{field}",
            metadata={"field": field, "world_id": world_id or ""},
        )


def _sync_story_to_rag(user_id: int, char_id: str, mc: MemoryCenter, world_id: str | None):
    """将所有活跃剧情同步到 story 集合（upsert 每条故事的概览 + 当前阶段）"""
    mem = mc.load_memory(user_id, char_id)
    stories = mem.get("stories", [])
    if not stories:
        return

    for story in stories:
        if story.get("status") != "active":
            continue
        story_id = story.get("id", "")
        if not story_id:
            continue

        story_type = story.get("type", "main")
        type_label = "主线" if story_type == "main" else "支线"

        # 剧情概览
        overview = f"【{type_label}】{story.get('title', '')}。{story.get('description', '')}"
        memory_rag.upsert_memory(
            user_id, char_id, "story", overview,
            doc_id=f"u{user_id}_{char_id}_story_{story_id}_overview",
            metadata={
                "story_id": story_id,
                "story_type": story_type,
                "world_id": world_id or "",
            },
        )

        # 各阶段
        stages = story.get("stages", [])
        current_stage_idx = story.get("stage", 0)
        for i, stage_text in enumerate(stages):
            prefix = "【当前阶段】" if i == current_stage_idx else ""
            memory_rag.upsert_memory(
                user_id, char_id, "story", f"{prefix}{stage_text}",
                doc_id=f"u{user_id}_{char_id}_story_{story_id}_stage_{i}",
                metadata={
                    "story_id": story_id,
                    "story_type": story_type,
                    "stage_index": i,
                    "is_current": i == current_stage_idx,
                    "world_id": world_id or "",
                },
            )


def _sync_relationship_to_rag(user_id: int, char_id: str, mc: MemoryCenter, world_id: str | None):
    """将当前关系同步到 relationship 集合（upsert）"""
    mem = mc.load_memory(user_id, char_id)
    rel = mem.get("relationship", {})
    level = rel.get("level", "普通")
    reason = rel.get("last_reason", "")
    fav = mem.get("favorability", 50)
    if reason:
        text = f"关系等级：{level}（好感度：{fav}），最近变化原因：{reason}"
    else:
        text = f"关系等级：{level}（好感度：{fav}）"
    memory_rag.upsert_memory(
        user_id, char_id, "relationship", text,
        doc_id=f"u{user_id}_{char_id}_relationship",
        metadata={"level": level, "favorability": fav, "world_id": world_id or ""},
    )


# 获取好感度
@app.get("/favorability")
def favorability(user = Depends(require_auth)):
    char_id = mc.get_user_current_character_id(user.id)
    return {
        "favorability": mc.get_favorability(user.id, char_id)
    }


# 获取用户画像
@app.get("/profile")
def profile(user = Depends(require_auth)):
    char_id = mc.get_user_current_character_id(user.id)
    return {
        "profile": mc.get_profile(user.id, char_id)
    }


# 保存用户画像
@app.post("/profile")
def save_profile(req: ChatRequest, user = Depends(require_approved)):
    char_id = mc.get_user_current_character_id(user.id)
    try:
        profile = json.loads(req.message)
        mem = mc.load_memory(user.id, char_id)
        mem["profile"] = profile
        mc.save_memory(user.id, char_id, mem)
    except:
        pass
    return {
        "message": "保存成功"
    }


# 获取历史记录
@app.get("/history")
def history(user = Depends(require_auth)):
    character = mc.load_user_current_character(user.id)
    messages = memory.load_memory(user.id, character["id"])
    return {
        "messages": messages[-10:]
    }


# 获取记忆
@app.get("/memory")
def get_memory(user = Depends(require_auth)):
    character = mc.load_user_current_character(user.id)
    messages = memory.load_memory(user.id, character["id"])
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
def clear_memory(user = Depends(require_approved)):
    character = mc.load_user_current_character(user.id)
    memory.clear_memory(user.id, character["id"])
    return {
        "message": "清空成功"
    }


# 获取角色列表（用户只能看到自己的角色 + 内置角色，管理员看全部）
@app.get("/characters")
def get_characters(user = Depends(require_auth)):
    if user.is_admin:
        return {"characters": mc.get_all_characters()}
    return {
        "characters": mc.get_all_characters(user_id=user.id)
    }


# 切换角色
@app.post("/character/switch")
def switch_character(req: SwitchCharacterRequest, user = Depends(require_approved)):
    character = mc.load_character_by_id(req.character_id)
    _check_character_access(character, user)
    mc.set_user_current_character(user.id, req.character_id)
    return {
        "message": "切换成功"
    }


# 获取世界列表
@app.get("/worlds")
def get_worlds(user = Depends(require_auth)):
    return {
        "worlds": mc.get_all_worlds()
    }


# 切换世界
@app.post("/world/switch")
def switch_world(req: SwitchCharacterRequest, user = Depends(require_approved)):
    mc.set_user_current_world(user.id, req.character_id)
    return {
        "message": "切换成功"
    }


# 获取长期记忆
@app.get("/long-memory")
def get_long_memory(user = Depends(require_auth)):
    char_id = mc.get_user_current_character_id(user.id)
    return {
        "long_memory": mc.get_long_memories(user.id, char_id)
    }


# 获取事件
@app.get("/events")
def get_events(user = Depends(require_auth)):
    char_id = mc.get_user_current_character_id(user.id)
    return {
        "events": mc.get_events(user.id, char_id)
    }


# ============================================================
# 新增：角色信息
# ============================================================


# 获取当前角色详情
@app.get("/character/current")
def get_current_character(user = Depends(require_auth)):
    """获取当前角色的完整静态定义"""
    character = mc.load_user_current_character(user.id)
    _check_character_access(character, user)
    return {
        "character": character
    }


# 上传角色头像
@app.post("/character/avatar")
async def upload_character_avatar(file: UploadFile = File(...), user = Depends(require_approved)):
    """上传当前角色的头像图片"""
    char_id = mc.get_user_current_character_id(user.id)

    # 校验角色访问权限
    character = mc.load_user_current_character(user.id)
    _check_character_access(character, user)

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
def create_character(req: CharacterCreateRequest, user = Depends(require_approved), db = Depends(get_db)):
    """根据关键词由 DeepSeek 生成一个新角色并保存"""
    # 角色数限制（admin 不限）
    if not user.is_admin:
        user_chars = [c for c in mc.get_all_characters() if c.get("created_by") == user.id]
        if len(user_chars) >= user.character_limit:
            return {"error": f"已达角色数量上限({user.character_limit}个)，请删除部分角色后再创建"}

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
        "created_by": user.id,  # 记录创建者
    }

    mc.save_character(character)

    # 记录用量
    _safe("记录用量", lambda: record_usage(user.id, "character_create", db_session=db))

    # 记忆文件无需手动创建：首次 /chat 时 load_memory() 会自动建默认记忆
    return {"character": character}


# 删除角色
class DeleteCharacterRequest(BaseModel):
    character_id: str


@app.post("/character/delete")
def delete_character(req: DeleteCharacterRequest, user = Depends(require_approved)):
    character_id = req.character_id
    """删除角色（仅创建者或 admin 可删）。内置角色（无 created_by）禁止删除。"""
    # 加载角色定义
    character = mc.load_character_by_id(character_id)
    if not character:
        return {"error": "角色不存在"}

    created_by = character.get("created_by")
    if created_by is None:
        return {"error": "内置角色不可删除"}

    if not user.is_admin and created_by != user.id:
        return {"error": "无权删除该角色", "status": 403}

    # 删除角色定义文件
    char_path = os.path.join("data", "characters", f"{character_id}.json")
    try:
        os.remove(char_path)
    except FileNotFoundError:
        pass

    # 删除记忆文件
    mem_path = os.path.join("data", "memories", str(created_by), f"{character_id}.json")
    try:
        os.remove(mem_path)
    except FileNotFoundError:
        pass

    # 删除聊天历史
    from funcation import memory as mem_module
    mem_module.delete_memory(created_by, character_id)

    # 删除 ChromaDB 集合
    from funcation import memory_rag
    memory_rag.purge_character(created_by, character_id)

    return {"message": f"角色 {character.get('name', character_id)} 已删除"}


# 获取角色状态
@app.get("/character/state")
def get_character_state(user = Depends(require_auth)):
    """获取当前角色状态（心情、精力、当前事件）"""
    char_id = mc.get_user_current_character_id(user.id)
    return {
        "state": mc.get_character_state(user.id, char_id)
    }


# ============================================================
# 新增：关系信息
# ============================================================


# 获取关系信息
@app.get("/relationship")
def get_relationship(user = Depends(require_auth)):
    """获取当前角色与用户的关系（等级、最近变化原因）"""
    char_id = mc.get_user_current_character_id(user.id)
    mem = mc.load_memory(user.id, char_id)
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
def get_story(user = Depends(require_auth)):
    """获取当前所有剧情（主线 + 支线 + 历史归档）"""
    char_id = mc.get_user_current_character_id(user.id)
    mem = mc.load_memory(user.id, char_id)
    stories = mem.get("stories", [])
    story_history = mem.get("story_history", [])
    # 兼容旧前端：仍返回 story 字段（取主线 active 的第一条）
    main_active = next(
        (s for s in stories if s.get("type") == "main" and s.get("status") == "active"),
        None,
    )
    return {
        "stories": stories,
        "story_history": story_history,
        "story": main_active or {},  # 兼容字段
    }


class StoryAdvanceRequest(BaseModel):
    story_id: str


@app.post("/story/advance")
def advance_story_api(req: StoryAdvanceRequest, user = Depends(require_approved)):
    """手动推进指定剧情的当前阶段"""
    from funcation import story_agent

    char_id = mc.get_user_current_character_id(user.id)
    mem = mc.load_memory(user.id, char_id)
    stories = mem.get("stories", [])

    target = next((s for s in stories if s.get("id") == req.story_id), None)
    if not target:
        return {"error": "剧情未找到"}
    if target.get("status") != "active":
        return {"error": "剧情非激活状态，不能推进"}
    if story_agent.is_story_finished(target):
        return {"error": "剧情已完结"}

    target, branch_created = story_agent.advance_story(target, mem)
    mem["stories"] = stories
    mc.save_memory(user.id, char_id, mem)
    return {
        "message": "已推进",
        "story": target,
        "branch_created": branch_created,
    }


class StoryBranchRequest(BaseModel):
    story_id: str
    reason: str = "手动存档"


@app.post("/story/branch")
def branch_story_api(req: StoryBranchRequest, user = Depends(require_approved)):
    """手动在当前 stage 创建一个分支存档点"""
    char_id = mc.get_user_current_character_id(user.id)
    mem = mc.load_memory(user.id, char_id)
    stories = mem.get("stories", [])

    target = next((s for s in stories if s.get("id") == req.story_id), None)
    if not target:
        return {"error": "剧情未找到"}

    import datetime as _dt
    stage = target.get("stage", 0)
    branch_points = target.setdefault("branch_points", [])
    branch_points.append({
        "stage": stage,
        "at": _dt.datetime.now().strftime("%Y-%m-%d"),
        "reason": req.reason,
        "favorability": mem.get("favorability", 50),
        "alt_direction": "（手动存档点）",
    })
    mc.save_memory(user.id, char_id, mem)
    return {"message": "已存档分支点", "story": target}


# ============================================================
# 新增：聊天摘要
# ============================================================


# 获取聊天摘要
@app.get("/chat-summary")
def get_chat_summary(user = Depends(require_auth)):
    """获取聊天摘要列表"""
    char_id = mc.get_user_current_character_id(user.id)
    return {
        "chat_summary": mc.get_chat_summary(user.id, char_id)
    }


# ============================================================
# 新增：主动消息 & 关心消息
# ============================================================


# 获取主动消息
@app.get("/proactive-message")
def get_proactive_message(user = Depends(require_auth)):
    """获取角色的主动问候消息（基于好感度和离线时间）"""
    char_id = mc.get_user_current_character_id(user.id)
    return {
        "message": mc.get_proactive_message(user.id, char_id)
    }


# 获取关心消息
@app.get("/caring-message")
def get_caring_message(user = Depends(require_auth)):
    """获取角色的关心消息（基于用户画像）"""
    char_id = mc.get_user_current_character_id(user.id)
    msg = mc.get_caring_message(user.id, char_id)
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
def add_event(req: EventRequest, user = Depends(require_approved)):
    """手动添加一个事件"""
    char_id = mc.get_user_current_character_id(user.id)
    mc.add_event(user.id, char_id, req.event)
    return {
        "message": "事件已添加",
        "events": mc.get_events(user.id, char_id)
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
def add_long_memory(req: MemoryItemRequest, user = Depends(require_approved)):
    """手动添加一条长期记忆"""
    char_id = mc.get_user_current_character_id(user.id)
    mc.add_long_memory(user.id, char_id, req.memory)
    return {
        "message": "记忆已添加",
        "long_memory": mc.get_long_memories(user.id, char_id)
    }


# 更新长期记忆
@app.post("/long-memory/update")
def update_long_memory(req: MemoryUpdateRequest, user = Depends(require_approved)):
    """手动更新一条长期记忆"""
    char_id = mc.get_user_current_character_id(user.id)
    mc.update_long_memory(user.id, char_id, req.old_memory, req.new_memory)
    return {
        "message": "记忆已更新",
        "long_memory": mc.get_long_memories(user.id, char_id)
    }


# 删除长期记忆
@app.delete("/long-memory")
def delete_long_memory(req: MemoryItemRequest, user = Depends(require_approved)):
    """删除一条长期记忆（通过将其设为空来移除）"""
    char_id = mc.get_user_current_character_id(user.id)
    mem = mc.load_memory(user.id, char_id)
    memories = mem.get("long_memory", [])
    if req.memory in memories:
        memories.remove(req.memory)
        mem["long_memory"] = memories
        mc.save_memory(user.id, char_id, mem)
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
def search_memory_rag(query: str, top_k: int = 5, user = Depends(require_auth)):
    """跨所有集合语义检索记忆"""
    char_id = mc.get_user_current_character_id(user.id)
    world_id = mc.get_user_current_world_id(user.id)
    results = memory_rag.retrieve_memories(
        user.id, char_id, query, top_k=top_k, world_id=world_id
    )
    return {"character_id": char_id, "query": query, "results": results}


@app.post("/memory/add")
def add_memory_rag(req: MemoryRagAddRequest, user = Depends(require_approved)):
    """向指定集合添加一条向量记忆"""
    char_id = mc.get_user_current_character_id(user.id)
    world_id = mc.get_user_current_world_id(user.id)
    if req.metadata is None:
        req.metadata = {}
    req.metadata.setdefault("world_id", world_id)
    doc_id = memory_rag.add_memory(
        user.id, char_id, req.collection_type, req.text, req.metadata
    )
    return {"message": "记忆已添加", "doc_id": doc_id}


@app.post("/memory/update")
def update_memory_rag(req: MemoryRagUpdateRequest, user = Depends(require_approved)):
    """更新向量记忆（删除旧文本，插入新文本）"""
    char_id = mc.get_user_current_character_id(user.id)
    world_id = mc.get_user_current_world_id(user.id)
    doc_id = memory_rag.update_memory(
        user.id, char_id, req.collection_type, req.old_text, req.new_text,
        metadata={"world_id": world_id},
    )
    return {"message": "记忆已更新", "doc_id": doc_id}


@app.post("/memory/delete")
def delete_memory_rag(req: MemoryRagDeleteRequest, user = Depends(require_approved)):
    """从向量存储中删除一条记忆"""
    char_id = mc.get_user_current_character_id(user.id)
    success = memory_rag.delete_memory(user.id, char_id, req.collection_type, req.text)
    return {"message": "记忆已删除" if success else "未找到匹配的记忆"}


@app.get("/memory/stats")
def memory_stats_rag(user = Depends(require_auth)):
    """获取当前角色各集合的文档数量（ChromaDB + JSON 混合统计）"""
    char_id = mc.get_user_current_character_id(user.id)
    stats = memory_rag.get_collection_stats(user.id, char_id)
    # profile / story / relationship 存在 JSON 中，不在 ChromaDB，需要单独统计
    mem = mc.load_memory(user.id, char_id)
    profile = mem.get("profile", {})
    stats["profile"] = sum(1 for v in profile.values() if v) if profile else 0
    story = mem.get("story", {})
    stats["story"] = 1 if story.get("title") else 0
    relationship = mem.get("relationship", {})
    stats["relationship"] = 1 if relationship.get("level") else 0
    return {"character_id": char_id, "collections": stats}


# ============================================================
# 新增：完整记忆数据
# ============================================================


# 获取完整记忆数据
@app.get("/memory/full")
def get_full_memory(user = Depends(require_auth)):
    """获取当前角色的完整记忆数据（所有动态状态）"""
    char_id = mc.get_user_current_character_id(user.id)
    mem = mc.load_memory(user.id, char_id)
    return {
        "memory": mem
    }


# ============================================================
# 新增：世界信息
# ============================================================


# 获取当前世界详情
@app.get("/world/current")
def get_current_world(user = Depends(require_auth)):
    """获取当前世界的完整定义 + 模式"""
    world = mc.load_user_current_world(user.id)
    mode = mc.get_user_world_mode(user.id)
    return {
        "world": world,
        "mode": mode
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
def get_world(user = Depends(require_auth)):
    """获取当前世界静态定义 + 动态状态（事件、环境），按 mode 路由"""
    world = mc.load_user_current_world(user.id)
    if not world:
        return {"error": "world not found"}
    mode = mc.get_user_world_mode(user.id)
    return world_event_agent.get_world_snapshot(mc, world, user.id, mode)


@app.get("/world/events")
def get_world_events(user = Depends(require_auth)):
    """获取当前世界事件列表（进行中 + 历史），按 mode 路由"""
    world_id = mc.get_user_current_world_id(user.id)
    mode = mc.get_user_world_mode(user.id)
    return {
        "world_id": world_id,
        "mode": mode,
        "current_events": mc.get_current_events(world_id, user.id, mode),
        "history_events": mc.get_history_events(world_id, user.id, mode),
        "world_state": mc.get_world_runtime_state(world_id, user.id, mode),
    }


@app.post("/world/event/create")
def create_world_event(req: WorldEventCreateRequest, user = Depends(require_approved)):
    """创建世界事件（手动或 AI 自动生成），按 mode 路由"""
    world = mc.load_user_current_world(user.id)
    character = mc.load_user_current_character(user.id)
    mode = mc.get_user_world_mode(user.id)

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
        user_id=user.id,
        mode=mode,
    )

    if not event:
        return {"error": "事件创建失败"}

    # 创建事件对当前用户即时影响（公共世界用 seen 去重）
    world_event_agent.apply_world_impact_to_user(
        mc, user.id, character, world,
        [{"type": "created", "event": dict(event)}], mode,
    )

    return {
        "message": "世界事件已创建",
        "event": event,
        "current_events": world_data.get("current_events", []),
    }


@app.post("/world/event/update")
def update_world_event(req: WorldEventUpdateRequest, user = Depends(require_approved)):
    """更新世界事件（进度、状态、标题等），按 mode 路由"""
    world = mc.load_user_current_world(user.id)
    character = mc.load_user_current_character(user.id)
    world_id = world.get("id") or mc.get_user_current_world_id(user.id)
    mode = mc.get_user_world_mode(user.id)

    updates = req.model_dump(exclude={"event_id"}, exclude_none=True)
    event, world_data, notification_type = world_event_agent.update_event(
        mc,
        world_id,
        req.event_id,
        updates,
        user_id=user.id,
        mode=mode,
    )

    if not event:
        return {"error": "事件不存在"}

    if notification_type:
        world_event_agent.apply_world_impact_to_user(
            mc, user.id, character, world,
            [{"type": notification_type, "event": dict(event)}], mode,
        )

    return {
        "message": "世界事件已更新",
        "event": event,
        "current_events": world_data.get("current_events", []),
        "history_events": world_data.get("history_events", []),
    }


@app.post("/world/tick")
def world_tick(req: WorldTickRequest = WorldTickRequest(), user = Depends(require_approved)):
    """推进世界时间线：事件进度 + 自动生成 + 角色/剧情联动"""
    world = mc.load_user_current_world(user.id)
    character = mc.load_user_current_character(user.id)

    result = world_event_agent.tick(
        mc,
        user.id,
        character,
        world,
        force=req.force,
    )

    return result


@app.get("/world/interactions")
def get_world_interactions(user = Depends(require_auth)):
    """获取 NPC 间关系与近期互动记录，按 mode 路由"""
    world_id = mc.get_user_current_world_id(user.id)
    mode = mc.get_user_world_mode(user.id)
    return interaction_agent.get_interaction_snapshot(mc, world_id, user.id, mode)


@app.post("/world/interaction/simulate")
def simulate_world_interaction(user = Depends(require_approved)):
    """手动触发一次多角色互动模拟（基于当前世界事件），按 mode 路由"""
    world = mc.load_user_current_world(user.id)
    mode = mc.get_user_world_mode(user.id)
    result = interaction_agent.run_interaction(mc, world, None, user.id, mode)
    return result


# ============================================================
# 主动问候
# ============================================================
@app.get("/proactive")
def proactive(user = Depends(require_auth)):
    character = mc.load_user_current_character(user.id)
    world = mc.load_user_current_world(user.id)
    message = proactive_engine.run(mc, user.id, character, world)
    return {
        "message": message
    }
