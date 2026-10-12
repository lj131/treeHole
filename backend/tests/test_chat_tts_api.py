"""聊天页朗读：POST /chat/tts。

真实的合成实现要打 edge-tts 云端（而且该端点目前上游 403），所以这里全部 mock ——
单测不该依赖网络，也不该因为上游故障而变红。
"""
import uuid

import pytest


def _unique(prefix="user"):
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


@pytest.fixture
def admin_token(client):
    r = client.post("/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture
def user_headers(client, admin_token):
    """已审批的**普通用户** —— 朗读是用户功能，不是管理员功能"""
    name = _unique()
    pwd = "pass1234"
    reg = client.post("/auth/register", json={"username": name, "password": pwd})
    assert reg.status_code == 200, reg.text
    uid = reg.json()["user"]["id"]
    client.post(f"/auth/admin/approve/{uid}",
                headers={"Authorization": f"Bearer {admin_token}"})
    lg = client.post("/auth/login", json={"username": name, "password": pwd})
    assert lg.status_code == 200, lg.text
    return {"Authorization": f"Bearer {lg.json()['token']}"}


@pytest.fixture
def fake_synth(monkeypatch):
    """把真实合成换掉，记录收到的参数"""
    from funcation.voice_service import voice_service

    calls = []

    async def _fake(text, character_id, config=None):
        calls.append({"text": text, "character_id": character_id})
        return b"ID3fake-mp3"

    monkeypatch.setattr(voice_service, "synthesize_speech", _fake)
    return calls


# ============================================================
# 正常路径
# ============================================================

def test_tts_returns_audio(client, tmp_data_dir, user_headers, fake_synth):
    r = client.post("/chat/tts", json={"text": "你好呀"}, headers=user_headers)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("audio/")
    assert r.content == b"ID3fake-mp3"


def test_tts_uses_current_character_when_not_given(client, tmp_data_dir, user_headers, fake_synth):
    """不传 character_id 时要落到当前角色，而不是空字符串"""
    client.post("/chat/tts", json={"text": "你好呀"}, headers=user_headers)
    assert fake_synth[0]["character_id"], "character_id 不能为空"


def test_tts_respects_explicit_character(client, tmp_data_dir, user_headers, fake_synth):
    client.post("/chat/tts", json={"text": "你好呀", "character_id": "maid"},
                headers=user_headers)
    assert fake_synth[0]["character_id"] == "maid"


def test_tts_passes_text_through(client, tmp_data_dir, user_headers, fake_synth):
    client.post("/chat/tts", json={"text": "  你好呀  "}, headers=user_headers)
    assert fake_synth[0]["text"] == "你好呀", "首尾空白要去掉再合成"


# ============================================================
# 入参校验
# ============================================================

def test_tts_rejects_empty_text(client, tmp_data_dir, user_headers, fake_synth):
    r = client.post("/chat/tts", json={"text": "   "}, headers=user_headers)
    assert r.status_code == 400, r.text
    assert not fake_synth, "空文本不该触发合成"


def test_tts_rejects_overlong_text(client, tmp_data_dir, user_headers, fake_synth):
    """长文本既慢又占缓存，超限直接拒绝（前端会先截断）"""
    from funcation import voice_pack

    r = client.post(
        "/chat/tts",
        json={"text": "啊" * (voice_pack.MAX_SYNTH_CHARS + 1)},
        headers=user_headers,
    )
    assert r.status_code == 400, r.text
    assert str(voice_pack.MAX_SYNTH_CHARS) in r.json()["detail"]
    assert not fake_synth


def test_tts_accepts_text_at_limit(client, tmp_data_dir, user_headers, fake_synth):
    """边界值要能过（别把上限写成开区间）"""
    from funcation import voice_pack

    r = client.post(
        "/chat/tts",
        json={"text": "啊" * voice_pack.MAX_SYNTH_CHARS},
        headers=user_headers,
    )
    assert r.status_code == 200, r.text


def test_tts_unknown_character_404(client, tmp_data_dir, user_headers, fake_synth):
    r = client.post("/chat/tts", json={"text": "你好", "character_id": "no_such_char"},
                    headers=user_headers)
    assert r.status_code == 404, r.text


# ============================================================
# 引擎故障
# ============================================================

def test_tts_engine_failure_returns_503(client, tmp_data_dir, user_headers, monkeypatch):
    """引擎不可用要明确报错 —— 绝不能返回一段静音让人以为成功了。

    edge-tts 的合成端点目前上游 403，这条路径是真实会被走到的。
    """
    from funcation.voice_service import TTSEngineError, voice_service

    async def _boom(text, character_id, config=None):
        raise TTSEngineError("edge-tts 合成失败（已重试 3 次）")

    monkeypatch.setattr(voice_service, "synthesize_speech", _boom)
    r = client.post("/chat/tts", json={"text": "你好"}, headers=user_headers)
    assert r.status_code == 503, r.text
    assert "edge-tts" in r.json()["detail"]


def test_tts_clone_engine_reports_not_deployed(client, tmp_data_dir, user_headers, monkeypatch):
    """绑了未部署的克隆引擎 → 明确报错，不静默换音色"""
    from funcation.voice_service import TTSEngineError, voice_service

    async def _boom(text, character_id, config=None):
        raise TTSEngineError("克隆引擎尚未部署")

    monkeypatch.setattr(voice_service, "synthesize_speech", _boom)
    r = client.post("/chat/tts", json={"text": "你好"}, headers=user_headers)
    assert r.status_code == 503, r.text
    assert "克隆引擎" in r.json()["detail"]


# ============================================================
# 权限
# ============================================================

def test_tts_requires_auth(client, tmp_data_dir):
    r = client.post("/chat/tts", json={"text": "你好"})
    assert r.status_code in (401, 403), r.text


def test_tts_is_not_admin_only(client, tmp_data_dir, user_headers, fake_synth):
    """朗读是用户功能 —— 普通用户必须能用（别照抄 /voice/preview 的管理员门）"""
    r = client.post("/chat/tts", json={"text": "你好"}, headers=user_headers)
    assert r.status_code == 200, f"普通用户被拒了：{r.status_code} {r.text}"
