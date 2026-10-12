"""edge-tts 上游变更的兼容层。

**2026-10 起微软对旧合成主机返回 403**（按地区分批切换，10-12 轮到美国），
edge-tts 7.2.8 仍指向旧主机 → 合成全线失败。这里锁住修复，避免以后被改回去。

不打真实网络：只验证"URL 被换掉了"和"日期解析不依赖 locale"。
"""
import locale
from datetime import timezone

import pytest

from funcation import edge_tts_compat


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    """每个用例都从"未应用"开始"""
    edge_tts_compat.reset_for_tests()
    monkeypatch.delenv("EDGE_TTS_LEGACY_HOST", raising=False)
    yield
    edge_tts_compat.reset_for_tests()


def _legacy_url() -> str:
    """把 communicate 上的 WSS_URL 还原成旧主机，模拟"未修复"状态"""
    import edge_tts.communicate as comm
    from edge_tts.constants import TRUSTED_CLIENT_TOKEN

    comm.WSS_URL = (
        "wss://speech.platform.bing.com/consumer/speech/synthesize/readaloud/edge/v1"
        f"?TrustedClientToken={TRUSTED_CLIENT_TOKEN}"
    )
    return comm.WSS_URL


# ============================================================
# 端点切换
# ============================================================

def test_apply_switches_to_new_host():
    """核心断言：合成端点必须指向新主机"""
    import edge_tts.communicate as comm

    _legacy_url()
    assert edge_tts_compat.apply() is True
    assert "api.msedgeservices.com" in comm.WSS_URL
    assert "speech.platform.bing.com" not in comm.WSS_URL


def test_apply_uses_subscription_key_param():
    """新主机接受同一个 legacy token，但参数名是 Ocp-Apim-Subscription-Key"""
    import edge_tts.communicate as comm
    from edge_tts.constants import TRUSTED_CLIENT_TOKEN

    _legacy_url()
    edge_tts_compat.apply()
    assert "Ocp-Apim-Subscription-Key=" in comm.WSS_URL
    assert TRUSTED_CLIENT_TOKEN in comm.WSS_URL
    # 旧参数名在新主机上不被接受
    assert "TrustedClientToken=" not in comm.WSS_URL


def test_apply_must_patch_communicate_not_constants():
    """`communicate` 是 `from .constants import WSS_URL` —— 改 constants 不生效。

    这条是踩过的坑：只改 constants 的话，`Communicate` 用的还是旧 URL，
    看起来"改了"但完全没效果。
    """
    import edge_tts.communicate as comm

    _legacy_url()
    edge_tts_compat.apply()
    assert "api.msedgeservices.com" in comm.WSS_URL


def test_apply_is_idempotent():
    """重复调用不该出问题，第二次应返回 False（没做改动）"""
    import edge_tts.communicate as comm

    _legacy_url()
    assert edge_tts_compat.apply() is True
    first = comm.WSS_URL
    assert edge_tts_compat.apply() is False
    assert comm.WSS_URL == first


def test_apply_skips_when_upstream_already_fixed():
    """上游将来自己修好后，兼容层不该把 URL 改回去"""
    import edge_tts.communicate as comm

    comm.WSS_URL = f"wss://{edge_tts_compat.NEW_WSS_HOST}?Ocp-Apim-Subscription-Key=x"
    assert edge_tts_compat.apply() is False
    assert "api.msedgeservices.com" in comm.WSS_URL


def test_legacy_host_escape_hatch(monkeypatch):
    """万一某些地区旧主机仍可用，要能一键退回"""
    import edge_tts.communicate as comm

    legacy = _legacy_url()
    monkeypatch.setenv("EDGE_TTS_LEGACY_HOST", "1")
    assert edge_tts_compat.apply() is False
    assert comm.WSS_URL == legacy


# ============================================================
# 日期解析（上游 #491 的第二个修复）
# ============================================================

def test_date_parsing_is_locale_independent():
    """HTTP 日期的星期/月份名永远是英文，不能跟着进程 locale 走。

    实测本机（中文 Windows）切到系统 locale 后，上游的 strptime 实现返回 None ——
    于是"时钟偏移自动校正"失效，真 403 会被 SkewAdjustmentError 盖住，排查时看不到真因。
    """
    from edge_tts.drm import DRM

    edge_tts_compat.apply()

    original = locale.getlocale()
    try:
        # 切到中文 locale（本机的系统 locale）
        locale.setlocale(locale.LC_ALL, "Chinese (Simplified)_China")
    except locale.Error:
        pytest.skip("本机不支持中文 locale，跳过")

    try:
        assert DRM.parse_rfc2616_date("Mon, 12 Oct 2026 03:16:09 GMT") is not None
    finally:
        locale.setlocale(locale.LC_ALL, original)


def test_date_parsing_accepts_numeric_zone():
    """上游的 strptime 格式读不了 `+0000` 这种数字时区"""
    from edge_tts.drm import DRM

    edge_tts_compat.apply()
    assert DRM.parse_rfc2616_date("Mon, 12 Oct 2026 03:16:09 +0000") is not None


def test_date_parsing_returns_none_on_garbage():
    """坏输入要返回 None，不能抛 —— 上游调用方靠 None 判断"解析失败" """
    from edge_tts.drm import DRM

    edge_tts_compat.apply()
    assert DRM.parse_rfc2616_date("") is None
    assert DRM.parse_rfc2616_date("not a date") is None


def test_date_without_zone_treated_as_utc():
    from datetime import datetime

    from edge_tts.drm import DRM

    edge_tts_compat.apply()
    ts = DRM.parse_rfc2616_date("Mon, 12 Oct 2026 03:16:09")
    expected = datetime(2026, 10, 12, 3, 16, 9, tzinfo=timezone.utc).timestamp()
    assert ts == expected


# ============================================================
# 真实合成（打网络；失败只警告不红，避免上游再变时把 CI 打挂）
# ============================================================

def test_real_synthesis_works():
    """端到端：兼容层生效后能真的合成出音频。

    这是**唯一**打网络的用例。上游若再次变更，这里会失败 ——
    但那条信息很有价值，所以保留为**显式跳过**而不是静默忽略：
    设 SKIP_EDGE_TTS_NETWORK=1 可跳过。
    """
    import asyncio
    import os

    if os.getenv("SKIP_EDGE_TTS_NETWORK") == "1":
        pytest.skip("SKIP_EDGE_TTS_NETWORK=1")

    edge_tts_compat.apply()

    async def _run() -> int:
        import edge_tts

        comm = edge_tts.Communicate("测试", "zh-CN-XiaoxiaoNeural")
        total = 0
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                total += len(chunk["data"])
        return total

    try:
        total = asyncio.run(asyncio.wait_for(_run(), timeout=30))
    except Exception as e:  # noqa: BLE001 - 上游故障不该把单测打红
        pytest.skip(f"edge-tts 云端不可用（上游问题，非本项目代码）：{type(e).__name__}")

    assert total > 0, "合成成功但没拿到音频字节"
