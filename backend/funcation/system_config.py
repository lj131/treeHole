"""系统配置 —— 让管理员在界面上改运行时配置，而不是「改 .env → 重启」。

**设计**

- **schema 驱动**：每个字段声明类型 / 范围 / 默认值 / 是否需重启，前端按 schema 渲染，
  不写死表单（加一个字段只需改这里）。
- **存储**：`data/system_config.json`，**只存被显式改过的键**。
  全量落盘会把默认值冻结下来 —— 以后改代码里的默认值就对老部署失效了。
- **优先级**：文件值 > 环境变量 > 代码默认值。所以**什么都不配时行为与改动前完全一致**。
- **绝不暴露密钥**：`JWT_SECRET_KEY`、`ADMIN_DEFAULT_PASSWORD`、各家 API key 都不进 schema ——
  在界面上改密钥是安全风险，也会让现有会话全部失效。有测试钉住这一点。

本模块**不 import 任何业务模块**（除了做音色名校验），避免循环依赖。
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DATA_DIR = "data"
CONFIG_FILE = os.path.join(DATA_DIR, "system_config.json")

# 文件缓存；测试会把它置 None 来强制重读
_cache: Optional[Dict[str, Any]] = None


class ConfigError(ValueError):
    """配置值非法。API 层翻译成 400。"""


@dataclass(frozen=True)
class ConfigField:
    """一个可配置项。前端按这些信息渲染控件。

    `default` 可以是值，也可以是**零参可调用对象**。
    后者用于「默认值本来就定义在别处」的情况（如 `model3d.DEFAULT_MAX_MODEL_MB`）——
    这样默认值只有一份真源，改那个常量这里跟着变，测试 monkeypatch 常量也仍然有效。
    """
    key: str
    label: str
    group: str
    kind: str                      # 'string' | 'int' | 'float'
    default: Any
    env: Optional[str] = None      # 环境变量名（作为默认值来源）
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    step: Optional[float] = None
    choices: tuple = ()            # 非空 = 下拉选择
    restart_required: bool = False
    hint: str = ""


def _const_default(module_name: str, attr: str, fallback: Any) -> Any:
    """惰性读取另一个模块里的常量作为默认值。

    必须是惰性的：`system_config` 被 `model3d` / `voice_pack` 反过来 import，
    模块导入期取常量会形成循环依赖。
    """
    def _get() -> Any:
        try:
            import importlib
            mod = importlib.import_module(f"funcation.{module_name}")
            return getattr(mod, attr)
        except (Exception, SystemExit):  # noqa: BLE001 - 拿不到就退回兜底值
            return fallback
    return _get


# ---------------------------------------------------------------------------
# 字段清单
#
# 加字段只需在这里加一行 —— 存储、接口、界面都跟着走。
# **不要把密钥类配置加进来**（见模块 docstring）。
# ---------------------------------------------------------------------------
FIELDS: List[ConfigField] = [
    # ---- 语音（TTS 全局默认）----
    ConfigField(
        "tts.voice_name", "默认音色", "语音（TTS）", "string",
        _const_default("voice_pack", "FALLBACK_VOICE", "zh-CN-XiaoxiaoNeural"),
        env="VOICE_NAME",
        hint="角色未绑定语音包时用它。角色绑定了包则以包为准。",
    ),
    ConfigField(
        "tts.speaking_rate", "语速", "语音（TTS）", "float",
        1.0, env="SPEAKING_RATE", minimum=0.5, maximum=2.0, step=0.05,
    ),
    ConfigField(
        "tts.pitch", "音调（Hz）", "语音（TTS）", "float",
        0.0, env="PITCH", minimum=-50.0, maximum=50.0, step=1.0,
        hint="实测部分中文音色会忽略音调；且非零音调更容易合成失败。",
    ),
    ConfigField(
        "tts.volume", "音量", "语音（TTS）", "float",
        1.0, env="VOLUME", minimum=0.0, maximum=2.0, step=0.05,
    ),

    # ---- 上传限额 ----
    ConfigField(
        "upload.model_max_mb", "3D 模型上限（MB）", "上传限额", "float",
        _const_default("model3d", "DEFAULT_MAX_MODEL_MB", 64),
        env="MODEL_MAX_MB", minimum=0.001, maximum=512, step=1,
        hint="保留小数是为了不改动既有 MODEL_MAX_MB 契约（原实现用 float() 解析，"
             "已有部署可能配了 0.001 这类值）。界面上按整数填即可。",
    ),
    ConfigField(
        "upload.voice_ref_max_mb", "参考音频上限（MB）", "上传限额", "int",
        _const_default("voice_pack", "VOICE_REF_MAX_MB", 10),
        minimum=1, maximum=100,
        hint="参考音频只是给克隆引擎当样本，10 秒左右就够。",
    ),
    ConfigField(
        "upload.max_voice_packs", "语音包数量上限", "上传限额", "int",
        _const_default("voice_pack", "MAX_PACKS", 30),
        minimum=1, maximum=200,
    ),

    # ---- 后台 / 世界 ----
    ConfigField(
        "world.tick_loop_sec", "后台 tick 间隔（秒）", "后台与世界", "int",
        1800, env="WORLD_TICK_LOOP_SEC", minimum=60, maximum=86400,
        restart_required=True,
        hint="角色不聊天时也推进世界。间隔在进程启动时读取。",
    ),
    ConfigField(
        "world.tick_min_interval_min", "世界推进最小间隔（分钟）", "后台与世界", "int",
        30, env="WORLD_TICK_MIN_INTERVAL_MIN", minimum=1, maximum=1440,
        restart_required=True,
    ),
    ConfigField(
        "world.active_user_days", "活跃用户判定天数", "后台与世界", "int",
        7, env="WORLD_TICK_ACTIVE_DAYS", minimum=1, maximum=365,
        restart_required=True,
        hint="只给最近这么多天聊过的用户做后台推进。",
    ),

    # ---- 嵌入模型 ----
    ConfigField(
        "embedding.provider", "嵌入提供方", "嵌入模型", "string",
        "fastembed", env="EMBEDDING_PROVIDER",
        choices=("fastembed", "openai", "huggingface"),
        restart_required=True,
        hint="换提供方会改变向量维度，已有向量库需要重建。",
    ),
    ConfigField(
        "embedding.model", "嵌入模型名", "嵌入模型", "string",
        "BAAI/bge-small-zh-v1.5", env="EMBEDDING_MODEL",
        restart_required=True,
    ),
]

_FIELD_BY_KEY = {f.key: f for f in FIELDS}

# 只允许字母数字和 - _ . / ，挡掉路径穿越之类的脏输入
_SAFE_STRING_RE = re.compile(r"^[A-Za-z0-9._/-]{1,120}$")
_VOICE_NAME_RE = re.compile(r"^[a-zA-Z]{2,3}-[a-zA-Z]{2,4}-[A-Za-z0-9]{2,40}$")


def fields() -> List[ConfigField]:
    return list(FIELDS)


def groups() -> List[str]:
    """按 FIELDS 的声明顺序去重（保持界面分组顺序稳定）"""
    seen: List[str] = []
    for f in FIELDS:
        if f.group not in seen:
            seen.append(f.group)
    return seen


# ---------------------------------------------------------------------------
# 存储
# ---------------------------------------------------------------------------

def load() -> Dict[str, Any]:
    """读覆盖值。文件不存在/损坏都退回空 dict（**不抛异常**）。

    配置被手改坏时宁可退回默认行为，也不能让整个服务起不来。
    """
    global _cache
    if _cache is not None:
        return dict(_cache)

    raw: Any = {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        raw = {}
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        logger.warning("[system_config] %s 读取失败，退回默认值: %s", CONFIG_FILE, e)
        raw = {}

    if not isinstance(raw, dict):
        logger.warning("[system_config] %s 不是对象，按空配置处理", CONFIG_FILE)
        raw = {}

    # 只保留已知键（文件被手改出脏键时静默丢弃，不污染生效值）
    _cache = {k: v for k, v in raw.items() if k in _FIELD_BY_KEY}
    return dict(_cache)


def _write(data: Dict[str, Any]) -> None:
    global _cache
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = f"{CONFIG_FILE}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, CONFIG_FILE)   # 原子替换，避免写一半崩掉
    _cache = dict(data)


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------

def _validate(f: ConfigField, value: Any) -> Any:
    if f.kind == "int":
        # 整数字段不接受小数 —— 否则「上限 64.5MB」这种值会一路传下去
        if isinstance(value, bool) or not isinstance(value, int):
            if isinstance(value, float):
                raise ConfigError(f"{f.label} 必须是整数")
            raise ConfigError(f"{f.label} 必须是整数")
        out: Any = value
    elif f.kind == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigError(f"{f.label} 必须是数字")
        out = float(value)
        if out != out or out in (float("inf"), float("-inf")):
            raise ConfigError(f"{f.label} 不是有效数字")
    else:
        if not isinstance(value, str):
            raise ConfigError(f"{f.label} 必须是字符串")
        out = value.strip()
        if not out:
            raise ConfigError(f"{f.label} 不能为空")
        if not _SAFE_STRING_RE.match(out):
            raise ConfigError(f"{f.label} 含非法字符")

    if f.minimum is not None and out < f.minimum:
        raise ConfigError(f"{f.label} 不能小于 {f.minimum}")
    if f.maximum is not None and out > f.maximum:
        raise ConfigError(f"{f.label} 不能大于 {f.maximum}")

    if f.choices and out not in f.choices:
        raise ConfigError(f"{f.label} 只能是 {'/'.join(f.choices)} 之一")

    if f.key == "tts.voice_name" and not _VOICE_NAME_RE.match(str(out)):
        raise ConfigError(f"{f.label} 不合法（形如 zh-CN-XiaoxiaoNeural）")

    return out


def save(patch: Dict[str, Any]) -> Dict[str, Any]:
    """局部更新覆盖值。值为 `None` 表示**删除该覆盖、恢复默认**。

    **先全部校验再落盘** —— 一次提交里有一个非法值就整批不写，
    避免留下「半套配置」这种最难排查的状态。
    """
    if not isinstance(patch, dict):
        raise ConfigError("配置必须是对象")

    current = load()
    validated: Dict[str, Any] = {}

    for key, value in patch.items():
        f = _FIELD_BY_KEY.get(key)
        if f is None:
            raise ConfigError(f"未知配置项：{key}")
        validated[key] = None if value is None else _validate(f, value)

    for key, value in validated.items():
        if value is None:
            current.pop(key, None)
        else:
            current[key] = value

    _write(current)
    return dict(current)


# ---------------------------------------------------------------------------
# 生效值
# ---------------------------------------------------------------------------

def _default_of(f: ConfigField) -> Any:
    """环境变量优先于代码默认值（保持与改动前一致的行为）"""
    if f.env:
        env_val = os.getenv(f.env)
        if env_val is not None and env_val != "":
            try:
                if f.kind == "int":
                    # 环境变量都是字符串：先转 float 再要求是整数，
                    # 直接传 float(64) 会被 _validate 的整数检查拒掉
                    as_float = float(env_val)
                    if not as_float.is_integer():
                        raise ConfigError(f"{f.label} 必须是整数")
                    raw: Any = int(as_float)
                elif f.kind == "float":
                    raw = float(env_val)
                else:
                    raw = env_val
                return _validate(f, raw)
            except (ConfigError, ValueError, TypeError) as e:
                logger.warning("[system_config] 环境变量 %s 非法（%s），改用默认值", f.env, e)
    # default 可能是零参可调用对象（默认值定义在别处，避免复制数字）
    return f.default() if callable(f.default) else f.default


def get_effective() -> Dict[str, Any]:
    """全部字段的当前生效值：文件 > 环境变量 > 默认值"""
    overrides = load()
    out: Dict[str, Any] = {}
    for f in FIELDS:
        out[f.key] = overrides[f.key] if f.key in overrides else _default_of(f)
    return out


def get(key: str) -> Any:
    """读单个生效值。未知键抛 ConfigError（拼错键名要能被发现）"""
    if key not in _FIELD_BY_KEY:
        raise ConfigError(f"未知配置项：{key}")
    return get_effective()[key]


def snapshot() -> Dict[str, Any]:
    """给接口用的形状：schema + 当前生效值，前端一个请求就能渲染完整界面"""
    effective = get_effective()
    overrides = load()
    return {
        "groups": groups(),
        "fields": [
            {
                "key": f.key,
                "label": f.label,
                "group": f.group,
                "kind": f.kind,
                "value": effective[f.key],
                "default": _default_of(f),
                "minimum": f.minimum,
                "maximum": f.maximum,
                "step": f.step,
                "choices": list(f.choices),
                "restart_required": f.restart_required,
                "hint": f.hint,
                # 是否被显式覆盖过（前端据此显示「已改」与「恢复默认」）
                "overridden": f.key in overrides,
            }
            for f in FIELDS
        ],
    }
