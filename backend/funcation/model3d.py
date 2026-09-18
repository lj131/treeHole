"""3D 角色模型（VRM / glTF）支持：文件校验 + 配置归一化。

设计原则：
- 本模块只做**纯函数**逻辑（无 IO、无 FastAPI 依赖），便于单测。
- 角色 JSON 中的 `model3d` 字段结构由 `build_default_config` / `normalize_config` 定义，
  前端 `Model3DViewer.vue` 按同一份字段读取。
- 所有数值都做 clamp，避免前端传入极端值把相机/模型搞坏。
"""

from __future__ import annotations

import os
from typing import Any

# ---------------------------------------------------------------- 常量

#: 允许的模型扩展名 → 规范化格式名
EXTENSION_FORMAT_MAP: dict[str, str] = {
    ".vrm": "vrm",
    ".glb": "glb",
    ".gltf": "gltf",
}

#: 允许的 MIME（浏览器上传时可能给的不一致，仅作参考，主校验走扩展名）
ALLOWED_CONTENT_TYPES: set[str] = {
    "model/gltf-binary",
    "model/gltf+json",
    "application/octet-stream",
    "application/x-vrm",
    "model/vrm",
    "application/vnd.vrm",
    "binary/octet-stream",
}

#: 单文件大小上限（MB），可用环境变量覆盖
DEFAULT_MAX_MODEL_MB = 64

#: 支持的默认表情（与 VRM 1.0 预设表情名对齐；前端再做一次实际可用性校验）
SUPPORTED_EXPRESSIONS: tuple[str, ...] = (
    "neutral",
    "happy",
    "angry",
    "sad",
    "relaxed",
    "surprised",
)

#: 相机 / 变换参数的合法区间：(min, max, 默认值)
NUMERIC_RANGES: dict[str, tuple[float, float, float]] = {
    "scale": (0.1, 5.0, 1.0),
    "rotation_y": (-180.0, 180.0, 0.0),
    "camera_distance": (0.3, 5.0, 1.4),
    "camera_height": (0.0, 3.0, 1.3),
    "camera_fov": (10.0, 90.0, 30.0),
}

#: 允许出现在 position 里的轴
POSITION_AXES: tuple[str, ...] = ("x", "y", "z")
POSITION_RANGE: tuple[float, float] = (-2.0, 2.0)


def max_model_bytes() -> int:
    """读取环境变量 `MODEL_MAX_MB`，失败时回退默认值。"""
    raw = os.getenv("MODEL_MAX_MB")
    if raw:
        try:
            mb = float(raw)
            if mb > 0:
                return int(mb * 1024 * 1024)
        except (TypeError, ValueError):
            pass
    return DEFAULT_MAX_MODEL_MB * 1024 * 1024


# ---------------------------------------------------------------- 校验


def detect_format(filename: str | None) -> str | None:
    """从文件名推断格式，不在白名单内返回 None。"""
    if not filename:
        return None
    _, ext = os.path.splitext(filename.strip().lower())
    return EXTENSION_FORMAT_MAP.get(ext)


def validate_upload(filename: str | None, size_bytes: int | None) -> tuple[str, str]:
    """校验上传的模型文件。

    返回 `(extension, format)`；不合法时抛 `ValueError`，消息可直接回给前端。
    """
    if not filename:
        raise ValueError("缺少文件名")
    ext = os.path.splitext(filename.strip().lower())[1]
    fmt = EXTENSION_FORMAT_MAP.get(ext)
    if fmt is None:
        allowed = "/".join(sorted(e.lstrip(".") for e in EXTENSION_FORMAT_MAP))
        raise ValueError(f"不支持的模型格式: {ext or filename}，仅支持 {allowed}")

    if size_bytes is None:
        raise ValueError("无法读取文件大小")
    if size_bytes <= 0:
        raise ValueError("模型文件为空")
    limit = max_model_bytes()
    if size_bytes > limit:
        raise ValueError(
            f"模型文件过大（{size_bytes / 1024 / 1024:.1f}MB），上限 {limit / 1024 / 1024:.0f}MB"
        )
    return ext, fmt


def build_model_filename(character_id: str, ext: str, token: str) -> str:
    """生成落盘文件名，保持与头像一致的 `{char_id}_{hex}.{ext}` 风格。"""
    safe_id = "".join(c for c in (character_id or "char") if c.isalnum() or c in "-_") or "char"
    safe_ext = ext if ext.startswith(".") else f".{ext}"
    return f"{safe_id}_{token}{safe_ext}"


# ---------------------------------------------------------------- 配置归一化


def _clamp(value: Any, low: float, high: float, default: float) -> float:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return default
    if num != num:  # NaN
        return default
    return max(low, min(high, num))


def _normalize_position(raw: Any) -> dict[str, float]:
    if not isinstance(raw, dict):
        return {axis: 0.0 for axis in POSITION_AXES}
    low, high = POSITION_RANGE
    return {axis: _clamp(raw.get(axis), low, high, 0.0) for axis in POSITION_AXES}


def _normalize_expression(raw: Any) -> str:
    if isinstance(raw, str) and raw.strip() in SUPPORTED_EXPRESSIONS:
        return raw.strip()
    return "neutral"


def build_default_config(url: str, fmt: str, **overrides: Any) -> dict[str, Any]:
    """构造一份完整的默认 model3d 配置。"""
    config: dict[str, Any] = {
        "url": url,
        "format": fmt,
        "enabled": True,
        "scale": NUMERIC_RANGES["scale"][2],
        "rotation_y": NUMERIC_RANGES["rotation_y"][2],
        "position": _normalize_position(None),
        "camera_distance": NUMERIC_RANGES["camera_distance"][2],
        "camera_height": NUMERIC_RANGES["camera_height"][2],
        "camera_fov": NUMERIC_RANGES["camera_fov"][2],
        "default_expression": "neutral",
        "auto_rotate": False,
        "background": "transparent",
    }
    config.update({k: v for k, v in overrides.items() if v is not None})
    return normalize_config(config)


def normalize_config(raw: Any, base: dict[str, Any] | None = None) -> dict[str, Any]:
    """把任意来源（前端表单 / 旧数据 / 手改 JSON）的配置归一化成合法结构。

    非法字段丢弃、数值 clamp、缺失字段用 `base` 或默认值补齐。
    """
    merged: dict[str, Any] = dict(base or {})
    if isinstance(raw, dict):
        merged.update(raw)

    url = merged.get("url")
    if not isinstance(url, str) or not url.strip():
        raise ValueError("model3d.url 必须是非空字符串")
    url = url.strip()

    fmt = merged.get("format")
    if not isinstance(fmt, str) or fmt.lower() not in EXTENSION_FORMAT_MAP.values():
        fmt = detect_format(url) or "vrm"
    fmt = fmt.lower()

    config: dict[str, Any] = {
        "url": url,
        "format": fmt,
        "enabled": bool(merged.get("enabled", True)),
        "position": _normalize_position(merged.get("position")),
        "default_expression": _normalize_expression(merged.get("default_expression")),
        "auto_rotate": bool(merged.get("auto_rotate", False)),
    }

    for key, (low, high, default) in NUMERIC_RANGES.items():
        config[key] = _clamp(merged.get(key), low, high, default)

    background = merged.get("background", "transparent")
    config["background"] = (
        background if background in ("transparent", "theme", "solid") else "transparent"
    )

    if isinstance(merged.get("updated_at"), str):
        config["updated_at"] = merged["updated_at"]

    return config


def config_summary(character: dict[str, Any]) -> dict[str, Any] | None:
    """给列表接口用的精简摘要（避免把整份配置塞进 /characters）。"""
    raw = character.get("model3d") if isinstance(character, dict) else None
    if not isinstance(raw, dict) or not raw.get("url"):
        return None
    return {
        "url": raw.get("url"),
        "format": raw.get("format") or detect_format(raw.get("url")) or "vrm",
        "enabled": bool(raw.get("enabled", True)),
    }
