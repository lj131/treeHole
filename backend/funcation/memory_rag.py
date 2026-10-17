"""
Memory RAG — 长期记忆向量检索系统

基于 ChromaDB 实现，6 个独立集合按角色隔离：
- profile: 用户画像
- long_memory: 长期记忆
- story: 剧情记录
- events: 世界/角色事件
- relationship: 关系变化
- chat_summary: 聊天摘要

持久化目录: data/chroma/
"""
from __future__ import annotations

import glob
import hashlib
import logging
import os
import shutil
import sqlite3
import time
import traceback
import uuid
from datetime import datetime, timezone

import chromadb
from chromadb.config import Settings
from pathlib import Path
from funcation.embedding_manager import get_embedding_function

logger = logging.getLogger(__name__)

# ============================================================
# 常量
# ============================================================

# PERSIST_DIR = os.path.join("data", "chroma")
BASE_DIR = Path(__file__).resolve().parent.parent

PERSIST_DIR = str(BASE_DIR / "data" / "chroma")
COLLECTION_TYPES = [
    "profile",
    "long_memory",
    "story",
    "events",
    "relationship",
    "chat_summary",
]

COLLECTION_LABELS = {
    "profile": "用户信息",
    "long_memory": "长期记忆",
    "story": "剧情",
    "events": "事件",
    "relationship": "关系",
    "chat_summary": "聊天摘要",
}

COLLECTION_WEIGHTS = {

    "profile": 0.4,

    "relationship": 0.6,

    "long_memory": 0.8,

    "story": 1.0,

    "events": 1.1,

    "chat_summary": 1.2
}

#: 跨集合检索时，每个集合**至少**保留几条。
#: 没有它，文档多的集合（story 常有 10+ 条）会占满 top_k，
#: 让"用户说过的事实"（long_memory）或"你们的事"（events）永远召不到。
#: 见 `fair_top_k()`。
FAIR_MIN_PER_COLLECTION = 2

#: **文档带 `world_id` 元数据的集合** —— 只有它们能按世界过滤。
#:
#: ⚠️ 2026-10-17 修：`long_memory` / `events` / `chat_summary` 的文档
#: 是 `rebuild_collection_from_items()` 全量重建的，metadata 只有
#: `{user_id, character_id}`，**没有 `world_id`**（而
#: `_sync_profile/story/relationship_to_rag` 写的三个集合有）。
#: 于是 `/chat/stream` 带 `world_id` 查询时，这三个集合**一条都查不到** ——
#: 长期记忆/事件/聊天摘要在真实对话里从未进过 prompt。
#:
#: 修在查询侧而不是补齐写入元数据：这三类的本质是"用户与角色之间的事"，
#: **没有世界属性**（用户在哪个世界聊天，说过的话就是说过的话）。
#: 补齐元数据反而会在用户切换世界后失效。
_WORLD_SCOPED_COLLECTIONS = frozenset({"profile", "story", "relationship"})


def applies_world_filter(collection_type: str) -> bool:
    """这个集合的文档带 `world_id` 元数据吗（决定能否按世界过滤）。

    纯函数，方便单测 —— 写错这两个集合名单的后果很严重
    （要么查不到记忆，要么跨世界串数据）。
    """
    return str(collection_type or "") in _WORLD_SCOPED_COLLECTIONS


# ============================================================
# 模块级单例
# ============================================================

_chroma_client = None
# 当原 PERSIST_DIR 无法删除时（Windows 文件锁），切到备用目录
_chroma_persist_dir: str | None = None
# 标记本次进程是否已执行过一次自动重建（避免无限循环重建）
_auto_rebuilt = False

# ---------------------------------------------------------------------------
# 隔离事件记录
#
# **隔离 = 数据丢失**，所以每次隔离判定都必须可查。之前只有一行 logger.warning，
# 既没有堆栈也没有计数 —— 结果 6 个库被误隔离、记忆被丢了好几个月都没人发现。
# ---------------------------------------------------------------------------
_quarantine_events: list[dict] = []
_QUARANTINE_EVENT_LIMIT = 50

# 网络 / IO 类异常：这些是**外部依赖**的问题，与向量库里的数据无关，绝不触发隔离。
#
# 实测教训（2026-10-12）：FastEmbed 在构造 embedding function 时会访问 huggingface.co，
# 本机代理返回 502 → 抛 httpx.ProxyError（代理不可达时抛 httpx.ConnectError），
# 一路冒泡进隔离分支，把**健康**的库整个 move 走。事后 6 个隔离库全部
# integrity_check=ok 且能被 chromadb 正常打开 —— 它们从来没坏过。
_NETWORK_ERROR_TYPES: tuple[type[BaseException], ...] = (
    ConnectionError,
    TimeoutError,
    OSError,
)
try:  # httpx 是 chromadb 的传递依赖；拿不到就退回上面三种，不影响正确性
    import httpx as _httpx

    _NETWORK_ERROR_TYPES = (*_NETWORK_ERROR_TYPES, _httpx.HTTPError)
except ImportError:  # pragma: no cover - 依赖缺失时仍可运行
    _httpx = None  # type: ignore[assignment]

# 真正指向「向量库自身坏了」的异常，按**异常类型的模块**识别（不是消息文本）
_CORRUPTION_MODULE_HINTS = ("chromadb", "sqlite3")


def is_corruption_error(exc: BaseException) -> bool:
    """这个异常是否**真的指向向量库损坏**。

    规则（保守优先：宁可漏判让调用方重试，也不误删数据）：
    - 网络 / IO 类 → False（外部依赖问题，重试即可）
    - 异常来自 chromadb / sqlite3 → True
    - 其余 → False

    **刻意不看 `str(exc)`**。旧代码用 `"connect" in msg` 判定，而这个子串
    在英文 locale 的 `ConnectError` 消息里出现、在中文 locale 的「无法连接」里不出现 ——
    同一份代码在不同部署环境下行为不同，是最难查的一类 bug。
    """
    if isinstance(exc, _NETWORK_ERROR_TYPES):
        return False
    module = getattr(type(exc), "__module__", "") or ""
    return any(hint in module for hint in _CORRUPTION_MODULE_HINTS)


def record_quarantine_event(reason: str, *, quarantined: bool, note: str = "") -> None:
    """记录一次隔离判定（无论最终是否真的隔离了）"""
    event = {
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "reason": reason,
        "quarantined": quarantined,
        "note": note,
        "traceback": traceback.format_exc(),
    }
    _quarantine_events.append(event)
    if len(_quarantine_events) > _QUARANTINE_EVENT_LIMIT:
        del _quarantine_events[:-_QUARANTINE_EVENT_LIMIT]

    if quarantined:
        logger.error(
            "[memory_rag] **向量库已被隔离（数据丢失）** 原因: %s | 位置: %s",
            reason, note or "(见上方日志)",
        )
    else:
        logger.warning("[memory_rag] 隔离请求被拒绝，未丢数据 —— 原因: %s", reason)


def get_quarantine_events() -> list[dict]:
    return list(_quarantine_events)


def is_persist_dir_healthy(persist_dir: str | None = None) -> bool:
    """持久化目录是不是**健康可用**的。

    隔离是不可逆的数据丢失，所以隔离前必须先问一句"它真的坏了吗"。

    判定规则（**宁可判健康**，绝不误删）：
    - 目录不存在 → True（还没建库，不算损坏）
    - 没有 chroma.sqlite3 → True（chroma 会自建）
    - sqlite 能只读打开且 `PRAGMA integrity_check` = ok → True
    - **打不开**（被占用 / 权限 / 环境问题）→ True（判不出来就别删）
    - sqlite **明确说这不是一个数据库 / 镜像损坏** → False
    """
    target = persist_dir or _chroma_persist_dir or PERSIST_DIR
    if not os.path.isdir(target):
        return True

    db_file = os.path.join(target, "chroma.sqlite3")
    if not os.path.isfile(db_file):
        return True

    try:
        con = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
    except sqlite3.OperationalError as e:
        # 打不开 = 文件被占用/权限不足/路径异常 —— 这是**环境**问题，不是数据坏了。
        # 这种情况删了就是白丢数据，所以按健康处理。
        logger.warning(
            "[memory_rag] 无法打开 %s 做健康探测（按健康处理以免误删）: %s", db_file, e
        )
        return True

    try:
        row = con.execute("PRAGMA integrity_check").fetchone()
        return bool(row) and str(row[0]).lower() == "ok"
    except sqlite3.DatabaseError as e:
        # sqlite 明确报 "file is not a database" / "database disk image is malformed"
        # —— 这才是真的坏了
        logger.warning("[memory_rag] %s 确认损坏: %s", db_file, e)
        return False
    except (Exception, SystemExit) as e:  # noqa: BLE001 - 其它意外一律按健康处理
        logger.warning(
            "[memory_rag] 健康探测无法完成（%s），按健康处理以免误删: %s", db_file, e
        )
        return True
    finally:
        try:
            con.close()
        except (Exception, SystemExit):  # noqa: BLE001
            pass


def health_snapshot() -> dict:
    """给 /health 用的 RAG 状态快照"""
    target = _chroma_persist_dir or PERSIST_DIR
    return {
        "persist_dir": target,
        "using_alt_dir": bool(_chroma_persist_dir),
        "quarantine_count": sum(1 for e in _quarantine_events if e["quarantined"]),
        "rejected_count": sum(1 for e in _quarantine_events if not e["quarantined"]),
        "healthy": is_persist_dir_healthy(target),
        "last_event": _quarantine_events[-1] if _quarantine_events else None,
    }


def try_restore_quarantined_dir() -> bool:
    """当前库不可用时，尝试从最近的**健康**隔离库里恢复数据。

    隔离目录里躺着的往往不是坏数据 —— 实测 6 个隔离库全部完好（12 个集合、15 条记录）。
    恢复成功就省掉一次"记忆全丢、等用户重新聊出来"的事故。
    """
    target = _chroma_persist_dir or PERSIST_DIR

    # 当前库本来就健康且已经有数据 → 别去动隔离目录
    if os.path.isdir(target) and is_persist_dir_healthy(target):
        if os.path.isfile(os.path.join(target, "chroma.sqlite3")):
            return False

    for cand in sorted(glob.glob(f"{PERSIST_DIR}_corrupt_*"), reverse=True):
        if not is_persist_dir_healthy(cand):
            continue
        try:
            if os.path.isdir(target):
                shutil.rmtree(target, ignore_errors=True)
            shutil.move(cand, target)
            logger.warning("[memory_rag] 已从隔离目录恢复向量库: %s -> %s", cand, target)
            record_quarantine_event(f"restored from {cand}", quarantined=False, note="恢复成功")
            return True
        except (Exception, SystemExit) as e:  # noqa: BLE001 - 恢复失败不影响启动
            logger.warning("[memory_rag] 从 %s 恢复失败: %s", cand, e)
    return False


def release_client() -> None:
    """释放持久化客户端（lifespan shutdown 调用）。

    chromadb 的 PersistentClient 通过 SharedSystemClient 持有 sqlite 句柄；
    进程被强杀时不释放，下一个进程打开同一目录就可能看到不一致状态
    （实测 5 次隔离都发生在反复启停之后）。显式释放能显著降低这个概率。
    """
    global _chroma_client
    _chroma_client = None
    try:
        from chromadb.api.shared_system_client import SharedSystemClient

        SharedSystemClient.clear_system_cache()
        logger.info("[memory_rag] 已释放 ChromaDB 客户端（sqlite 句柄已交还）")
    except (Exception, SystemExit) as e:  # noqa: BLE001 - 释放失败不该阻断关闭
        logger.warning("[memory_rag] 释放 chroma 客户端失败（忽略）: %s", e)


def _quarantine_corrupt_dir(reason: str) -> None:
    """把损坏的持久化目录改名隔离（加时间戳防覆盖），为重建腾出位置。

    **隔离前必须先过健康探测** —— 隔离是不可逆的数据丢失，判定错了就是真丢数据。
    探测显示库可用时直接拒绝隔离，让调用方去重试。

    Windows 上常有进程锁导致 move/rmtree 失败；此时用备用目录名重建，
    原损坏目录留待下次启动手工清理。
    """
    global _chroma_client, _chroma_persist_dir

    target = _chroma_persist_dir or PERSIST_DIR
    if is_persist_dir_healthy(target):
        logger.warning(
            "[memory_rag] 收到隔离请求（原因: %s），但健康探测显示 %s 可用 —— **拒绝隔离**。"
            "隔离会丢弃有效记忆，改由调用方重试。",
            reason, target,
        )
        record_quarantine_event(reason, quarantined=False, note="健康探测通过，拒绝隔离")
        return

    _chroma_client = None
    if not os.path.exists(PERSIST_DIR):
        return
    backup = f"{PERSIST_DIR}_corrupt_{int(time.time())}"
    try:
        shutil.move(PERSIST_DIR, backup)
        logger.warning(
            "[memory_rag] ChromaDB 目录已隔离到 %s（原因: %s）。将重建空库，"
            "long_memory/events/chat_summary 等仅存向量库的数据会丢失，"
            "profile/story/relationship 会在下次 /chat 时从 JSON 重新同步。",
            backup, reason,
        )
        record_quarantine_event(reason, quarantined=True, note=backup)
    except Exception as move_err:
        # 移动失败（Windows 上常有文件被占用），先尝试逐个文件删除
        logger.error("[memory_rag] move 失败: %s，尝试逐文件清空", move_err)
        _rmtree_robust(PERSIST_DIR)
        # 目录仍然存在（有残余锁文件）→ 切到备用目录名重建
        if os.path.exists(PERSIST_DIR):
            alt = f"{PERSIST_DIR}_new"
            logger.warning(
                "[memory_rag] 原目录 %s 无法完全删除（文件被占用），"
                "将使用备用目录 %s 重建。原目录可稍后手动删除。",
                PERSIST_DIR, alt,
            )
            _chroma_persist_dir = alt
            os.makedirs(_chroma_persist_dir, exist_ok=True)
            record_quarantine_event(reason, quarantined=True, note=alt)


def _rmtree_robust(dir_path: str) -> None:
    """尽量删除目录：先逐个删文件（跳过锁定的），再 rmtree 收尾。"""
    for root, dirs, files in os.walk(dir_path, topdown=False):
        for name in files:
            try:
                os.unlink(os.path.join(root, name))
            except OSError:
                pass
        for name in dirs:
            try:
                os.rmdir(os.path.join(root, name))
            except OSError:
                pass
    try:
        shutil.rmtree(dir_path, ignore_errors=True)
    except Exception:
        pass


def _create_client():
    """实际创建 PersistentClient。损坏时由调用方决定是否重建。
    若 _quarantine_corrupt_dir 已将目录切到备用路径，则使用备用路径。"""
    global _chroma_persist_dir
    persist = _chroma_persist_dir or PERSIST_DIR
    os.makedirs(persist, exist_ok=True)
    return chromadb.PersistentClient(
        path=persist,
        settings=Settings(anonymized_telemetry=False),
    )


def _get_client() -> chromadb.PersistentClient:
    """返回持久化 ChromaDB 客户端单例。

    若持久化数据**确实损坏**（如 tenant 元数据坏），隔离损坏目录并重建空库，
    而不是直接抛 500。每个进程最多重建一次，避免无限循环。

    **但外部依赖故障（网络/代理/磁盘）不算损坏** —— 那种情况只重试，绝不动数据。
    实测踩过：FastEmbed 访问 huggingface.co 被代理拦成 502，异常一路冒泡到这里，
    旧代码的 `except Exception` 一律当成"初始化失败"把健康库隔离掉了。
    """
    global _chroma_client, _auto_rebuilt
    if _chroma_client is not None:
        return _chroma_client

    # 当前库不可用、而隔离目录里有健康数据 → 先恢复，别重建空库
    try:
        try_restore_quarantined_dir()
    except (Exception, SystemExit) as e:  # noqa: BLE001 - 恢复失败不影响正常启动
        logger.warning("[memory_rag] 隔离目录恢复检查失败（忽略）: %s", e)

    try:
        _chroma_client = _create_client()
    except Exception as exc:
        if not is_corruption_error(exc):
            # 外部依赖故障：重试一次即可，**绝不隔离**
            logger.warning(
                "[memory_rag] ChromaDB 初始化遇到外部故障（非数据损坏），重试一次: %s", exc
            )
            record_quarantine_event(
                f"init non-corruption error: {exc}", quarantined=False, note="外部故障，重试"
            )
            _chroma_client = _create_client()
            logger.info("Chroma Path: %s", _chroma_persist_dir or PERSIST_DIR)
            return _chroma_client

        # 若其他并发请求已经重建过，直接重试创建（不重复隔离）
        if _auto_rebuilt:
            logger.warning("[memory_rag] 已有重建发生过，再次尝试: %s", exc)
            try:
                _quarantine_corrupt_dir(f"retry error: {exc}")
                _chroma_client = _create_client()
            except Exception as exc2:
                logger.error("[memory_rag] 重建失败，放弃: %s", exc2)
                raise
            return _chroma_client
        logger.warning("[memory_rag] ChromaDB 初始化失败，尝试自动重建: %s", exc)
        _auto_rebuilt = True
        _quarantine_corrupt_dir(f"init error: {exc}")
        _chroma_client = _create_client()

    logger.info("Chroma Path: %s", _chroma_persist_dir or PERSIST_DIR)
    return _chroma_client


# ============================================================
# 集合管理
# ============================================================


# 旧集合名 → 新集合名 的懒迁移：admin (user_id=1) 的旧集合自动改名
_LEGACY_ADMIN_USER_ID = 1


def _collection_name(user_id: int, character_id: str, collection_type: str) -> str:
    """新集合命名：u{user_id}_{character_id}_{collection_type}"""
    return f"u{user_id}_{character_id}_{collection_type}"


def _try_migrate_legacy_collection(
    client, user_id: int, character_id: str, collection_type: str
) -> bool:
    """如果旧集合 {character_id}_{collection_type} 存在 + user_id 是 admin，
    把它改名为新格式。返回是否做了迁移。"""
    if user_id != _LEGACY_ADMIN_USER_ID:
        return False
    legacy_name = f"{character_id}_{collection_type}"
    new_name = _collection_name(user_id, character_id, collection_type)
    try:
        existing = {c.name for c in client.list_collections()}
        if legacy_name in existing and new_name not in existing:
            legacy = client.get_collection(name=legacy_name)
            legacy.modify(name=new_name)
            logger.info("[memory_rag] 旧集合 %s → %s", legacy_name, new_name)
            return True
    except Exception as exc:
        logger.warning("[memory_rag] 旧集合迁移失败 %s: %s", legacy_name, exc)
    return False


def _get_collection(user_id: int, character_id: str, collection_type: str):
    """
    获取指定用户、角色和类型的 ChromaDB 集合（懒创建 + 旧集合懒迁移）。

    集合命名: u{user_id}_{character_id}_{collection_type}
    若 user_id=admin 且旧名 {character_id}_{collection_type} 存在，自动改名。
    """
    if collection_type not in COLLECTION_TYPES:
        raise ValueError(
            f"不支持的集合类型: {collection_type}。支持: {COLLECTION_TYPES}"
        )

    collection_name = _collection_name(user_id, character_id, collection_type)
    ef = get_embedding_function()

    def _build(client):
        # 在创建前尝试懒迁移旧集合
        _try_migrate_legacy_collection(client, user_id, character_id, collection_type)
        return client.get_or_create_collection(
            name=collection_name,
            embedding_function=ef,
            metadata={
                "user_id": user_id,
                "character_id": character_id,
                "type": collection_type,
            },
        )

    try:
        return _build(_get_client())
    except Exception as exc:
        global _auto_rebuilt
        # **按异常类型判断，不看消息文本**。
        # 旧代码是 `"tenant" not in msg and "connect" not in msg` —— 那个 "connect"
        # 本意是匹配 chroma 的 "Could not connect to tenant"，但也会命中
        # httpx.ConnectError（FastEmbed 访问 huggingface.co 失败），
        # 于是网络抖动就把健康的向量库整个隔离掉。
        if _auto_rebuilt or not is_corruption_error(exc):
            raise
        logger.warning(
            "[memory_rag] 集合操作检测到损坏，自动重建: %s", exc
        )
        _auto_rebuilt = True
        _quarantine_corrupt_dir(f"runtime error: {exc}")
        return _build(_get_client())


# ============================================================
# CRUD 操作
# ============================================================


def rebuild_collection_from_items(
    user_id: int,
    character_id: str,
    collection_type: str,
    items: list,
) -> int:
    """用**真源里的条目**全量重建一个集合的索引。返回索引条数。

    ## 为什么要有这个

    向量库是**派生索引**，不是存储（见 `memory_center` 模块 docstring 的真源划分）。
    它随时可能被清空 / 隔离 / 损坏，这时只要真源还在就能重建。
    在 2026-10-14 之前 `long_memory`/`events`/`chat_summary` 只有向量库一份，
    隔离一次就等于静默丢数据 —— 这个函数就是那次的产物。

    ## items 的两种形态

    - `list[str]`（long_memory / chat_summary）
    - `list[{time, event}]`（events）—— `time` 会写进 metadata

    会先 `purge_collection` 再全量写。调用方保证 items 是完整的真源内容。
    """
    if collection_type not in COLLECTION_TYPES:
        raise ValueError(
            f"不支持的集合类型: {collection_type}。支持: {COLLECTION_TYPES}"
        )

    purge_collection(user_id, character_id, collection_type)

    texts: list[str] = []
    metas: list[dict] = []
    for item in items or []:
        if isinstance(item, str):
            if item:
                texts.append(item)
                metas.append({})
        elif isinstance(item, dict):
            text = item.get("event") or item.get("text") or ""
            if text:
                texts.append(str(text))
                metas.append({"time": item.get("time", "")})

    if not texts:
        return 0

    collection = _get_collection(user_id, character_id, collection_type)
    ids = [str(uuid.uuid4()) for _ in texts]
    for m in metas:
        m.setdefault("user_id", user_id)
        m.setdefault("character_id", character_id)
    collection.add(ids=ids, documents=texts, metadatas=metas)
    return len(texts)


def add_memory(
    user_id: int,
    character_id: str,
    collection_type: str,
    text: str,
    metadata: dict | None = None,
) -> str:
    """添加一条记忆到向量库。返回 doc_id"""
    collection = _get_collection(user_id, character_id, collection_type)
    meta = metadata or {}
    meta.setdefault("user_id", user_id)
    meta.setdefault("character_id", character_id)

    doc_id = str(uuid.uuid4())
    collection.add(
        ids=[doc_id],
        documents=[text],
        metadatas=[meta],
    )
    return doc_id


def upsert_memory(
    user_id: int,
    character_id: str,
    collection_type: str,
    text: str,
    doc_id: str,
    metadata: dict | None = None,
) -> str:
    """插入或更新一条记忆（相同 doc_id 会覆盖）。返回 doc_id"""
    collection = _get_collection(user_id, character_id, collection_type)
    meta = metadata or {}
    meta.setdefault("user_id", user_id)
    meta.setdefault("character_id", character_id)

    collection.upsert(
        ids=[doc_id],
        documents=[text],
        metadatas=[meta],
    )
    return doc_id


def update_memory(
    user_id: int,
    character_id: str,
    collection_type: str,
    old_text: str,
    new_text: str,
    metadata: dict | None = None,
) -> str | None:
    """更新一条记忆：相似度定位旧文档 → 删除 → 插入新文档。"""
    collection = _get_collection(user_id, character_id, collection_type)

    try:
        results = collection.query(
            query_texts=[old_text],
            n_results=3,
            include=["documents", "metadatas"],
        )
    except Exception:
        return None

    if not results["ids"] or not results["ids"][0]:
        return None

    old_id = None
    for i, doc in enumerate(results["documents"][0]):
        if doc.strip() == old_text.strip():
            old_id = results["ids"][0][i]
            break

    if old_id:
        collection.delete(ids=[old_id])

    return add_memory(user_id, character_id, collection_type, new_text, metadata)


def delete_memory(
    user_id: int,
    character_id: str,
    collection_type: str,
    text: str,
) -> bool:
    """从向量库删除一条记忆（按文本精确匹配）。"""
    collection = _get_collection(user_id, character_id, collection_type)

    try:
        results = collection.query(
            query_texts=[text],
            n_results=5,
            include=["documents"],
        )
    except Exception:
        return False

    if not results["ids"] or not results["ids"][0]:
        return False

    ids_to_delete = []
    for i, doc in enumerate(results["documents"][0]):
        if doc.strip() == text.strip():
            ids_to_delete.append(results["ids"][0][i])

    if ids_to_delete:
        collection.delete(ids=ids_to_delete)
        return True

    return False


# ============================================================
# 检索操作
# ============================================================


def _retrieve_single(
    user_id: int,
    character_id: str,
    collection_type: str,
    query: str,
    top_k: int = 3,
    world_id: str | None = None,
) -> list[dict]:
    """单个集合检索。"""
    collection = _get_collection(user_id, character_id, collection_type)

    where_filter = None
    if world_id:
        where_filter = {"world_id": world_id}

    try:
        results = collection.query(
            query_texts=[query],
            n_results=top_k,
            where=where_filter,
            include=["documents", "metadatas", "distances"],
        )
    except Exception as e:
        print(f"[memory_rag] 检索 {collection_type} 失败: {e}")
        return []

    if not results["ids"] or not results["ids"][0]:
        return []

    items = []
    for i, doc_id in enumerate(results["ids"][0]):
        distance = (
            results["distances"][0][i]
            if results.get("distances")
            else 1.0
        )
        metadata = (
            results["metadatas"][0][i]
            if results.get("metadatas")
            else {}
        )
        weight = COLLECTION_WEIGHTS.get(collection_type, 1.0)
        weighted_score = distance * weight

        items.append({
            "text": results["documents"][0][i],
            "collection": collection_type,
            "score": round(distance, 4),
            "weighted_score": round(weighted_score, 4),
            "metadata": metadata,
        })

    items.sort(key=lambda x: x["score"])
    return items


def fair_top_k(
    items: list[dict],
    *,
    top_k: int,
    min_per_collection: int = 2,
) -> list[dict]:
    """跨集合合并结果后取 top_k，但**保证每个集合有最低代表数**。

    为什么要它：原来是 `all_items.sort(...)[:top_k]`，**文档多的集合会垄断席位**。
    实测：`story` 有 10+ 条文档，当 query 关键词和它重合时（如问"校庆筹备委员会"），
    10 条 story 的 distance 都明显小于 `long_memory` 的 2 条，于是**占满 top_k=10**，
    long_memory 被整个挤掉 —— 结果是"角色用不上用户说过的事实"。

    策略（两步）：
    1. 全局按分数排序后，**先给每个集合保底** `min_per_collection` 条
    2. 剩余名额按全局顺序补齐

    ⚠️ 最后**重新按全局分数排序** —— 保底 + 补齐会打乱顺序，
    而调用方（prompt 构建）期望"返回的就是相关性顺序"。

    `min_per_collection` 会按集合数收敛：top_k 太小时不至于全被保底占满。
    """
    if top_k <= 0 or not items:
        return []

    collection_count = len({it.get("collection", "") for it in items}) or 1
    # 保底太多会让 top_k 全被保底占满 → 按集合数收敛（至少 1）
    floor = max(1, min(min_per_collection, top_k // collection_count or 1))

    def score_of(it: dict):
        s = it.get("score")
        return s if isinstance(s, (int, float)) else float("inf")

    ordered = sorted(items, key=score_of)

    picked: list[dict] = []
    picked_ids: set[int] = set()
    per_collection: dict[str, int] = {}

    # 第一轮：保底
    for it in ordered:
        if len(picked) >= top_k:
            break
        coll = it.get("collection", "")
        if per_collection.get(coll, 0) < floor:
            picked.append(it)
            picked_ids.add(id(it))
            per_collection[coll] = per_collection.get(coll, 0) + 1

    # 第二轮：补齐
    for it in ordered:
        if len(picked) >= top_k:
            break
        if id(it) in picked_ids:
            continue
        picked.append(it)
        picked_ids.add(id(it))

    # 恢复全局相关性顺序
    picked.sort(key=score_of)
    return picked


def retrieve_memories(
    user_id: int,
    character_id: str,
    query: str,
    top_k: int = 5,
    world_id: str | None = None,
    collections: list[str] | None = None,
) -> list[dict]:
    """跨指定集合检索，合并后返回 top_k 结果。

    **集合间公平**：见 `fair_top_k` —— 文档多的集合不垄断席位，
    每个保底 `FAIR_MIN_PER_COLLECTION` 条。否则用户说过的事实可能永远召不到。
    """
    if collections is None:
        collections = COLLECTION_TYPES

    all_items = []
    per_collection_k = max(top_k, 3)

    for ctype in collections:
        if ctype not in COLLECTION_TYPES:
            continue

        items = _retrieve_single(
            user_id=user_id,
            character_id=character_id,
            collection_type=ctype,
            query=query,
            top_k=per_collection_k,
            # ⚠️ 只对**带 world_id 元数据**的集合按世界过滤 ——
            # long_memory/events/chat_summary 的 metadata 里没有 world_id，
            # 带过滤会一条都查不到（2026-10-17 修）。
            world_id=world_id if applies_world_filter(ctype) else None,
        )

        for item in items:
            item["weighted_score"] = item["score"]
            item["weight"] = 1.0

        all_items.extend(items)

    selected = fair_top_k(all_items, top_k=top_k, min_per_collection=FAIR_MIN_PER_COLLECTION)

    print(f"\n====== RAG RETRIEVE u={user_id} c={character_id} ({len(collections)} collections) ======")
    for item in selected:
        print(f"  [{item['collection']}] score={item['score']:.4f} | {item['text'][:60]}")
    print("==========================\n")

    return selected


def retrieve_profile(user_id, character_id: str, query: str, top_k: int = 3) -> list[dict]:
    return _retrieve_single(user_id, character_id, "profile", query, top_k=top_k)


def retrieve_story(user_id, character_id: str, query: str, top_k: int = 3) -> list[dict]:
    return _retrieve_single(user_id, character_id, "story", query, top_k=top_k)


def retrieve_events(user_id, character_id: str, query: str, top_k: int = 3) -> list[dict]:
    return _retrieve_single(user_id, character_id, "events", query, top_k=top_k)


def retrieve_relationship(user_id, character_id: str, query: str, top_k: int = 3) -> list[dict]:
    return _retrieve_single(user_id, character_id, "relationship", query, top_k=top_k)


# ============================================================
# 全量读取
# ============================================================


def list_all_memories(
    user_id: int,
    character_id: str,
    collection_type: str,
    where_filter: dict | None = None,
    limit: int = 200,
) -> list[dict]:
    """列出集合中的所有文档（不进行语义检索）。"""
    collection = _get_collection(user_id, character_id, collection_type)
    try:
        results = collection.get(
            where=where_filter,
            limit=limit,
            include=["documents", "metadatas"],
        )
    except Exception:
        return []

    if not results["ids"]:
        return []

    items = []
    for i, doc_id in enumerate(results["ids"]):
        items.append({
            "id": doc_id,
            "text": results["documents"][i] if results["documents"] else "",
            "metadata": results["metadatas"][i] if results["metadatas"] else {},
        })
    return items


def delete_by_id(
    user_id: int,
    character_id: str,
    collection_type: str,
    doc_id: str,
) -> bool:
    """按 doc_id 删除文档"""
    collection = _get_collection(user_id, character_id, collection_type)
    try:
        collection.delete(ids=[doc_id])
        return True
    except Exception:
        return False


# ============================================================
# 统计
# ============================================================


def get_collection_stats(user_id: int, character_id: str) -> dict[str, int]:
    """返回各集合文档数量"""
    stats = {}
    for ctype in COLLECTION_TYPES:
        try:
            collection = _get_collection(user_id, character_id, ctype)
            stats[ctype] = collection.count()
        except Exception:
            stats[ctype] = 0
    return stats


# ============================================================
# 工具
# ============================================================


def purge_character(user_id: int, character_id: str) -> dict[str, int]:
    """删除指定用户+角色的所有集合（用于重置 / 角色删除）"""
    client = _get_client()
    deleted = {}
    for ctype in COLLECTION_TYPES:
        collection_name = _collection_name(user_id, character_id, ctype)
        try:
            client.delete_collection(collection_name)
            deleted[ctype] = 1
        except Exception:
            deleted[ctype] = 0
    return deleted


def purge_collection(user_id: int, character_id: str, collection_type: str) -> int:
    """清空指定集合的所有文档，返回删除数量"""
    collection = _get_collection(user_id, character_id, collection_type)
    try:
        count = collection.count()
        all_ids = collection.get(limit=count, include=[])["ids"]
        if all_ids:
            collection.delete(ids=all_ids)
        return len(all_ids)
    except Exception:
        return 0
