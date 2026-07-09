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

import hashlib
import logging
import os
import shutil
import time
import uuid

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

# ============================================================
# 模块级单例
# ============================================================

_chroma_client = None
# 当原 PERSIST_DIR 无法删除时（Windows 文件锁），切到备用目录
_chroma_persist_dir: str | None = None
# 标记本次进程是否已执行过一次自动重建（避免无限循环重建）
_auto_rebuilt = False


def _quarantine_corrupt_dir(reason: str) -> None:
    """把损坏的持久化目录改名隔离（加时间戳防覆盖），为重建腾出位置。

    Windows 上常有进程锁导致 move/rmtree 失败；此时用备用目录名重建，
    原损坏目录留待下次启动手工清理。
    """
    global _chroma_client, _chroma_persist_dir
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

    若持久化数据损坏（如 tenant 元数据坏），自动隔离损坏目录并重建空库，
    而不是直接抛 500。每个进程最多重建一次，避免无限循环。
    """
    global _chroma_client, _auto_rebuilt
    if _chroma_client is not None:
        return _chroma_client

    try:
        _chroma_client = _create_client()
    except Exception as exc:
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
        msg = str(exc).lower()
        # 仅对 tenant / 连接类损坏触发重建，业务错误（如参数错）不重建
        if _auto_rebuilt or "tenant" not in msg and "connect" not in msg:
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


def retrieve_memories(
    user_id: int,
    character_id: str,
    query: str,
    top_k: int = 5,
    world_id: str | None = None,
    collections: list[str] | None = None,
) -> list[dict]:
    """跨指定集合检索，合并排序后返回 top_k 结果。"""
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
            world_id=world_id,
        )

        for item in items:
            item["weighted_score"] = item["score"]
            item["weight"] = 1.0

        all_items.extend(items)

    all_items.sort(key=lambda x: x["score"])

    print(f"\n====== RAG RETRIEVE u={user_id} c={character_id} ({len(collections)} collections) ======")
    for item in all_items[:top_k]:
        print(f"  [{item['collection']}] score={item['score']:.4f} | {item['text'][:60]}")
    print("==========================\n")

    return all_items[:top_k]


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
