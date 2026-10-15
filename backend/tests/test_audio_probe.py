"""参考音频时长探测（尽力而为，不引依赖）。"""
import math
import struct
import wave

import pytest

from funcation import audio_probe


def _make_wav(path, seconds: float, rate: int = 16000):
    """造一个真实 WAV（单声道 16bit 静音），返回路径"""
    frames = int(rate * seconds)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * frames)
    return str(path)


# ── WAV 能读 ────────────────────────────────────────────────

def test_reads_wav_duration(tmp_path):
    path = _make_wav(tmp_path / "a.wav", 8.0)
    assert audio_probe.probe_duration_seconds(path) == pytest.approx(8.0, abs=0.05)


def test_reads_short_wav(tmp_path):
    path = _make_wav(tmp_path / "b.wav", 2.0)
    assert audio_probe.probe_duration_seconds(path) == pytest.approx(2.0, abs=0.05)


# ── 读不出来不能抛，也不能谎报 ──────────────────────────────

def test_non_wav_returns_none(tmp_path):
    """mp3 之类：返回 None（不知道），绝不抛"""
    p = tmp_path / "c.mp3"
    p.write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 200)
    assert audio_probe.probe_duration_seconds(str(p)) is None


def test_missing_file_returns_none(tmp_path):
    assert audio_probe.probe_duration_seconds(str(tmp_path / "nope.wav")) is None


def test_corrupt_wav_returns_none(tmp_path):
    p = tmp_path / "bad.wav"
    p.write_bytes(b"RIFF____WAVEjunk")
    assert audio_probe.probe_duration_seconds(str(p)) is None


def test_empty_file_returns_none(tmp_path):
    p = tmp_path / "empty.wav"
    p.write_bytes(b"")
    assert audio_probe.probe_duration_seconds(str(p)) is None


# ── 警告语义 ────────────────────────────────────────────────

def test_short_audio_warns():
    w = audio_probe.duration_warning(2.0)
    assert w and "偏短" in w and audio_probe.VOICE_REF_HINT in w


def test_good_audio_no_warning():
    assert audio_probe.duration_warning(8.0) is None


def test_unknown_duration_never_warns():
    """**关键**：读不出来（None）绝不能报警 —— 否则用户传 mp3 也看到红色警告"""
    assert audio_probe.duration_warning(None) is None


def test_boundary_value():
    """正好等于阈值不算短"""
    assert audio_probe.duration_warning(audio_probe.VOICE_REF_MIN_SECONDS) is None
    assert audio_probe.duration_warning(audio_probe.VOICE_REF_MIN_SECONDS - 0.01) is not None
