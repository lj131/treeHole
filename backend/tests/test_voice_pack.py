"""语音包纯函数测试：clamp / 校验 / 净化 / 解析链。

不碰 IO、不碰网络 —— 落盘在 voice_store，接口在 test_voice_pack_api。
"""
import pytest

from funcation import voice_pack as vp
from funcation.voice_service import ResolvedVoice, TTSEngineError, VoiceService


# ---------- ID ----------

def test_new_pack_id_format():
    pid = vp.new_pack_id()
    assert vp.is_valid_pack_id(pid)
    assert pid.startswith("vp_") and len(pid) == 11


def test_pack_id_validation_rejects_junk():
    for bad in [None, "", "vp_", "vp_XYZ", "abc12345", "vp_1234567", "vp_123456789", 123]:
        assert not vp.is_valid_pack_id(bad), bad


def test_new_pack_id_is_unique():
    assert len({vp.new_pack_id() for _ in range(200)}) == 200


# ---------- 文本净化 ----------

def test_sanitize_text_strips_control_chars_and_collapses_space():
    assert vp.sanitize_text("  温柔\n\n学姐\x00  ", max_len=40, field="名称") == "温柔 学姐"


def test_sanitize_text_truncates():
    assert len(vp.sanitize_text("啊" * 100, max_len=10, field="名称")) == 10


def test_sanitize_text_required_rejects_blank():
    with pytest.raises(vp.VoicePackError):
        vp.sanitize_text("   ", max_len=10, field="名称", required=True)


def test_sanitize_text_rejects_non_string():
    with pytest.raises(vp.VoicePackError):
        vp.sanitize_text({"a": 1}, max_len=10, field="名称")


def test_sanitize_filename_stem_keeps_chinese_drops_path():
    assert vp.sanitize_filename_stem("../../温柔 学姐") == "温柔_学姐"
    assert vp.sanitize_filename_stem("") == "voice"
    assert "/" not in vp.sanitize_filename_stem("a/b\\c:d")


# ---------- 数值 clamp ----------

def test_clamp_float_bounds():
    assert vp.clamp_float(99, low=0.5, high=2.0, default=1.0, field="语速") == 2.0
    assert vp.clamp_float(0.01, low=0.5, high=2.0, default=1.0, field="语速") == 0.5
    assert vp.clamp_float(None, low=0.5, high=2.0, default=1.0, field="语速") == 1.0


def test_clamp_float_rejects_nan_and_inf():
    for bad in [float("nan"), float("inf"), float("-inf")]:
        with pytest.raises(vp.VoicePackError):
            vp.clamp_float(bad, low=0, high=1, default=0.5, field="音量")


def test_clamp_float_rejects_non_numeric():
    with pytest.raises(vp.VoicePackError):
        vp.clamp_float("大声", low=0, high=1, default=0.5, field="音量")


# ---------- 音色名 / 引擎 ----------

def test_voice_name_validation():
    assert vp.is_valid_voice_name("zh-CN-XiaoxiaoNeural")
    assert vp.is_valid_voice_name("en-US-AriaNeural")
    for bad in ["", "xiaoxiao", "zh-CN-", "../../etc/passwd", None, "zh-CN-X; rm -rf /"]:
        assert not vp.is_valid_voice_name(bad), bad


def test_normalize_voice_name_rejects_injection():
    with pytest.raises(vp.VoicePackError):
        vp.normalize_voice_name("zh-CN-XiaoxiaoNeural'; drop table")


def test_normalize_engine_default_and_reject():
    assert vp.normalize_engine(None) == vp.DEFAULT_ENGINE
    assert vp.normalize_engine("EDGE") == "edge"
    with pytest.raises(vp.VoicePackError):
        vp.normalize_engine("gpt-sovits")


# ---------- 上传校验 ----------

def test_validate_ref_upload_accepts_audio():
    assert vp.validate_ref_upload("sample.WAV", "audio/wav") == ".wav"
    assert vp.validate_ref_upload("a.mp3", "audio/mpeg") == ".mp3"


def test_validate_ref_upload_allows_octet_stream_by_ext():
    """有些浏览器上传时 content_type 是 octet-stream，后缀对就该放行"""
    assert vp.validate_ref_upload("a.wav", "application/octet-stream") == ".wav"


def test_validate_ref_upload_rejects_bad_ext_and_type():
    with pytest.raises(vp.VoicePackError):
        vp.validate_ref_upload("evil.exe", "application/octet-stream")
    with pytest.raises(vp.VoicePackError):
        vp.validate_ref_upload("noext", "audio/wav")
    with pytest.raises(vp.VoicePackError):
        vp.validate_ref_upload("a.wav", "text/html")


# ---------- normalize_pack ----------

def test_normalize_pack_defaults():
    pack = vp.normalize_pack({"name": "默认"})
    assert vp.is_valid_pack_id(pack["id"])
    assert pack["engine"] == "edge"
    assert pack["voice_name"] == vp.FALLBACK_VOICE
    assert pack["speaking_rate"] == 1.0
    assert pack["pitch"] == 0.0
    assert pack["volume"] == 1.0
    assert pack["reference_audio"] is None


def test_normalize_pack_clamps_out_of_range():
    pack = vp.normalize_pack({
        "name": "越界",
        "speaking_rate": 99,
        "pitch": -999,
        "volume": 50,
    })
    assert pack["speaking_rate"] == vp.RATE_MAX
    assert pack["pitch"] == vp.PITCH_MIN
    assert pack["volume"] == vp.VOLUME_MAX


def test_normalize_pack_requires_name():
    with pytest.raises(vp.VoicePackError):
        vp.normalize_pack({"name": "  "})


def test_normalize_pack_rejects_non_dict():
    with pytest.raises(vp.VoicePackError):
        vp.normalize_pack([1, 2, 3])


def test_normalize_pack_patch_keeps_untouched_fields():
    """PATCH 语义：只改传入的字段，其余沿用旧值"""
    original = vp.normalize_pack({"name": "旧名字", "voice_name": "zh-CN-YunxiNeural", "pitch": 8.0})
    patched = vp.normalize_pack({"name": "新名字"}, pack_id=original["id"], existing=original)

    assert patched["name"] == "新名字"
    assert patched["voice_name"] == "zh-CN-YunxiNeural"  # 没传 → 保持
    assert patched["pitch"] == 8.0
    assert patched["id"] == original["id"]


def test_normalize_pack_patch_keeps_reference_audio():
    """参考音频由上传接口写入，普通更新不能把它抹掉"""
    original = vp.normalize_pack({"name": "带样本"})
    original["reference_audio"] = "data/voice_refs/vp_aaaaaaaa.wav"
    patched = vp.normalize_pack({"description": "改个描述"}, pack_id=original["id"], existing=original)
    assert patched["reference_audio"] == "data/voice_refs/vp_aaaaaaaa.wav"


# ---------- 摘要 ----------

def test_summarize_pack_marks_reference():
    pack = vp.normalize_pack({"name": "有样本"})
    assert vp.summarize_pack(pack)["has_reference_audio"] is False
    pack["reference_audio"] = "data/voice_refs/x.wav"
    assert vp.summarize_pack(pack)["has_reference_audio"] is True


# ---------- 解析链 ----------

def _pack(name, voice, pid=None):
    pack = vp.normalize_pack({"name": name, "voice_name": voice}, pack_id=pid)
    return pack


def test_resolve_prefers_bound_pack():
    pack = _pack("温柔", "zh-CN-XiaoyiNeural")
    cfg = vp.resolve_voice_config(
        character_id="linwan", packs=[pack], bindings={"linwan": pack["id"]}
    )
    assert cfg["source"] == "pack"
    assert cfg["voice_name"] == "zh-CN-XiaoyiNeural"
    assert cfg["pack_id"] == pack["id"]


def test_resolve_falls_back_to_legacy_map():
    cfg = vp.resolve_voice_config(character_id="linwan", packs=[], bindings={})
    assert cfg["source"] == "legacy"
    assert cfg["voice_name"] == vp.LEGACY_CHARACTER_VOICES["linwan"]


def test_resolve_falls_back_to_global_default_for_unknown_character():
    cfg = vp.resolve_voice_config(character_id="someone_new", packs=[], bindings={})
    assert cfg["source"] == "default"
    assert cfg["voice_name"] == vp.FALLBACK_VOICE


def test_resolve_ignores_dangling_binding():
    """绑定指向一个已被删掉的包 → 不能炸，按 legacy 走"""
    cfg = vp.resolve_voice_config(
        character_id="linwan", packs=[], bindings={"linwan": "vp_deadbeef"}
    )
    assert cfg["source"] == "legacy"


def test_find_pack_handles_none():
    assert vp.find_pack([], None) is None
    assert vp.find_pack([], "vp_deadbeef") is None


# ---------- 删包后的绑定清理 ----------

def test_prune_bindings_removes_dangling():
    keep = _pack("留", "zh-CN-XiaoyiNeural")
    bindings = {"linwan": keep["id"], "maid": "vp_deadbeef"}
    assert vp.prune_bindings(bindings, [keep]) == {"linwan": keep["id"]}


def test_prune_bindings_noop_when_all_valid():
    a = _pack("A", "zh-CN-XiaoyiNeural")
    b = _pack("B", "zh-CN-YunxiNeural")
    bindings = {"linwan": a["id"], "maid": b["id"]}
    assert vp.prune_bindings(bindings, [a, b]) == bindings


# ---------- 限额 ----------

def test_max_ref_bytes_matches_mb_constant():
    assert vp.max_ref_bytes() == vp.VOICE_REF_MAX_MB * 1024 * 1024


def test_ext_of():
    assert vp.ext_of("a/b/c.WAV") == ".wav"
    assert vp.ext_of("noext") == ""
    assert vp.ext_of(None) == ""


# ---------- 云端重试 ----------

def test_edge_synth_retries_on_transient_failure(monkeypatch):
    """edge-tts 云端会偶发 NoAudioReceived：第一次失败必须重试，不能直接静默丢这一句。

    实测同一段文本同一组参数连打 4 次可能挂 2 次 —— 不重试的话语音通话里
    角色就只是"张了张嘴"没声音。
    """
    import asyncio
    import sys
    import types

    from funcation.voice_service import VoiceService

    calls = {"n": 0}

    class _FakeCommunicate:
        def __init__(self, **_kw):
            pass

        async def stream(self):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("No audio was received.")
            yield {"type": "audio", "data": b"mp3-bytes"}

    fake_mod = types.SimpleNamespace(Communicate=_FakeCommunicate)
    monkeypatch.setitem(sys.modules, "edge_tts", fake_mod)
    # 别在测试里真等退避
    monkeypatch.setattr("funcation.voice_service._EDGE_RETRY_DELAY", 0)

    svc = VoiceService()
    voice = ResolvedVoice(voice_name="zh-CN-XiaoxiaoNeural")
    audio = asyncio.run(svc.synthesize("你好", voice))

    assert audio == b"mp3-bytes"
    assert calls["n"] == 2, "第一次失败后应该重试一次就成功"


def test_edge_synth_gives_up_after_all_attempts(monkeypatch):
    """重试到底还是失败 → 抛 TTSEngineError（带上尝试次数），绝不返回空音频"""
    import asyncio
    import sys
    import types

    from funcation.voice_service import TTSEngineError, VoiceService

    calls = {"n": 0}

    class _AlwaysFail:
        def __init__(self, **_kw):
            pass

        async def stream(self):
            calls["n"] += 1
            raise RuntimeError("No audio was received.")
            yield  # pragma: no cover - 让它是个生成器

    monkeypatch.setitem(sys.modules, "edge_tts", types.SimpleNamespace(Communicate=_AlwaysFail))
    monkeypatch.setattr("funcation.voice_service._EDGE_RETRY_DELAY", 0)

    svc = VoiceService()
    voice = ResolvedVoice(voice_name="zh-CN-XiaoxiaoNeural")
    with pytest.raises(TTSEngineError) as exc:
        asyncio.run(svc.synthesize("你好", voice))

    assert "重试" in str(exc.value)
    assert calls["n"] == 3


def test_clone_engine_reports_not_deployed(monkeypatch):
    """选了克隆引擎但没部署 → 明确报错，不静默退回别的音色"""
    import asyncio

    from funcation.voice_service import TTSEngineError, VoiceService

    svc = VoiceService()
    voice = ResolvedVoice(engine="clone", reference_audio="data/voice_refs/x.wav")
    with pytest.raises(TTSEngineError) as exc:
        asyncio.run(svc.synthesize("你好", voice))
    assert "克隆引擎尚未部署" in str(exc.value)


def test_clone_engine_without_reference_audio(monkeypatch):
    import asyncio

    from funcation.voice_service import TTSEngineError, VoiceService

    svc = VoiceService()
    with pytest.raises(TTSEngineError) as exc:
        asyncio.run(svc.synthesize("你好", ResolvedVoice(engine="clone")))
    assert "没有参考音频" in str(exc.value)


def test_unknown_engine_rejected():
    import asyncio

    from funcation.voice_service import TTSEngineError, VoiceService

    svc = VoiceService()
    with pytest.raises(TTSEngineError):
        asyncio.run(svc.synthesize("你好", ResolvedVoice(engine="gpt-sovits")))


# ---------- 缓存指纹 ----------

def test_voice_fingerprint_changes_with_params():
    """改了音色/语速必须换缓存键，否则会继续放旧音频"""
    from funcation.voice_service import ResolvedVoice

    a = ResolvedVoice(voice_name="zh-CN-XiaoxiaoNeural", speaking_rate=1.0)
    b = ResolvedVoice(voice_name="zh-CN-XiaoxiaoNeural", speaking_rate=1.2)
    c = ResolvedVoice(voice_name="zh-CN-YunxiNeural", speaking_rate=1.0)
    assert a.fingerprint() != b.fingerprint()
    assert a.fingerprint() != c.fingerprint()
    assert a.fingerprint() == ResolvedVoice(voice_name="zh-CN-XiaoxiaoNeural").fingerprint()


def test_engine_availability():
    """UI 靠它给语音包打「引擎未部署」标记，不能撒谎"""
    from funcation.voice_service import VoiceService

    svc = VoiceService()
    assert svc.engine_available("edge") is True
    assert svc.engine_available("clone") is False
    assert svc.engine_available("nope") is False


def test_normalize_pack_reads_reference_text_from_input():
    """reference_text 是普通文本字段，必须从**入参**读。

    踩过的坑：把它和「只由上传接口写入」的 reference_audio 一样写成 base.get()，
    结果创建时永远是空、更新时改不动 —— 而克隆引擎恰恰要靠这段文本对齐音色。
    """
    pack = vp.normalize_pack({"name": "x", "reference_text": "你好，我是这个声音的主人。"})
    assert pack["reference_text"] == "你好，我是这个声音的主人。"


def test_normalize_pack_patch_updates_reference_text():
    original = vp.normalize_pack({"name": "x", "reference_text": "旧文本"})
    patched = vp.normalize_pack({"reference_text": "新文本"}, pack_id=original["id"], existing=original)
    assert patched["reference_text"] == "新文本"


def test_normalize_pack_patch_keeps_reference_text_when_omitted():
    original = vp.normalize_pack({"name": "x", "reference_text": "别弄丢我"})
    patched = vp.normalize_pack({"name": "y"}, pack_id=original["id"], existing=original)
    assert patched["reference_text"] == "别弄丢我"


def test_normalize_pack_reference_text_is_sanitized_and_truncated():
    pack = vp.normalize_pack({"name": "x", "reference_text": "  多  空格\x00  "})
    assert pack["reference_text"] == "多 空格"
    assert len(vp.normalize_pack({"name": "x", "reference_text": "啊" * 900})["reference_text"]) == vp.REF_TEXT_MAX


def test_normalize_pack_reads_reference_text_from_input():
    """reference_text 是普通文本字段，必须从**入参**读。

    踩过的坑：把它和「只由上传接口写入」的 reference_audio 一样写成 base.get()，
    结果创建时永远是空、更新时改不动 —— 而克隆引擎恰恰要靠这段文本对齐音色。
    """
    pack = vp.normalize_pack({"name": "x", "reference_text": "你好，我是这个声音的主人。"})
    assert pack["reference_text"] == "你好，我是这个声音的主人。"


def test_normalize_pack_patch_updates_reference_text():
    original = vp.normalize_pack({"name": "x", "reference_text": "旧文本"})
    patched = vp.normalize_pack({"reference_text": "新文本"}, pack_id=original["id"], existing=original)
    assert patched["reference_text"] == "新文本"


def test_normalize_pack_patch_keeps_reference_text_when_omitted():
    original = vp.normalize_pack({"name": "x", "reference_text": "别弄丢我"})
    patched = vp.normalize_pack({"name": "y"}, pack_id=original["id"], existing=original)
    assert patched["reference_text"] == "别弄丢我"


def test_normalize_pack_reference_text_is_sanitized_and_truncated():
    pack = vp.normalize_pack({"name": "x", "reference_text": "  多  空格\x00  "})
    assert pack["reference_text"] == "多 空格"
    assert len(vp.normalize_pack({"name": "x", "reference_text": "啊" * 900})["reference_text"]) == vp.REF_TEXT_MAX
