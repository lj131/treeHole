"""
pytest 公共夹具

关键约束（务必先读）：
1. 所有 agent 在「模块导入时」创建 client = OpenAI(...)，部分无 key 守卫——
   必须在任何 funcation import 之前注入 DEEPSEEK_API_KEY，否则 import 直接炸。
2. funcation.auth 在导入时跑 _migrate_legacy_to_admin()，用相对路径 data/memories
   操作文件——必须在 import 前把 cwd 切到临时目录，否则会动到真实仓库数据。
3. DATABASE_URL 可被 env 覆盖（funcation/auth.py:36），导入前指向临时 sqlite。
4. MemoryCenter 的数据目录是相对常量 data/...，靠 cwd 隔离。
5. ChromaDB / fastembed 在测试里全程绕开（disable_rag 把 memory_rag 的读写全 mock）。

所以本文件顶部（模块导入期，早于任何 test 收集）就把环境变量 + cwd + preload 钉死。
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

# ============================================================
# 1. 环境 & cwd —— 必须在 import funcation/* 之前完成
# ============================================================
os.environ.setdefault("DEEPSEEK_API_KEY", "test-key-not-real")
os.environ.setdefault("OPENAI_BASE_URL", "https://api.deepseek.com")
os.environ.setdefault("RUN_BACKGROUND_TICK", "0")          # 关掉后台 world tick 调度器
os.environ.setdefault("EMBEDDING_PROVIDER", "fastembed")   # 仅配置，实际 embed 被 disable_rag 绕开

# 一次性会话级临时根目录：auth 导入时的 _migrate_legacy_to_admin 会在这里跑（空数据 → no-op）
_SESSION_TMP = tempfile.mkdtemp(prefix="amy_test_session_")
os.chdir(_SESSION_TMP)                                     # 切 cwd，隔离所有相对路径
_DATA_TMP = Path(_SESSION_TMP) / "data"
(_DATA_TMP / "characters").mkdir(parents=True, exist_ok=True)
(_DATA_TMP / "worlds").mkdir(parents=True, exist_ok=True)

# SQLite 指向会话临时库（funcation.auth 导入时读 DATABASE_URL）
_db_path = (_DATA_TMP / "users.db").as_posix()
os.environ["DATABASE_URL"] = f"sqlite:///{_db_path}"

# 后端源 data 目录（绝对路径，供拷贝内置角色/世界用）
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_SOURCE_DATA = _BACKEND_DIR / "data"

# 显式把 backend/ 加入 sys.path：os.chdir 之后依赖 pytest 自动加 rootdir，
# CI 上可能因 pytest 版本/配置差异导致 rootdir 检测失败，funcation 找不到。
sys.path.insert(0, str(_BACKEND_DIR))


def _cleanup_session_tmp():
    try:
        os.chdir(_BACKEND_DIR)
    except Exception:
        pass
    shutil.rmtree(_SESSION_TMP, ignore_errors=True)


import atexit
atexit.register(_cleanup_session_tmp)


# ============================================================
# 2. 把 embedding 预热改成 no-op，避免 import api.api 时下载/加载模型
#    必须在 api.api 被 import 之前替换（api.py 顶部 from ... import preload）
# ============================================================
import funcation.embedding_manager as _emb  # noqa: E402

_emb.preload = lambda *a, **k: None


# ============================================================
# 3. FakeDeepSeek —— 拦截所有 client.chat.completions.create 调用
# ============================================================
class _FakeUsage:
    def __init__(self):
        self.prompt_tokens = 10
        self.completion_tokens = 20
        self.total_tokens = 30


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]
        self.usage = _FakeUsage()


class _Completions:
    def __init__(self, fake):
        self._fake = fake

    def create(self, **kwargs):
        return self._fake._dispatch(kwargs)


class _Chat:
    def __init__(self, fake):
        self.completions = _Completions(fake)


class FakeDeepSeek:
    """假 DeepSeek 客户端。

    默认按 prompt 关键字路由返回 JSON 或纯文本；测试可改 self.handler 自定义。
    所有调用记到 self.calls，便于断言「确实调过 LLM」。
    """

    def __init__(self):
        self.chat = _Chat(self)
        self.calls = []
        self.handler = None  # 测试可覆盖：(kwargs) -> content str

    def _dispatch(self, kwargs):
        self.calls.append(kwargs)
        if self.handler is not None:
            content = self.handler(kwargs)
        else:
            content = self._default_handler(kwargs)
        return _FakeResponse(content)

    @staticmethod
    def _default_handler(kwargs):
        import json

        # 流式调用（/chat/stream）—— 测试不覆盖流式，给个占位
        if kwargs.get("stream"):
            return ""

        resp_format = kwargs.get("response_format")
        messages = kwargs.get("messages", [])
        # 拼所有消息文本做关键字判断
        blob = " ".join(
            (m.get("content", "") if isinstance(m, dict) else str(getattr(m, "content", "")))
            for m in messages
        )

        if resp_format == {"type": "json_object"}:
            if any(k in blob for k in ("好感", "画像", "心情", "能量", "统一状态")):
                # unified_state_agent 期望 {profile, relationship, character_state}
                return json.dumps({
                    "profile": {},
                    "relationship": {"delta": 1, "reason": "测试好感+1"},
                    "character_state": {"mood": "开心", "energy": 80},
                }, ensure_ascii=False)
            if "记忆" in blob and any(k in blob for k in ("add", "update", "ignore", "长期")):
                # memory_agent.extract_memory 期望 {action, ...}
                return json.dumps({"action": "ignore"}, ensure_ascii=False)
            if any(k in blob for k in ("剧情", "故事", "story")):
                return json.dumps({"title": "测试剧情", "advance": False}, ensure_ascii=False)
            if any(k in blob for k in ("事件", "世界", "event")):
                return json.dumps({"events": []}, ensure_ascii=False)
            if any(k in blob for k in ("集合", "检索", "collection", "范围")):
                return json.dumps({"collections": []}, ensure_ascii=False)
            return json.dumps({"reply": "测试回复"}, ensure_ascii=False)

        # 纯文本主回复（/chat 的 DeepSeek 主调用）
        return "这是来自测试桩的回复。"


# agent 模块列表：有「模块级 client」的需要被替换成 FakeDeepSeek
_AGENT_MODULES = [
    "funcation.story_agent",
    "funcation.world_event_agent",
    "funcation.relationship_agent",
    "funcation.memory_agent",
    "funcation.recall_agent",
    "funcation.interaction_agent",
    "funcation.character_agent",
    "funcation.unified_state_agent",
    "funcation.profile_agent",
    "funcation.event_agent",
    "funcation.proactive_agent",
    "funcation.proactive.proactive_message_agent",
]


import pytest  # noqa: E402


# ============================================================
# 4. Fixtures
# ============================================================
#
# 作用域策略（重要）：
# - client / fake_deepseek / disable_rag / admin_token → session 级。
#   整个会话只起一次 TestClient lifespan，避免反复 start/stop lifespan 时
#   TTS 队列任务 / world_tick 调度器单例残留导致第二个 TestClient 卡死。
# - tmp_data_dir → function 级。每个测试 chdir 到独立 tmp + 拷内置角色/世界，
#   保证 MemoryCenter 的相对路径落到该测试私有目录（数据隔离靠 cwd，不靠 TestClient）。
# - approved_user → function 级。每测试注册独立用户，避免会话级 DB 串档。

@pytest.fixture
def tmp_data_dir(tmp_path, monkeypatch):
    """每个测试一个干净的数据目录：chdir 进去 + 建子目录 + 拷内置角色/世界。

    funcation.auth 已在会话级导入过（_migrate_legacy_to_admin 只跑一次），
    所以这里切 cwd 是安全的，不会再触发迁移。
    """
    monkeypatch.chdir(tmp_path)
    data = tmp_path / "data"
    for sub in ("characters", "worlds", "memories", "world_state", "avatars",
                "chat_history"):
        (data / sub).mkdir(parents=True, exist_ok=True)

    # 拷贝内置角色 + 世界（供 prompt._load_character / mc.load_* 用）
    src_chars = _SOURCE_DATA / "characters"
    if src_chars.exists():
        for f in src_chars.glob("*.json"):
            shutil.copy2(f, data / "characters" / f.name)
    src_worlds = _SOURCE_DATA / "worlds"
    if src_worlds.exists():
        for f in src_worlds.glob("*.json"):
            shutil.copy2(f, data / "worlds" / f.name)

    # CI 兜底：backend/data 整个目录被 .gitignore，checkout 后可能没有内置角色/世界。
    # 缺哪个就写最小桩，保证测试 hermetic（不依赖运行时数据是否提交）。
    import json as _json
    _CHAR_STUBS = {
        "linwan": {"id": "linwan", "name": "林婉", "description": "高冷、嘴硬、偶尔温柔",
                   "personality": "高冷", "system_prompt": "你叫林婉。高冷女生，说话简短。", "avatar": ""},
        "maid": {"id": "maid", "name": "小羽", "description": "温柔女仆",
                 "personality": "温柔", "system_prompt": "你叫小羽。温柔女仆。", "avatar": ""},
        "xiaomei": {"id": "xiaomei", "name": "小梅", "description": "傲娇毒舌",
                    "personality": "傲娇", "system_prompt": "你叫小梅。傲娇。", "avatar": ""},
    }
    for cid, stub in _CHAR_STUBS.items():
        cf = data / "characters" / f"{cid}.json"
        if not cf.exists():
            cf.write_text(_json.dumps(stub, ensure_ascii=False), encoding="utf-8")

    _WORLD_STUBS = {
        "campus": {"id": "campus", "name": "校园", "description": "大学校园日常",
                   "background": "大学校园日常。", "world_event": {"title": "期末考试周", "impact": -20}},
        "cyberpunk": {"id": "cyberpunk", "name": "赛博朋克", "description": "霓虹都市 2099",
                      "background": "赛博朋克世界。", "world_event": {"title": "企业战争", "impact": -10}},
    }
    for wid, stub in _WORLD_STUBS.items():
        wf = data / "worlds" / f"{wid}.json"
        if not wf.exists():
            wf.write_text(_json.dumps(stub, ensure_ascii=False), encoding="utf-8")

    return tmp_path


@pytest.fixture(scope="session")
def fake_deepseek():
    """用一个 FakeDeepSeek 实例替换所有 agent 模块 + api.api 的 client（整会话一次）。"""
    import importlib
    fake = FakeDeepSeek()
    mp = pytest.MonkeyPatch()

    for mod_name in _AGENT_MODULES:
        try:
            mod = importlib.import_module(mod_name)
        except Exception:
            continue
        if hasattr(mod, "client"):
            mp.setattr(mod, "client", fake)

    # api.api 有自己的 client（主回复用）
    try:
        import api.api as _api
        if hasattr(_api, "client"):
            mp.setattr(_api, "client", fake)
    except Exception:
        pass

    yield fake
    mp.undo()


@pytest.fixture(scope="session")
def disable_rag():
    """绕开 ChromaDB / fastembed：把 memory_rag 读写全 mock 成空/no-op（整会话一次）。

    这样 load_memory → _migrate_to_chroma / get_long_memories / get_events /
    get_chat_summary 都不碰向量库，集成测试不依赖 chroma 进程或模型下载。
    """
    from funcation import memory_rag, recall_agent
    mp = pytest.MonkeyPatch()

    mp.setattr(memory_rag, "retrieve_memories", lambda *a, **k: [])
    mp.setattr(memory_rag, "list_all_memories", lambda *a, **k: [])
    mp.setattr(memory_rag, "add_memory", lambda *a, **k: None)
    mp.setattr(memory_rag, "update_memory", lambda *a, **k: None)
    mp.setattr(memory_rag, "delete_memory", lambda *a, **k: None)
    # recall_agent.detect_memory_scope 是 LLM 调用，直接返回空集合
    mp.setattr(recall_agent, "detect_memory_scope", lambda *a, **k: [])
    # 兜底：peek_cached_scope 也可能被调到（/chat/stream），返回空
    if hasattr(recall_agent, "peek_cached_scope"):
        mp.setattr(recall_agent, "peek_cached_scope",
                   lambda *a, **k: {"scope": [], "source": "test"})

    yield
    mp.undo()


@pytest.fixture(scope="session")
def client(fake_deepseek, disable_rag):
    """FastAPI TestClient（session 级，整会话一个 lifespan）。

    数据隔离靠 tmp_data_dir 的 chdir（function 级），不靠重新建 TestClient。
    """
    from fastapi.testclient import TestClient
    from api.api import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def admin_token(client):
    """admin 默认账 admin/admin123（_ensure_admin 种入），整会话登录一次。"""
    r = client.post("/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


# 便利组合：MemoryCenter 纯逻辑测试用（不经过 TestClient）
@pytest.fixture
def mc(tmp_data_dir, disable_rag):
    from funcation.memory_center import MemoryCenter
    return MemoryCenter()
