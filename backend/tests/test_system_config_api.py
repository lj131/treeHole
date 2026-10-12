"""系统配置接口：GET/PATCH /admin/config。

**仅管理员** —— 这些是全局配置，会影响所有用户。
"""
import uuid

import pytest


def _unique(prefix="user"):
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


@pytest.fixture
def admin_headers(client):
    r = client.post("/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture
def user_headers(client, admin_headers):
    """已审批的**普通用户** —— 用来验证管理员门"""
    name = _unique()
    pwd = "pass1234"
    reg = client.post("/auth/register", json={"username": name, "password": pwd})
    assert reg.status_code == 200, reg.text
    uid = reg.json()["user"]["id"]
    client.post(f"/auth/admin/approve/{uid}", headers=admin_headers)
    lg = client.post("/auth/login", json={"username": name, "password": pwd})
    assert lg.status_code == 200, lg.text
    return {"Authorization": f"Bearer {lg.json()['token']}"}


@pytest.fixture(autouse=True)
def _isolate_config(tmp_path, monkeypatch):
    """每个用例一份独立配置文件，避免互相污染"""
    from funcation import system_config as sc

    monkeypatch.setattr(sc, "CONFIG_FILE", str(tmp_path / "system_config.json"))
    monkeypatch.setattr(sc, "_cache", None)
    yield


# ============================================================
# 权限
# ============================================================

def test_get_requires_auth(client, tmp_data_dir):
    assert client.get("/admin/config").status_code in (401, 403)


def test_get_is_admin_only(client, tmp_data_dir, user_headers):
    r = client.get("/admin/config", headers=user_headers)
    assert r.status_code == 403, r.text


def test_patch_is_admin_only(client, tmp_data_dir, user_headers):
    r = client.patch("/admin/config", json={"values": {"tts.volume": 1.5}},
                     headers=user_headers)
    assert r.status_code == 403, r.text


# ============================================================
# GET
# ============================================================

def test_get_returns_schema_and_values(client, tmp_data_dir, admin_headers):
    r = client.get("/admin/config", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["groups"]
    keys = {f["key"] for f in body["fields"]}
    assert "tts.voice_name" in keys
    assert "upload.model_max_mb" in keys

    for f in body["fields"]:
        assert set(f) >= {
            "key", "label", "group", "kind", "value", "default",
            "restart_required", "hint", "overridden",
        }


def test_get_does_not_expose_secrets(client, tmp_data_dir, admin_headers):
    """密钥类配置绝不能出现在响应里（界面上改密钥是安全风险）"""
    body = client.get("/admin/config", headers=admin_headers).json()
    blob = str(body).lower()
    for forbidden in ("jwt", "secret", "password", "api_key", "apikey"):
        assert forbidden not in blob, f"响应里出现了敏感项：{forbidden}"


# ============================================================
# PATCH
# ============================================================

def test_patch_updates_value(client, tmp_data_dir, admin_headers):
    r = client.patch("/admin/config", json={"values": {"tts.speaking_rate": 1.3}},
                     headers=admin_headers)
    assert r.status_code == 200, r.text
    field = next(f for f in r.json()["fields"] if f["key"] == "tts.speaking_rate")
    assert field["value"] == 1.3
    assert field["overridden"] is True


def test_patch_takes_effect_immediately_for_tts(client, tmp_data_dir, admin_headers):
    """改默认音色要立刻生效 —— 这是本功能的核心价值（不用重启）"""
    from funcation.voice_service import VoiceService

    client.patch("/admin/config", json={"values": {"tts.voice_name": "zh-CN-YunxiNeural"}},
                 headers=admin_headers)
    # 用一个没被绑定过语音包的角色，才会落到全局默认
    resolved = VoiceService().resolve("someone_without_pack")
    assert resolved.voice_name == "zh-CN-YunxiNeural"


def test_patch_null_resets_to_default(client, tmp_data_dir, admin_headers):
    client.patch("/admin/config", json={"values": {"tts.speaking_rate": 1.3}},
                 headers=admin_headers)
    r = client.patch("/admin/config", json={"values": {"tts.speaking_rate": None}},
                     headers=admin_headers)
    assert r.status_code == 200, r.text
    field = next(f for f in r.json()["fields"] if f["key"] == "tts.speaking_rate")
    assert field["value"] == 1.0
    assert field["overridden"] is False


def test_patch_rejects_out_of_range(client, tmp_data_dir, admin_headers):
    r = client.patch("/admin/config", json={"values": {"tts.speaking_rate": 99}},
                     headers=admin_headers)
    assert r.status_code == 400, r.text


def test_patch_rejects_unknown_key(client, tmp_data_dir, admin_headers):
    r = client.patch("/admin/config", json={"values": {"tts.nope": 1}},
                     headers=admin_headers)
    assert r.status_code == 400, r.text


def test_patch_rejects_bad_voice_name(client, tmp_data_dir, admin_headers):
    r = client.patch("/admin/config", json={"values": {"tts.voice_name": "../../etc/passwd"}},
                     headers=admin_headers)
    assert r.status_code == 400, r.text


def test_patch_missing_values_key_is_400(client, tmp_data_dir, admin_headers):
    r = client.patch("/admin/config", json={}, headers=admin_headers)
    assert r.status_code == 400, r.text


# ============================================================
# 与既有行为的兼容（最重要的一条）
# ============================================================

def test_untouched_config_keeps_original_behaviour(client, tmp_data_dir, admin_headers):
    """**什么都没配时，取值必须与改动前一致** —— 否则等于偷偷改了默认值"""
    from funcation import model3d, voice_pack
    from funcation.voice_service import VoiceService

    assert model3d.max_model_bytes() == model3d.DEFAULT_MAX_MODEL_MB * 1024 * 1024
    assert voice_pack.max_ref_bytes() == voice_pack.VOICE_REF_MAX_MB * 1024 * 1024
    assert voice_pack.max_packs() == voice_pack.MAX_PACKS

    defaults = VoiceService().env_defaults()
    assert defaults["voice_name"] == voice_pack.FALLBACK_VOICE
    assert defaults["speaking_rate"] == 1.0
    assert defaults["pitch"] == 0.0
    assert defaults["volume"] == 1.0


def test_module_constant_still_works_when_config_absent(client, tmp_data_dir, monkeypatch):
    """没配过配置时，monkeypatch 模块常量仍然有效（测试与老代码都依赖这一点）"""
    from funcation import voice_pack

    monkeypatch.setattr(voice_pack, "MAX_PACKS", 7)
    monkeypatch.setattr(voice_pack, "VOICE_REF_MAX_MB", 3)
    assert voice_pack.max_packs() == 7
    assert voice_pack.max_ref_bytes() == 3 * 1024 * 1024
