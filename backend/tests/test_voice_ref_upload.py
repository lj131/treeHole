"""参考音频上传接口：落盘校验 + 时长警告。"""
import io
import wave

import pytest


def _wav_bytes(seconds: float, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


@pytest.fixture
def a_pack(client, tmp_data_dir, admin_headers):
    """建一个空语音包，返回 pack_id"""
    r = client.post(
        "/voice/packs",
        json={"name": "参考音频测试包", "engine": "clone"},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    return r.json()["pack"]["id"]


def test_upload_short_wav_returns_warning(client, tmp_data_dir, admin_headers, a_pack):
    """短 WAV → 上传成功**且**带 warning（警告不阻断）"""
    r = client.post(
        f"/voice/packs/{a_pack}/reference",
        files={"file": ("ref.wav", _wav_bytes(2.0), "audio/wav")},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["duration_seconds"] == pytest.approx(2.0, abs=0.1)
    assert body["warning"] and "偏短" in body["warning"]


def test_upload_long_wav_no_warning(client, tmp_data_dir, admin_headers, a_pack):
    r = client.post(
        f"/voice/packs/{a_pack}/reference",
        files={"file": ("ref.wav", _wav_bytes(8.0), "audio/wav")},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["warning"] is None
    assert r.json()["duration_seconds"] == pytest.approx(8.0, abs=0.1)


def test_upload_mp3_duration_unknown_not_warned(client, tmp_data_dir, admin_headers, a_pack):
    """mp3 读不出时长 → duration_seconds=None 且**不报警**（不误导用户）"""
    r = client.post(
        f"/voice/packs/{a_pack}/reference",
        files={"file": ("ref.mp3", b"\xff\xfb\x90\x00" + b"\x00" * 500, "audio/mpeg")},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["duration_seconds"] is None
    assert body["warning"] is None


def test_upload_rejects_bad_extension(client, tmp_data_dir, admin_headers, a_pack):
    """格式校验仍然拦得住"""
    r = client.post(
        f"/voice/packs/{a_pack}/reference",
        files={"file": ("ref.txt", b"hello", "text/plain")},
        headers=admin_headers,
    )
    assert r.status_code == 400
    assert "不支持" in r.json()["detail"]
