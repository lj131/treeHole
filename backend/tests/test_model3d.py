"""3D 模型配置纯函数单测（funcation/model3d.py）。

不经过 FastAPI，覆盖：格式判定、上传校验、文件名生成、配置归一化 / clamp。
"""
import os

import pytest

from funcation import model3d


# ---------- detect_format ----------

@pytest.mark.parametrize("name,expected", [
    ("avatar.vrm", "vrm"),
    ("AVATAR.VRM", "vrm"),
    ("model.glb", "glb"),
    ("scene.gltf", "gltf"),
    ("  spaced.glb  ", "glb"),
    ("model.fbx", None),
    ("model.zip", None),
    ("noext", None),
    (None, None),
    ("", None),
])
def test_detect_format(name, expected):
    assert model3d.detect_format(name) == expected


# ---------- validate_upload ----------

def test_validate_upload_ok():
    ext, fmt = model3d.validate_upload("char_ab12.vrm", 1024)
    assert (ext, fmt) == (".vrm", "vrm")


@pytest.mark.parametrize("name", ["bad.exe", "bad.zip", "noext", "", None])
def test_validate_upload_rejects_bad_extension(name):
    with pytest.raises(ValueError):
        model3d.validate_upload(name, 1024)


def test_validate_upload_rejects_empty_file():
    with pytest.raises(ValueError, match="空"):
        model3d.validate_upload("a.glb", 0)


def test_validate_upload_rejects_unknown_size():
    with pytest.raises(ValueError):
        model3d.validate_upload("a.glb", None)


def test_validate_upload_size_limit(monkeypatch):
    monkeypatch.setenv("MODEL_MAX_MB", "1")
    ok = 1024 * 1024  # 恰好 1MB 允许
    model3d.validate_upload("a.glb", ok)
    with pytest.raises(ValueError, match="过大"):
        model3d.validate_upload("a.glb", ok + 1)


def test_max_model_bytes_default_and_env(monkeypatch):
    monkeypatch.delenv("MODEL_MAX_MB", raising=False)
    assert model3d.max_model_bytes() == model3d.DEFAULT_MAX_MODEL_MB * 1024 * 1024

    monkeypatch.setenv("MODEL_MAX_MB", "2")
    assert model3d.max_model_bytes() == 2 * 1024 * 1024

    # 非法值回退默认
    monkeypatch.setenv("MODEL_MAX_MB", "abc")
    assert model3d.max_model_bytes() == model3d.DEFAULT_MAX_MODEL_MB * 1024 * 1024


# ---------- build_model_filename ----------

def test_build_model_filename_sanitizes_id():
    name = model3d.build_model_filename("../../etc/passwd", ".vrm", "ab12cd34")
    assert name == "etcpasswd_ab12cd34.vrm"
    assert os.path.basename(name) == name  # 无路径成分


def test_build_model_filename_accepts_ext_without_dot():
    assert model3d.build_model_filename("linwan", "glb", "ffff0000") == "linwan_ffff0000.glb"


def test_build_model_filename_empty_id_fallback():
    assert model3d.build_model_filename("", ".vrm", "x1").startswith("char_")


# ---------- normalize_config ----------

def test_normalize_config_requires_url():
    with pytest.raises(ValueError, match="url"):
        model3d.normalize_config({"scale": 2})
    with pytest.raises(ValueError):
        model3d.normalize_config({"url": "   "})


def test_normalize_config_fills_defaults():
    cfg = model3d.normalize_config({"url": "/models/a.vrm"})
    assert cfg["format"] == "vrm"
    assert cfg["enabled"] is True
    assert cfg["scale"] == 1.0
    assert cfg["position"] == {"x": 0.0, "y": 0.0, "z": 0.0}
    assert cfg["camera_distance"] == 1.4
    assert cfg["camera_fov"] == 30.0
    assert cfg["default_expression"] == "neutral"
    assert cfg["auto_rotate"] is False


def test_normalize_config_infers_format_from_url():
    assert model3d.normalize_config({"url": "/models/a.glb"})["format"] == "glb"
    # 无法推断时回退 vrm
    assert model3d.normalize_config({"url": "https://cdn.x/a"})["format"] == "vrm"


def test_normalize_config_clamps_out_of_range():
    cfg = model3d.normalize_config({
        "url": "/models/a.vrm",
        "scale": 999,
        "rotation_y": -720,
        "camera_distance": 0.0001,
        "camera_height": 99,
        "camera_fov": 1,
        "position": {"x": 100, "y": -100, "z": "nan"},
    })
    assert cfg["scale"] == 5.0
    assert cfg["rotation_y"] == -180.0
    assert cfg["camera_distance"] == 0.3
    assert cfg["camera_height"] == 3.0
    assert cfg["camera_fov"] == 10.0
    assert cfg["position"] == {"x": 2.0, "y": -2.0, "z": 0.0}


def test_normalize_config_garbage_values_fall_back():
    cfg = model3d.normalize_config({
        "url": "/models/a.vrm",
        "scale": "big",
        "position": "left",
        "default_expression": "excited",
        "background": "neon",
        "auto_rotate": "yes",
    })
    assert cfg["scale"] == 1.0
    assert cfg["position"] == {"x": 0.0, "y": 0.0, "z": 0.0}
    assert cfg["default_expression"] == "neutral"
    assert cfg["background"] == "transparent"
    assert cfg["auto_rotate"] is True


def test_normalize_config_merges_with_base():
    base = model3d.build_default_config("/models/a.vrm", "vrm")
    cfg = model3d.normalize_config({"scale": 1.8}, base)
    assert cfg["scale"] == 1.8
    assert cfg["url"] == "/models/a.vrm"
    assert cfg["camera_fov"] == base["camera_fov"]


def test_normalize_config_ignores_unknown_keys():
    cfg = model3d.normalize_config({"url": "/models/a.vrm", "hack": "boom"})
    assert "hack" not in cfg


# ---------- build_default_config / config_summary ----------

def test_build_default_config_roundtrip():
    cfg = model3d.build_default_config("/models/a.glb", "glb", updated_at="2026-09-18T00:00:00Z")
    assert cfg["url"] == "/models/a.glb"
    assert cfg["format"] == "glb"
    assert cfg["updated_at"] == "2026-09-18T00:00:00Z"


def test_config_summary():
    assert model3d.config_summary({}) is None
    assert model3d.config_summary({"model3d": {}}) is None
    assert model3d.config_summary({"model3d": {"url": ""}}) is None

    summary = model3d.config_summary({
        "model3d": {"url": "/models/a.vrm", "format": "vrm", "enabled": True, "scale": 1.2}
    })
    assert summary == {"url": "/models/a.vrm", "format": "vrm", "enabled": True}


def test_config_summary_infers_missing_format():
    summary = model3d.config_summary({"model3d": {"url": "/models/a.glb"}})
    assert summary["format"] == "glb"
