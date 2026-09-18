"""语音包的落盘层（全局单份，管理员维护）。

存储布局（相对 cwd，与项目其它数据一致）：

```
data/voice_packs.json       # 全局语音包库 [{...}, ...]
data/voice_bindings.json    # 全局绑定 {"linwan": "vp_1a2b3c4d", ...}
data/voice_refs/<pack_id>.<ext>   # 参考音频
```

**为什么是全局而不是按用户**：语音包由管理员统一维护（见 API 层 `require_admin`），
角色本身也是全局共享的（内置角色所有人可见），所以"角色 → 语音包"的绑定同样全局。
好处是运行时解析（语音通话里合成 TTS）**不需要 user_id**，调用链一行都不用改。

本模块只做读写，不做校验（校验在 `voice_pack.py` 的纯函数里）。
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from .utils import remove_file_quietly

logger = logging.getLogger(__name__)

DATA_DIR = "data"
PACKS_FILE = os.path.join(DATA_DIR, "voice_packs.json")
BINDINGS_FILE = os.path.join(DATA_DIR, "voice_bindings.json")
REFS_DIR = os.path.join(DATA_DIR, "voice_refs")


def ensure_dirs() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(REFS_DIR, exist_ok=True)


def _load_json(path: str, default: Any) -> Any:
    """读 JSON；文件不存在 / 损坏都退回默认值（**不抛异常**）。

    配置文件被手改坏时，宁可让功能退回默认行为，也不能让整个服务起不来。
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        logger.warning("[voice_store] %s 读取失败，退回默认值: %s", path, e)
        return default


def _save_json(path: str, payload: Any) -> None:
    ensure_dirs()
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    # 原子替换：避免写一半崩掉留下半截 JSON
    os.replace(tmp, path)


# ── 语音包库 ──────────────────────────────────────────────────────────

def load_packs() -> List[Dict[str, Any]]:
    raw = _load_json(PACKS_FILE, [])
    if not isinstance(raw, list):
        logger.warning("[voice_store] voice_packs.json 不是数组，按空库处理")
        return []
    return [p for p in raw if isinstance(p, dict) and p.get("id")]


def save_packs(packs: List[Dict[str, Any]]) -> None:
    _save_json(PACKS_FILE, packs)


# ── 角色绑定 ──────────────────────────────────────────────────────────

def load_bindings() -> Dict[str, str]:
    raw = _load_json(BINDINGS_FILE, {})
    if not isinstance(raw, dict):
        logger.warning("[voice_store] voice_bindings.json 不是对象，按空绑定处理")
        return {}
    return {
        str(char_id): str(pack_id)
        for char_id, pack_id in raw.items()
        if isinstance(pack_id, str) and pack_id
    }


def save_bindings(bindings: Dict[str, str]) -> None:
    _save_json(BINDINGS_FILE, bindings)


def load_library() -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """一次读全（包库 + 绑定），运行时解析用"""
    return load_packs(), load_bindings()


# ── 参考音频 ──────────────────────────────────────────────────────────

def ref_path(pack_id: str, ext: str) -> str:
    """参考音频路径。`ext` 含点，如 `.wav`。"""
    ensure_dirs()
    return os.path.join(REFS_DIR, f"{os.path.basename(pack_id)}{ext}")


def find_existing_ref(pack_id: str) -> Optional[str]:
    """按 pack_id 找出已存在的参考音频（后缀未知，扫一遍目录）。

    换格式重传时要用它清掉旧文件，否则会同时留下 .wav 和 .mp3。
    """
    if not os.path.isdir(REFS_DIR):
        return None
    stem = os.path.basename(pack_id)
    for name in os.listdir(REFS_DIR):
        if name.startswith(f"{stem}.") and not name.endswith(".part"):
            return os.path.join(REFS_DIR, name)
    return None


def remove_ref(pack_id: str) -> bool:
    """删掉某语音包的参考音频（best-effort，失败不抛）"""
    existing = find_existing_ref(pack_id)
    if not existing:
        return True
    return remove_file_quietly(existing, "voice_ref")
