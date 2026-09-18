"""语音包（Voice Pack）—— 纯函数模块：schema / 校验 / clamp / 音色目录。

**什么是语音包**：一个角色可以用的一种"声音"。包里同时装两样东西：

1. **音色参数**（`engine` / `voice_name` / `speaking_rate` / `pitch` / `volume` / `style`）
   —— 现在 edge-tts 直接吃这些；
2. **参考音频**（`reference_audio` + `reference_text`）—— 给将来的音色克隆引擎用。

**为什么这样设计**：`engine` 字段决定用哪条推理链。现在只有 `edge`（云端、音色是固定名字、
不能克隆）。以后接本地克隆引擎（XTTS / CosyVoice / GPT-SoVITS）时，只要新增一个 engine 值
和一个适配器 —— 存储、接口、前端都不用动，参考音频早就存好了。

本模块**无 IO、无 FastAPI 依赖**，方便单测；落盘在 `voice_store.py`。
"""
from __future__ import annotations

import re
import secrets
from typing import Any, Dict, List, Optional

# ── 限额 ──────────────────────────────────────────────────────────────
# 参考音频只是给克隆引擎当"样本"，10 秒左右就够，没必要放开太大
VOICE_REF_MAX_MB = 10
MAX_PACKS = 30
NAME_MAX = 40
DESC_MAX = 200
REF_TEXT_MAX = 500
STYLE_MAX = 60

# 允许的参考音频格式（克隆引擎基本都吃 wav/mp3，其余是兼容）
ALLOWED_AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".webm", ".aac"}
ALLOWED_AUDIO_TYPES = {
    "audio/wav", "audio/x-wav", "audio/wave",
    "audio/mpeg", "audio/mp3",
    "audio/mp4", "audio/x-m4a", "audio/aac",
    "audio/ogg", "audio/flac", "audio/x-flac",
    "audio/webm",
}

# ── 参数范围 ──────────────────────────────────────────────────────────
# 与 edge-tts 的 rate/volume(+/-%) 与 pitch(+/-Hz) 对齐；给宽一点但不允许离谱值
RATE_MIN, RATE_MAX = 0.5, 2.0
PITCH_MIN, PITCH_MAX = -50.0, 50.0
VOLUME_MIN, VOLUME_MAX = 0.0, 2.0

# ── 引擎 ──────────────────────────────────────────────────────────────
# edge：云端固定音色，立刻可用
# clone：本地音色克隆，需要额外部署引擎（预留，选了会明确报"未安装"而不是静默降级）
SUPPORTED_ENGINES = ("edge", "clone")
DEFAULT_ENGINE = "edge"

# 未绑定语音包时回退用的音色（原来 voice_service 里写死的三行字典搬到这里）
LEGACY_CHARACTER_VOICES: Dict[str, str] = {
    "linwan": "zh-CN-XiaoxiaoNeural",
    "maid": "zh-CN-XiaoxueNeural",
    "xiaomei": "zh-CN-XiaomengNeural",
}
FALLBACK_VOICE = "zh-CN-XiaoxiaoNeural"

# ── 内置音色目录 ──────────────────────────────────────────────────────
# 静态表，不走网络（`edge_tts.list_voices()` 只在 /voice/voices 里用，失败了也能退回这张表）
VOICE_CATALOG: List[Dict[str, str]] = [
    {"short_name": "zh-CN-XiaoxiaoNeural", "label": "晓晓 · 女声 · 温柔", "gender": "Female"},
    {"short_name": "zh-CN-XiaoyiNeural", "label": "晓伊 · 女声 · 活泼", "gender": "Female"},
    {"short_name": "zh-CN-liaoning-XiaobeiNeural", "label": "晓北 · 女声 · 东北", "gender": "Female"},
    {"short_name": "zh-CN-shaanxi-XiaoniNeural", "label": "晓妮 · 女声 · 陕西", "gender": "Female"},
    {"short_name": "zh-CN-YunxiNeural", "label": "云希 · 男声 · 少年", "gender": "Male"},
    {"short_name": "zh-CN-YunyangNeural", "label": "云扬 · 男声 · 新闻", "gender": "Male"},
    {"short_name": "zh-CN-YunjianNeural", "label": "云健 · 男声 · 浑厚", "gender": "Male"},
    {"short_name": "zh-CN-YunxiaNeural", "label": "云夏 · 男声 · 童声", "gender": "Male"},
]

_PACK_ID_RE = re.compile(r"^vp_[0-9a-f]{8}$")
# 控制字符白名单式剔除：**保留 \t \n \r**，让它们走后面的空白折叠变成单个空格。
# 如果在这里直接删掉换行，多行描述会被粘成一句（"第一行第二行"）。
_UNSAFE_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# 文件名里不能出现的字符（Windows 更严），统一换成下划线
_UNSAFE_FILENAME_RE = re.compile(r'[\\/:*?"<>|\s]+')


class VoicePackError(ValueError):
    """语音包数据非法。API 层翻译成 400。"""


# ── 基础工具 ──────────────────────────────────────────────────────────

def new_pack_id() -> str:
    """生成语音包 ID（vp_ + 8 位十六进制）"""
    return f"vp_{secrets.token_hex(4)}"


def is_valid_pack_id(pack_id: Any) -> bool:
    return isinstance(pack_id, str) and bool(_PACK_ID_RE.match(pack_id))


def sanitize_text(raw: Any, *, max_len: int, field: str, required: bool = False) -> str:
    """去掉控制字符、压缩空白、截断超长。required=True 时不允许空串。"""
    if raw is None:
        raw = ""
    if not isinstance(raw, str):
        raise VoicePackError(f"{field} 必须是字符串")
    text = _UNSAFE_CHARS_RE.sub("", raw).strip()
    text = re.sub(r"\s+", " ", text)
    if len(text) > max_len:
        text = text[:max_len]
    if required and not text:
        raise VoicePackError(f"{field} 不能为空")
    return text


def sanitize_filename_stem(raw: Any, *, fallback: str = "voice") -> str:
    """把任意字符串变成安全的文件名主干（保留中文，去掉路径分隔符等）"""
    text = _UNSAFE_CHARS_RE.sub("", str(raw or ""))
    text = _UNSAFE_FILENAME_RE.sub("_", text).strip("._")
    return (text[:40] or fallback)


def clamp_float(value: Any, *, low: float, high: float, default: float, field: str) -> float:
    """数值 clamp：非法值（None / 非数字 / NaN / inf）一律回默认值"""
    if value is None:
        return default
    try:
        num = float(value)
    except (TypeError, ValueError):
        raise VoicePackError(f"{field} 必须是数字")
    if num != num or num in (float("inf"), float("-inf")):
        raise VoicePackError(f"{field} 不是有效数字")
    return max(low, min(high, num))


def is_valid_voice_name(name: Any) -> bool:
    """音色名必须形如 zh-CN-XiaoxiaoNeural（防注入，也防手抖填错）"""
    if not isinstance(name, str):
        return False
    return bool(re.match(r"^[a-zA-Z]{2,3}-[a-zA-Z]{2,4}-[A-Za-z0-9]{2,40}$", name.strip()))


def normalize_voice_name(name: Any) -> str:
    if not is_valid_voice_name(name):
        raise VoicePackError(f"音色名不合法：{name!r}（形如 zh-CN-XiaoxiaoNeural）")
    return str(name).strip()


def normalize_engine(engine: Any) -> str:
    if engine is None:
        return DEFAULT_ENGINE
    value = str(engine).strip().lower()
    if value not in SUPPORTED_ENGINES:
        raise VoicePackError(f"不支持的引擎：{engine!r}（可选：{'/'.join(SUPPORTED_ENGINES)}）")
    return value


def max_ref_bytes() -> int:
    return VOICE_REF_MAX_MB * 1024 * 1024


def ext_of(filename: Optional[str]) -> str:
    if not filename or "." not in filename:
        return ""
    return "." + filename.rsplit(".", 1)[-1].lower()


def validate_ref_upload(filename: Optional[str], content_type: Optional[str]) -> str:
    """校验参考音频的文件名后缀与 MIME，返回规范化后缀。"""
    ext = ext_of(filename)
    if ext not in ALLOWED_AUDIO_EXTS:
        raise VoicePackError(
            f"不支持的音频格式：{ext or '(无后缀)'}，仅支持 {'/'.join(sorted(ALLOWED_AUDIO_EXTS))}"
        )
    # 有些浏览器上传时 content_type 是 application/octet-stream，后缀对就放行
    if content_type and content_type != "application/octet-stream":
        if content_type not in ALLOWED_AUDIO_TYPES:
            raise VoicePackError(f"不支持的音频类型：{content_type}")
    return ext


# ── 语音包归一化 ──────────────────────────────────────────────────────

def normalize_pack(raw: Any, *, pack_id: Optional[str] = None, existing: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """把任意输入归一化成合法语音包。

    - `existing` 传入时做**局部更新**：没传的字段沿用旧值（PATCH 语义）；
    - 所有数值 clamp 到合法区间，坏数据抛 `VoicePackError` 而不是写进存储。
    """
    if not isinstance(raw, dict):
        raise VoicePackError("语音包必须是对象")
    base = dict(existing or {})

    pid = pack_id or base.get("id")
    if not is_valid_pack_id(pid):
        pid = new_pack_id()

    def pick(field: str, default: Any = None) -> Any:
        return raw[field] if field in raw else base.get(field, default)

    name = sanitize_text(pick("name"), max_len=NAME_MAX, field="名称", required=True)
    description = sanitize_text(pick("description"), max_len=DESC_MAX, field="描述")
    style = sanitize_text(pick("style"), max_len=STYLE_MAX, field="风格")

    engine = normalize_engine(pick("engine", DEFAULT_ENGINE))
    voice_name = normalize_voice_name(pick("voice_name", FALLBACK_VOICE))

    pack: Dict[str, Any] = {
        "id": pid,
        "name": name,
        "description": description,
        "engine": engine,
        "voice_name": voice_name,
        "speaking_rate": round(clamp_float(pick("speaking_rate", 1.0), low=RATE_MIN, high=RATE_MAX, default=1.0, field="语速"), 3),
        "pitch": round(clamp_float(pick("pitch", 0.0), low=PITCH_MIN, high=PITCH_MAX, default=0.0, field="音调"), 2),
        "volume": round(clamp_float(pick("volume", 1.0), low=VOLUME_MIN, high=VOLUME_MAX, default=1.0, field="音量"), 3),
        "style": style,
        # 参考**音频**由上传接口写入，普通更新只能保留已有值（走 base）；
        # 参考**文本**是普通文本字段，必须走 pick —— 否则创建时永远是空、更新时改不动。
        "reference_audio": base.get("reference_audio") or None,
        "reference_text": sanitize_text(pick("reference_text"), max_len=REF_TEXT_MAX, field="参考文本"),
        "created_at": base.get("created_at"),
        "updated_at": base.get("updated_at"),
    }
    return pack


def summarize_pack(pack: Dict[str, Any]) -> Dict[str, Any]:
    """列表用的摘要：带上"能不能用克隆"这类 UI 需要判断的信息。"""
    ref = pack.get("reference_audio")
    return {
        "id": pack.get("id"),
        "name": pack.get("name"),
        "description": pack.get("description"),
        "engine": pack.get("engine"),
        "voice_name": pack.get("voice_name"),
        "speaking_rate": pack.get("speaking_rate"),
        "pitch": pack.get("pitch"),
        "volume": pack.get("volume"),
        "style": pack.get("style"),
        "has_reference_audio": bool(ref),
        "reference_audio": ref,
        "reference_text": pack.get("reference_text") or "",
        "created_at": pack.get("created_at"),
        "updated_at": pack.get("updated_at"),
    }


def find_pack(packs: List[Dict[str, Any]], pack_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not pack_id:
        return None
    for pack in packs:
        if pack.get("id") == pack_id:
            return pack
    return None


def resolve_voice_config(
    *,
    character_id: str,
    packs: List[Dict[str, Any]],
    bindings: Dict[str, str],
) -> Dict[str, Any]:
    """解析某个角色最终该用哪套音色。

    解析链：**角色绑定的语音包 → 旧的按角色写死映射 → 全局兜底音色**。
    返回里带 `source`，方便接口/日志说清楚"这个声音是哪来的"。
    """
    pack = find_pack(packs, bindings.get(character_id))
    if pack:
        return {
            "engine": pack.get("engine") or DEFAULT_ENGINE,
            "voice_name": pack.get("voice_name") or FALLBACK_VOICE,
            "speaking_rate": pack.get("speaking_rate", 1.0),
            "pitch": pack.get("pitch", 0.0),
            "volume": pack.get("volume", 1.0),
            "style": pack.get("style") or "",
            "reference_audio": pack.get("reference_audio"),
            "reference_text": pack.get("reference_text") or "",
            "pack_id": pack.get("id"),
            "pack_name": pack.get("name"),
            "source": "pack",
        }

    legacy = LEGACY_CHARACTER_VOICES.get(character_id)
    if legacy:
        return {
            "engine": DEFAULT_ENGINE,
            "voice_name": legacy,
            "speaking_rate": 1.0,
            "pitch": 0.0,
            "volume": 1.0,
            "style": "",
            "reference_audio": None,
            "reference_text": "",
            "pack_id": None,
            "pack_name": None,
            "source": "legacy",
        }

    return {
        "engine": DEFAULT_ENGINE,
        "voice_name": FALLBACK_VOICE,
        "speaking_rate": 1.0,
        "pitch": 0.0,
        "volume": 1.0,
        "style": "",
        "reference_audio": None,
        "reference_text": "",
        "pack_id": None,
        "pack_name": None,
        "source": "default",
    }


def prune_bindings(bindings: Dict[str, str], packs: List[Dict[str, Any]]) -> Dict[str, str]:
    """删包之后把指向它的绑定一并清掉（避免留下悬空引用）"""
    valid_ids = {p.get("id") for p in packs}
    return {char_id: pid for char_id, pid in bindings.items() if pid in valid_ids}
