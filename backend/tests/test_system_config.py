"""系统配置：schema 校验 / 存储 / 生效值优先级。纯逻辑，不碰网络。"""
import json
from pathlib import Path

import pytest

from funcation import system_config as sc


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """每个用例一份独立的配置文件 + 清掉缓存"""
    monkeypatch.setattr(sc, "CONFIG_FILE", str(tmp_path / "system_config.json"))
    monkeypatch.setattr(sc, "_cache", None)
    yield


# ============================================================
# 生效值优先级：文件 > 环境变量 > 默认值
# ============================================================

def test_defaults_come_from_schema():
    """没配过任何东西时取到 schema 默认值 —— 等于现在 .env 的默认行为"""
    assert sc.get_effective()["tts.voice_name"] == "zh-CN-XiaoxiaoNeural"
    assert sc.get_effective()["tts.speaking_rate"] == 1.0


def test_env_var_overrides_default(monkeypatch):
    monkeypatch.setenv("VOICE_NAME", "zh-CN-YunxiNeural")
    monkeypatch.setattr(sc, "_cache", None)
    assert sc.get_effective()["tts.voice_name"] == "zh-CN-YunxiNeural"


def test_file_value_beats_env(monkeypatch):
    """文件 > 环境变量 —— 否则界面上改完不生效，用户会以为坏了"""
    monkeypatch.setenv("VOICE_NAME", "zh-CN-YunxiNeural")
    sc.save({"tts.voice_name": "zh-CN-XiaoyiNeural"})
    assert sc.get_effective()["tts.voice_name"] == "zh-CN-XiaoyiNeural"


def test_get_returns_single_value(monkeypatch):
    assert sc.get("tts.speaking_rate") == 1.0
    sc.save({"tts.speaking_rate": 1.5})
    assert sc.get("tts.speaking_rate") == 1.5


def test_get_unknown_key_raises():
    with pytest.raises(sc.ConfigError):
        sc.get("nope.nope")


# ============================================================
# 存储
# ============================================================

def test_only_overrides_are_persisted():
    """只存被显式改过的键。

    全量落盘会把默认值冻结下来 —— 以后改代码里的默认值就对老部署失效了。
    """
    sc.save({"tts.speaking_rate": 1.2})
    stored = json.loads(Path(sc.CONFIG_FILE).read_text(encoding="utf-8"))
    assert stored == {"tts.speaking_rate": 1.2}


def test_reset_removes_override():
    sc.save({"tts.speaking_rate": 1.2})
    sc.save({"tts.speaking_rate": None})  # None = 恢复默认
    assert sc.get_effective()["tts.speaking_rate"] == 1.0
    stored = json.loads(Path(sc.CONFIG_FILE).read_text(encoding="utf-8"))
    assert "tts.speaking_rate" not in stored


def test_partial_save_keeps_other_overrides():
    sc.save({"tts.speaking_rate": 1.2, "tts.volume": 0.8})
    sc.save({"tts.volume": 1.5})
    assert sc.get("tts.speaking_rate") == 1.2
    assert sc.get("tts.volume") == 1.5


def test_corrupt_config_file_falls_back_to_defaults():
    """配置文件被手改坏 → 退回默认值，不能让整个服务起不来"""
    Path(sc.CONFIG_FILE).write_text("{ 这不是 json", encoding="utf-8")
    sc._cache = None
    assert sc.get_effective()["tts.speaking_rate"] == 1.0


def test_non_dict_config_file_is_ignored():
    Path(sc.CONFIG_FILE).write_text("[1, 2, 3]", encoding="utf-8")
    sc._cache = None
    assert sc.get_effective()["tts.speaking_rate"] == 1.0


# ============================================================
# 校验
# ============================================================

def test_out_of_range_rejected():
    with pytest.raises(sc.ConfigError):
        sc.save({"tts.speaking_rate": 99})
    with pytest.raises(sc.ConfigError):
        sc.save({"tts.speaking_rate": 0.01})


def test_unknown_key_rejected():
    """未知键直接拒 —— 静默忽略会让人以为配上了"""
    with pytest.raises(sc.ConfigError):
        sc.save({"tts.nonexistent": 1})


def test_non_numeric_rejected():
    with pytest.raises(sc.ConfigError):
        sc.save({"tts.speaking_rate": "快一点"})


def test_nan_and_inf_rejected():
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(sc.ConfigError):
            sc.save({"tts.speaking_rate": bad})


def test_int_field_rejects_float():
    """整数字段不接受小数 —— 否则「上限 64.5 个包」这种值会一路传下去"""
    with pytest.raises(sc.ConfigError):
        sc.save({"upload.voice_ref_max_mb": 64.5})


def test_model_max_mb_accepts_fraction_to_keep_env_contract(monkeypatch):
    """`upload.model_max_mb` 刻意是小数型。

    原实现用 `float(os.getenv("MODEL_MAX_MB"))` 解析，已有部署可能配了 0.001
    这类值；改成整数型会**悄悄收窄既有的 env 契约**。
    """
    sc.save({"upload.model_max_mb": 0.001})
    assert sc.get("upload.model_max_mb") == 0.001


def test_voice_name_validated():
    with pytest.raises(sc.ConfigError):
        sc.save({"tts.voice_name": "../../etc/passwd"})
    with pytest.raises(sc.ConfigError):
        sc.save({"tts.voice_name": ""})


def test_embedding_provider_restricted_to_known_values():
    with pytest.raises(sc.ConfigError):
        sc.save({"embedding.provider": "不存在的引擎"})


def test_bad_value_does_not_partially_write():
    """一次 PATCH 里有一个非法值 → 整批都不落盘（避免半套配置）"""
    with pytest.raises(sc.ConfigError):
        sc.save({"tts.speaking_rate": 1.2, "tts.volume": 99})
    assert sc.get("tts.speaking_rate") == 1.0


# ============================================================
# schema 安全性
# ============================================================

def test_secrets_are_not_exposed():
    """密钥类配置绝不能进 schema —— 在界面上改密钥是安全风险，
    而且会让现有会话全部失效。要改请编辑 .env。"""
    keys = " ".join(f.key for f in sc.fields()).lower()
    for forbidden in ("jwt", "secret", "password", "api_key", "apikey", "token"):
        assert forbidden not in keys, f"schema 暴露了敏感项：{forbidden}"


def test_schema_declares_restart_requirement():
    """需要重启的项必须如实标注，否则用户改完没生效会以为坏了"""
    restart = {f.key for f in sc.fields() if f.restart_required}
    assert "world.tick_loop_sec" in restart
    assert "embedding.provider" in restart
    assert "tts.voice_name" not in restart  # 音色是即时生效的


def test_every_field_has_label_and_group():
    """前端按 schema 渲染，缺 label/group 会渲染出空白项"""
    for f in sc.fields():
        assert f.label, f.key
        assert f.group, f.key


def test_field_keys_are_unique():
    keys = [f.key for f in sc.fields()]
    assert len(keys) == len(set(keys))


def test_schema_snapshot_matches_effective():
    """GET 的形状：schema + 当前生效值，前端一个请求就能渲染"""
    snap = sc.snapshot()
    assert set(snap) >= {"fields", "groups"}
    for f in snap["fields"]:
        assert set(f) >= {
            "key", "label", "group", "kind", "value", "default",
            "restart_required", "hint",
        }
        assert f["value"] == sc.get(f["key"])
