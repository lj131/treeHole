"""语音包 API 集成测试：增删改查 / 上传 / 绑定 / 试听 / 权限。

关键约束：**语音包仅管理员可操作**（全局资源，会影响所有角色和所有用户），
所以每个写接口都要有一条"非管理员被拒"的用例。

依赖 conftest 的 session 级 TestClient + function 级 tmp_data_dir（cwd 隔离）。
"""
import json
import uuid
from pathlib import Path

import pytest


def _unique(prefix="user"):
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


@pytest.fixture
def admin_token(client):
    r = client.post("/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture
def plain_headers(client, admin_token):
    """已审批的**普通用户**（非管理员）—— 用来验证"仅管理员可操作"。"""
    name = _unique()
    pwd = "pass1234"
    reg = client.post("/auth/register", json={"username": name, "password": pwd})
    assert reg.status_code == 200, reg.text
    user_id = reg.json()["user"]["id"]

    apv = client.post(f"/auth/admin/approve/{user_id}",
                      headers={"Authorization": f"Bearer {admin_token}"})
    assert apv.status_code == 200, apv.text

    lg = client.post("/auth/login", json={"username": name, "password": pwd})
    assert lg.status_code == 200, lg.text
    return {"Authorization": f"Bearer {lg.json()['token']}"}


@pytest.fixture(autouse=True)
def _clear_character_cache():
    from funcation.memory_center import MemoryCenter
    MemoryCenter._character_cache.clear()
    yield
    MemoryCenter._character_cache.clear()


@pytest.fixture
def packs_file():
    """当前测试私有 cwd 下的语音包文件"""
    return Path("data/voice_packs.json")


@pytest.fixture
def bindings_file():
    return Path("data/voice_bindings.json")


def _create_pack(client, headers, **overrides):
    payload = {"name": "测试语音包", "voice_name": "zh-CN-XiaoyiNeural", **overrides}
    r = client.post("/voice/packs", json=payload, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["pack"]


# ============================================================
# 权限：仅管理员
# ============================================================

@pytest.mark.parametrize("method,path,body", [
    ("get", "/voice/voices", None),
    ("get", "/voice/packs", None),
    ("post", "/voice/packs", {"name": "x"}),
    ("patch", "/voice/packs/vp_aaaaaaaa", {"name": "x"}),
    ("delete", "/voice/packs/vp_aaaaaaaa", None),
    ("delete", "/voice/packs/vp_aaaaaaaa/reference", None),
    ("post", "/voice/preview", {"pack_id": "vp_aaaaaaaa"}),
    ("post", "/voice/bindings", {"character_id": "linwan", "pack_id": None}),
])
def test_non_admin_forbidden(client, tmp_data_dir, plain_headers, method, path, body):
    r = getattr(client, method)(path, json=body, headers=plain_headers) if body is not None \
        else getattr(client, method)(path, headers=plain_headers)
    assert r.status_code == 403, f"{method} {path} → {r.status_code} {r.text}"


def test_anonymous_rejected(client, tmp_data_dir):
    r = client.get("/voice/packs")
    assert r.status_code in (401, 403), r.text


# ============================================================
# 音色目录
# ============================================================

def test_list_voices_returns_catalog_and_engines(client, tmp_data_dir, admin_headers):
    r = client.get("/voice/voices", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["voices"], "音色目录不能为空（网络不通也要有静态兜底）"
    assert body["default_voice"]
    assert body["max_packs"] > 0
    assert ".wav" in body["allowed_audio_exts"]

    engines = {e["engine"]: e for e in body["engines"]}
    assert engines["edge"]["available"] is True
    # 克隆引擎没部署，必须如实标注不可用
    assert engines["clone"]["available"] is False


# ============================================================
# 增删改查
# ============================================================

def test_create_pack_persists(client, tmp_data_dir, admin_headers, packs_file):
    pack = _create_pack(client, admin_headers, name="温柔学姐", speaking_rate=0.9)
    assert pack["name"] == "温柔学姐"
    assert pack["speaking_rate"] == 0.9
    assert pack["has_reference_audio"] is False

    assert packs_file.exists()
    stored = json.loads(packs_file.read_text(encoding="utf-8"))
    assert [p["id"] for p in stored] == [pack["id"]]


def test_create_pack_rejects_bad_voice_name(client, tmp_data_dir, admin_headers):
    r = client.post("/voice/packs",
                    json={"name": "坏音色", "voice_name": "../../etc/passwd"},
                    headers=admin_headers)
    assert r.status_code == 400, r.text
    assert "音色名" in r.json()["detail"]


def test_create_pack_rejects_blank_name(client, tmp_data_dir, admin_headers):
    r = client.post("/voice/packs", json={"name": "   "}, headers=admin_headers)
    assert r.status_code == 400, r.text


def test_create_pack_clamps_out_of_range(client, tmp_data_dir, admin_headers):
    pack = _create_pack(client, admin_headers, speaking_rate=99, pitch=-999, volume=99)
    assert pack["speaking_rate"] == 2.0
    assert pack["pitch"] == -50.0
    assert pack["volume"] == 2.0


def test_update_pack_partial(client, tmp_data_dir, admin_headers):
    pack = _create_pack(client, admin_headers, pitch=5.0)
    r = client.patch(f"/voice/packs/{pack['id']}", json={"name": "改名了"}, headers=admin_headers)
    assert r.status_code == 200, r.text
    updated = r.json()["pack"]
    assert updated["name"] == "改名了"
    assert updated["pitch"] == 5.0          # 没传的字段保持
    assert updated["voice_name"] == pack["voice_name"]


def test_update_unknown_pack_404(client, tmp_data_dir, admin_headers):
    r = client.patch("/voice/packs/vp_deadbeef", json={"name": "x"}, headers=admin_headers)
    assert r.status_code == 404, r.text


def test_delete_pack(client, tmp_data_dir, admin_headers):
    pack = _create_pack(client, admin_headers)
    r = client.delete(f"/voice/packs/{pack['id']}", headers=admin_headers)
    assert r.status_code == 200, r.text

    listing = client.get("/voice/packs", headers=admin_headers).json()
    assert all(p["id"] != pack["id"] for p in listing["packs"])


def test_delete_pack_unknown_404(client, tmp_data_dir, admin_headers):
    r = client.delete("/voice/packs/vp_deadbeef", headers=admin_headers)
    assert r.status_code == 404, r.text


def test_max_packs_enforced(client, tmp_data_dir, admin_headers, monkeypatch):
    from funcation import voice_pack as vp
    monkeypatch.setattr(vp, "MAX_PACKS", 2)

    _create_pack(client, admin_headers, name="A")
    _create_pack(client, admin_headers, name="B")
    r = client.post("/voice/packs", json={"name": "C"}, headers=admin_headers)
    assert r.status_code == 400, r.text
    assert "上限" in r.json()["detail"]


# ============================================================
# 参考音频上传
# ============================================================

def _upload(client, headers, pack_id, filename="sample.wav",
            content_type="audio/wav", data=b"RIFF....WAVEfmt "):
    return client.post(
        f"/voice/packs/{pack_id}/reference",
        files={"file": (filename, data, content_type)},
        headers=headers,
    )


def test_upload_reference_stores_file(client, tmp_data_dir, admin_headers):
    pack = _create_pack(client, admin_headers)
    r = _upload(client, admin_headers, pack["id"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pack"]["has_reference_audio"] is True

    refs = sorted(p.name for p in Path("data/voice_refs").iterdir())
    assert refs == [f"{pack['id']}.wav"]

    # 落盘的路径要能被读到
    stored = json.loads(Path("data/voice_packs.json").read_text(encoding="utf-8"))
    assert stored[0]["reference_audio"].endswith(f"{pack['id']}.wav")


def test_upload_reference_replaces_old_format(client, tmp_data_dir, admin_headers):
    """换格式重传不能同时留下 .wav 和 .mp3"""
    pack = _create_pack(client, admin_headers)
    _upload(client, admin_headers, pack["id"], filename="a.wav", content_type="audio/wav")
    _upload(client, admin_headers, pack["id"], filename="a.mp3", content_type="audio/mpeg")

    refs = sorted(p.name for p in Path("data/voice_refs").iterdir())
    assert refs == [f"{pack['id']}.mp3"]


def test_upload_reference_rejects_bad_ext(client, tmp_data_dir, admin_headers):
    pack = _create_pack(client, admin_headers)
    r = _upload(client, admin_headers, pack["id"], filename="evil.exe",
                content_type="application/octet-stream")
    assert r.status_code == 400, r.text
    assert not list(Path("data/voice_refs").iterdir())


def test_upload_reference_rejects_empty(client, tmp_data_dir, admin_headers):
    pack = _create_pack(client, admin_headers)
    r = _upload(client, admin_headers, pack["id"], data=b"")
    assert r.status_code == 400, r.text
    assert not list(Path("data/voice_refs").iterdir())


def test_upload_reference_rejects_oversize(client, tmp_data_dir, admin_headers, monkeypatch):
    from funcation import voice_pack as vp
    monkeypatch.setattr(vp, "VOICE_REF_MAX_MB", 1)   # 把上限压到 1MB，免得测试真传 10MB

    pack = _create_pack(client, admin_headers)
    r = _upload(client, admin_headers, pack["id"], data=b"x" * (2 * 1024 * 1024))
    assert r.status_code == 400, r.text
    assert "上限" in r.json()["detail"]
    assert not list(Path("data/voice_refs").iterdir())


def test_upload_reference_unknown_pack_404(client, tmp_data_dir, admin_headers):
    r = _upload(client, admin_headers, "vp_deadbeef")
    assert r.status_code == 404, r.text


def test_delete_reference_keeps_pack(client, tmp_data_dir, admin_headers):
    pack = _create_pack(client, admin_headers)
    _upload(client, admin_headers, pack["id"])

    r = client.delete(f"/voice/packs/{pack['id']}/reference", headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.json()["pack"]["has_reference_audio"] is False
    assert not list(Path("data/voice_refs").iterdir())

    # 语音包本身还在
    listing = client.get("/voice/packs", headers=admin_headers).json()
    assert any(p["id"] == pack["id"] for p in listing["packs"])


def test_delete_pack_removes_reference_file(client, tmp_data_dir, admin_headers):
    pack = _create_pack(client, admin_headers)
    _upload(client, admin_headers, pack["id"])
    assert list(Path("data/voice_refs").iterdir())

    client.delete(f"/voice/packs/{pack['id']}", headers=admin_headers)
    assert not list(Path("data/voice_refs").iterdir())


# ============================================================
# 角色绑定
# ============================================================

def test_bind_pack_to_character(client, tmp_data_dir, admin_headers, bindings_file):
    pack = _create_pack(client, admin_headers)
    r = client.post("/voice/bindings",
                    json={"character_id": "linwan", "pack_id": pack["id"]},
                    headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.json()["effective"]["source"] == "pack"
    assert r.json()["effective"]["voice_name"] == pack["voice_name"]

    assert json.loads(bindings_file.read_text(encoding="utf-8")) == {"linwan": pack["id"]}


def test_unbind_falls_back_to_legacy(client, tmp_data_dir, admin_headers):
    pack = _create_pack(client, admin_headers)
    client.post("/voice/bindings",
                json={"character_id": "linwan", "pack_id": pack["id"]},
                headers=admin_headers)

    r = client.post("/voice/bindings",
                    json={"character_id": "linwan", "pack_id": None},
                    headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.json()["effective"]["source"] == "legacy"


def test_bind_unknown_pack_404(client, tmp_data_dir, admin_headers):
    r = client.post("/voice/bindings",
                    json={"character_id": "linwan", "pack_id": "vp_deadbeef"},
                    headers=admin_headers)
    assert r.status_code == 404, r.text


def test_bind_unknown_character_404(client, tmp_data_dir, admin_headers):
    pack = _create_pack(client, admin_headers)
    r = client.post("/voice/bindings",
                    json={"character_id": "no_such_char", "pack_id": pack["id"]},
                    headers=admin_headers)
    assert r.status_code == 404, r.text


def test_bind_blank_character_400(client, tmp_data_dir, admin_headers):
    pack = _create_pack(client, admin_headers)
    r = client.post("/voice/bindings",
                    json={"character_id": "  ", "pack_id": pack["id"]},
                    headers=admin_headers)
    assert r.status_code == 400, r.text


def test_delete_pack_unbinds_characters(client, tmp_data_dir, admin_headers):
    """删包不能留下悬空绑定"""
    pack = _create_pack(client, admin_headers)
    client.post("/voice/bindings",
                json={"character_id": "linwan", "pack_id": pack["id"]},
                headers=admin_headers)

    r = client.delete(f"/voice/packs/{pack['id']}", headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.json()["unbound"] == ["linwan"]

    listing = client.get("/voice/packs", headers=admin_headers).json()
    linwan = next(b for b in listing["bindings"] if b["character_id"] == "linwan")
    assert linwan["pack_id"] is None
    assert linwan["effective_source"] == "legacy"


def test_list_packs_shows_effective_binding_for_each_character(client, tmp_data_dir, admin_headers):
    pack = _create_pack(client, admin_headers, name="林婉专用")
    client.post("/voice/bindings",
                json={"character_id": "linwan", "pack_id": pack["id"]},
                headers=admin_headers)

    listing = client.get("/voice/packs", headers=admin_headers).json()
    linwan = next(b for b in listing["bindings"] if b["character_id"] == "linwan")
    assert linwan["effective_pack_name"] == "林婉专用"
    assert linwan["effective_voice"] == pack["voice_name"]
    assert linwan["character_name"]


# ============================================================
# 试听
# ============================================================

@pytest.fixture
def fake_synth(monkeypatch):
    """把真正的合成换掉 —— 单测不该打网络（edge-tts 是云端服务）。"""
    from funcation.voice_service import voice_service

    calls = []

    async def _fake(text, voice):
        calls.append({"text": text, "voice": voice})
        return b"ID3fake-audio-bytes"

    monkeypatch.setattr(voice_service, "synthesize", _fake)
    return calls


def test_preview_with_saved_pack(client, tmp_data_dir, admin_headers, fake_synth):
    pack = _create_pack(client, admin_headers, speaking_rate=1.2, pitch=3.0)
    r = client.post("/voice/preview", json={"pack_id": pack["id"]}, headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("audio/")
    assert r.content == b"ID3fake-audio-bytes"

    assert len(fake_synth) == 1
    voice = fake_synth[0]["voice"]
    assert voice.voice_name == pack["voice_name"]
    assert voice.speaking_rate == 1.2
    assert voice.pitch == 3.0


def test_preview_with_inline_params(client, tmp_data_dir, admin_headers, fake_synth):
    """新建语音包时可以先试听还没保存的配置"""
    r = client.post("/voice/preview",
                    json={"voice_name": "zh-CN-YunxiNeural", "speaking_rate": 0.8},
                    headers=admin_headers)
    assert r.status_code == 200, r.text
    assert fake_synth[0]["voice"].voice_name == "zh-CN-YunxiNeural"
    assert fake_synth[0]["voice"].speaking_rate == 0.8


def test_preview_uses_default_text(client, tmp_data_dir, admin_headers, fake_synth):
    pack = _create_pack(client, admin_headers)
    client.post("/voice/preview", json={"pack_id": pack["id"]}, headers=admin_headers)
    assert fake_synth[0]["text"]


def test_preview_unknown_pack_404(client, tmp_data_dir, admin_headers, fake_synth):
    r = client.post("/voice/preview", json={"pack_id": "vp_deadbeef"}, headers=admin_headers)
    assert r.status_code == 404, r.text


def test_preview_bad_inline_params_400(client, tmp_data_dir, admin_headers, fake_synth):
    r = client.post("/voice/preview",
                    json={"voice_name": "not-a-voice"},
                    headers=admin_headers)
    assert r.status_code == 400, r.text


def test_preview_engine_error_returns_503(client, tmp_data_dir, admin_headers, monkeypatch):
    """引擎不可用要明确报错，不能返回一段静音让人以为成功了"""
    from funcation.voice_service import TTSEngineError, voice_service

    async def _boom(text, voice):
        raise TTSEngineError("克隆引擎尚未部署")

    monkeypatch.setattr(voice_service, "synthesize", _boom)
    pack = _create_pack(client, admin_headers)

    r = client.post("/voice/preview", json={"pack_id": pack["id"]}, headers=admin_headers)
    assert r.status_code == 503, r.text
    assert "克隆引擎" in r.json()["detail"]


# ============================================================
# 与合成链路的联通（这是整个功能的意义所在）
# ============================================================

def test_bound_pack_actually_changes_character_voice(client, tmp_data_dir, admin_headers):
    """绑了包之后，TTS 解析出来的音色必须真的变成包里的音色。

    这条是"每个角色用自己的语音包"的核心断言 —— 接口都通但合成还在用旧音色，
    才是最容易悄悄发生的失败。
    """
    from funcation.voice_service import voice_service

    before = voice_service.resolve("linwan")
    assert before.source == "legacy"
    assert before.voice_name == "zh-CN-XiaoxiaoNeural"

    pack = _create_pack(client, admin_headers, voice_name="zh-CN-YunxiNeural",
                        speaking_rate=0.85, pitch=-4.0)
    client.post("/voice/bindings",
                json={"character_id": "linwan", "pack_id": pack["id"]},
                headers=admin_headers)

    after = voice_service.resolve("linwan")
    assert after.source == "pack"
    assert after.voice_name == "zh-CN-YunxiNeural"
    assert after.speaking_rate == 0.85
    assert after.pitch == -4.0


def test_unbound_character_keeps_legacy_voice(client, tmp_data_dir, admin_headers):
    from funcation.voice_service import voice_service

    # maid 没被绑过 → 仍然走旧的写死映射，不能被全局默认音色顶掉
    resolved = voice_service.resolve("maid")
    assert resolved.source == "legacy"
    assert resolved.voice_name == "zh-CN-XiaoxueNeural"


def test_pack_update_invalidates_tts_cache(client, tmp_data_dir, admin_headers, fake_synth):
    """改了语音包还放旧音频是典型坑：更新必须清缓存"""
    from funcation.voice_service import voice_service

    pack = _create_pack(client, admin_headers)
    voice_service.cache["sentinel"] = b"stale"

    client.patch(f"/voice/packs/{pack['id']}", json={"pitch": 2.0}, headers=admin_headers)
    assert "sentinel" not in voice_service.cache


# ============================================================
# 编辑已有语音包
# ============================================================

def test_update_pack_keeps_reference_audio(client, tmp_data_dir, admin_headers):
    """编辑（改名 / 调参数）不能把参考音频弄丢。

    这是"只能删了重建"那个设计缺陷的核心风险：删包会连样本一起清掉，
    等于改个名字就要重新录一遍参考音频。
    """
    pack = _create_pack(client, admin_headers)
    _upload(client, admin_headers, pack["id"])
    assert list(Path("data/voice_refs").iterdir())

    r = client.patch(
        f"/voice/packs/{pack['id']}",
        json={"name": "改过名的包", "speaking_rate": 0.8},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()["pack"]
    assert body["name"] == "改过名的包"
    assert body["speaking_rate"] == 0.8
    assert body["has_reference_audio"] is True
    # 文件必须还在原地
    assert list(Path("data/voice_refs").iterdir())


def test_reference_text_round_trip(client, tmp_data_dir, admin_headers):
    """参考音频对应的文本要能存能读 —— 克隆引擎靠它对齐音色"""
    pack = _create_pack(client, admin_headers, reference_text="你好，我是这个声音的主人。")
    assert pack["reference_text"] == "你好，我是这个声音的主人。"

    r = client.patch(
        f"/voice/packs/{pack['id']}",
        json={"reference_text": "换了一句话"},
        headers=admin_headers,
    )
    assert r.json()["pack"]["reference_text"] == "换了一句话"


def test_update_pack_can_switch_engine_and_voice(client, tmp_data_dir, admin_headers):
    pack = _create_pack(client, admin_headers, voice_name="zh-CN-XiaoyiNeural")
    r = client.patch(
        f"/voice/packs/{pack['id']}",
        json={"voice_name": "zh-CN-YunxiNeural", "engine": "clone"},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    updated = r.json()["pack"]
    assert updated["voice_name"] == "zh-CN-YunxiNeural"
    assert updated["engine"] == "clone"
    # 引擎没部署 → UI 要能据此打标记
    assert updated["engine_available"] is False


def test_update_pack_rejects_bad_voice_name(client, tmp_data_dir, admin_headers):
    pack = _create_pack(client, admin_headers)
    r = client.patch(
        f"/voice/packs/{pack['id']}",
        json={"voice_name": "not a voice"},
        headers=admin_headers,
    )
    assert r.status_code == 400, r.text


def test_edited_pack_takes_effect_on_bound_character(client, tmp_data_dir, admin_headers):
    """改完包之后，绑定它的角色解析出来的音色要跟着变（而不是还吃旧值）"""
    from funcation.voice_service import voice_service

    pack = _create_pack(client, admin_headers, voice_name="zh-CN-XiaoyiNeural")
    client.post("/voice/bindings",
                json={"character_id": "linwan", "pack_id": pack["id"]},
                headers=admin_headers)
    assert voice_service.resolve("linwan").voice_name == "zh-CN-XiaoyiNeural"

    client.patch(f"/voice/packs/{pack['id']}",
                 json={"voice_name": "zh-CN-YunjianNeural", "speaking_rate": 1.3},
                 headers=admin_headers)

    after = voice_service.resolve("linwan")
    assert after.voice_name == "zh-CN-YunjianNeural"
    assert after.speaking_rate == 1.3
    assert after.source == "pack"


def test_synthesize_speech_entrypoint_uses_bound_pack(client, tmp_data_dir, admin_headers, fake_synth):
    """锁住语音通话真正走的那条路：`synthesize_speech(text, character_id)`。

    前面测的是 `resolve()`；但通话链路调的是 `synthesize_speech`，
    中间还隔着一层解析和缓存键，必须端到端钉住。
    """
    import asyncio

    from funcation.voice_service import voice_service

    pack = _create_pack(client, admin_headers, voice_name="zh-CN-YunxiNeural", speaking_rate=0.9)
    client.post("/voice/bindings",
                json={"character_id": "linwan", "pack_id": pack["id"]},
                headers=admin_headers)

    voice_service.clear_cache()
    audio = asyncio.run(voice_service.synthesize_speech("你好呀", "linwan"))

    assert audio == b"ID3fake-audio-bytes"
    assert len(fake_synth) == 1
    assert fake_synth[0]["voice"].voice_name == "zh-CN-YunxiNeural"
    assert fake_synth[0]["voice"].speaking_rate == 0.9


def test_synthesize_speech_falls_back_for_unbound_character(client, tmp_data_dir, admin_headers, fake_synth):
    """没绑包的角色仍然走旧的写死映射，不能被全局默认音色顶掉"""
    import asyncio

    from funcation.voice_service import voice_service

    voice_service.clear_cache()
    asyncio.run(voice_service.synthesize_speech("你好呀", "maid"))
    assert fake_synth[0]["voice"].voice_name == "zh-CN-XiaoxueNeural"


def test_synthesize_speech_cache_key_includes_voice(client, tmp_data_dir, admin_headers, fake_synth):
    """换音色必须换缓存键，否则改完语音包还在放旧音频"""
    import asyncio

    from funcation.voice_service import voice_service

    pack = _create_pack(client, admin_headers, voice_name="zh-CN-XiaoyiNeural")
    client.post("/voice/bindings",
                json={"character_id": "linwan", "pack_id": pack["id"]},
                headers=admin_headers)

    voice_service.clear_cache()
    asyncio.run(voice_service.synthesize_speech("同一句话", "linwan"))
    assert len(fake_synth) == 1

    # 同一句话 + 同一角色，但音色变了 → 不能再命中缓存
    client.patch(f"/voice/packs/{pack['id']}", json={"voice_name": "zh-CN-YunjianNeural"},
                 headers=admin_headers)
    asyncio.run(voice_service.synthesize_speech("同一句话", "linwan"))
    assert len(fake_synth) == 2, "换了音色还在命中旧缓存"


# ============================================================
# 编辑已有语音包
# ============================================================

def test_update_pack_keeps_reference_audio(client, tmp_data_dir, admin_headers):
    """编辑（改名 / 调参数）不能把参考音频弄丢。

    这是"只能删了重建"那个设计缺陷的核心风险：删包会连样本一起清掉，
    等于改个名字就要重新录一遍参考音频。
    """
    pack = _create_pack(client, admin_headers)
    _upload(client, admin_headers, pack["id"])
    assert list(Path("data/voice_refs").iterdir())

    r = client.patch(
        f"/voice/packs/{pack['id']}",
        json={"name": "改过名的包", "speaking_rate": 0.8},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()["pack"]
    assert body["name"] == "改过名的包"
    assert body["speaking_rate"] == 0.8
    assert body["has_reference_audio"] is True
    # 文件必须还在原地
    assert list(Path("data/voice_refs").iterdir())


def test_reference_text_round_trip(client, tmp_data_dir, admin_headers):
    """参考音频对应的文本要能存能读 —— 克隆引擎靠它对齐音色"""
    pack = _create_pack(client, admin_headers, reference_text="你好，我是这个声音的主人。")
    assert pack["reference_text"] == "你好，我是这个声音的主人。"

    r = client.patch(
        f"/voice/packs/{pack['id']}",
        json={"reference_text": "换了一句话"},
        headers=admin_headers,
    )
    assert r.json()["pack"]["reference_text"] == "换了一句话"


def test_update_pack_can_switch_engine_and_voice(client, tmp_data_dir, admin_headers):
    pack = _create_pack(client, admin_headers, voice_name="zh-CN-XiaoyiNeural")
    r = client.patch(
        f"/voice/packs/{pack['id']}",
        json={"voice_name": "zh-CN-YunxiNeural", "engine": "clone"},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    updated = r.json()["pack"]
    assert updated["voice_name"] == "zh-CN-YunxiNeural"
    assert updated["engine"] == "clone"
    # 引擎没部署 → UI 要能据此打标记
    assert updated["engine_available"] is False


def test_update_pack_rejects_bad_voice_name(client, tmp_data_dir, admin_headers):
    pack = _create_pack(client, admin_headers)
    r = client.patch(
        f"/voice/packs/{pack['id']}",
        json={"voice_name": "not a voice"},
        headers=admin_headers,
    )
    assert r.status_code == 400, r.text


def test_edited_pack_takes_effect_on_bound_character(client, tmp_data_dir, admin_headers):
    """改完包之后，绑定它的角色解析出来的音色要跟着变（而不是还吃旧值）"""
    from funcation.voice_service import voice_service

    pack = _create_pack(client, admin_headers, voice_name="zh-CN-XiaoyiNeural")
    client.post("/voice/bindings",
                json={"character_id": "linwan", "pack_id": pack["id"]},
                headers=admin_headers)
    assert voice_service.resolve("linwan").voice_name == "zh-CN-XiaoyiNeural"

    client.patch(f"/voice/packs/{pack['id']}",
                 json={"voice_name": "zh-CN-YunjianNeural", "speaking_rate": 1.3},
                 headers=admin_headers)

    after = voice_service.resolve("linwan")
    assert after.voice_name == "zh-CN-YunjianNeural"
    assert after.speaking_rate == 1.3
    assert after.source == "pack"


def test_synthesize_speech_entrypoint_uses_bound_pack(client, tmp_data_dir, admin_headers, fake_synth):
    """锁住语音通话真正走的那条路：`synthesize_speech(text, character_id)`。

    前面测的是 `resolve()`；但通话链路调的是 `synthesize_speech`，
    中间还隔着一层解析和缓存键，必须端到端钉住。
    """
    import asyncio

    from funcation.voice_service import voice_service

    pack = _create_pack(client, admin_headers, voice_name="zh-CN-YunxiNeural", speaking_rate=0.9)
    client.post("/voice/bindings",
                json={"character_id": "linwan", "pack_id": pack["id"]},
                headers=admin_headers)

    voice_service.clear_cache()
    audio = asyncio.run(voice_service.synthesize_speech("你好呀", "linwan"))

    assert audio == b"ID3fake-audio-bytes"
    assert len(fake_synth) == 1
    assert fake_synth[0]["voice"].voice_name == "zh-CN-YunxiNeural"
    assert fake_synth[0]["voice"].speaking_rate == 0.9


def test_synthesize_speech_falls_back_for_unbound_character(client, tmp_data_dir, admin_headers, fake_synth):
    """没绑包的角色仍然走旧的写死映射，不能被全局默认音色顶掉"""
    import asyncio

    from funcation.voice_service import voice_service

    voice_service.clear_cache()
    asyncio.run(voice_service.synthesize_speech("你好呀", "maid"))
    assert fake_synth[0]["voice"].voice_name == "zh-CN-XiaoxueNeural"


def test_synthesize_speech_cache_key_includes_voice(client, tmp_data_dir, admin_headers, fake_synth):
    """换音色必须换缓存键，否则改完语音包还在放旧音频"""
    import asyncio

    from funcation.voice_service import voice_service

    pack = _create_pack(client, admin_headers, voice_name="zh-CN-XiaoyiNeural")
    client.post("/voice/bindings",
                json={"character_id": "linwan", "pack_id": pack["id"]},
                headers=admin_headers)

    voice_service.clear_cache()
    asyncio.run(voice_service.synthesize_speech("同一句话", "linwan"))
    assert len(fake_synth) == 1

    # 同一句话 + 同一角色，但音色变了 → 不能再命中缓存
    client.patch(f"/voice/packs/{pack['id']}", json={"voice_name": "zh-CN-YunjianNeural"},
                 headers=admin_headers)
    asyncio.run(voice_service.synthesize_speech("同一句话", "linwan"))
    assert len(fake_synth) == 2, "换了音色还在命中旧缓存"
