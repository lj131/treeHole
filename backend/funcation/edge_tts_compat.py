"""edge-tts 上游变更的兼容层（**临时**，等上游发版后可删）。

## 背景：为什么"之前能用，现在不行"

**2026-10 起 `speech.platform.bing.com` 对合成 WebSocket 返回 403。**
微软把语音合成后端迁到了新主机，**按地区分批切换**：

- 先是"许多国家"（2026-10 初）
- **2026-10-12 轮到美国**

edge-tts 7.2.8（当前最新版）仍然指向旧主机，所以合成全线失败 —— 与本项目代码、
网络、代理、系统时钟**都无关**（这些都实测排除过）。

**最容易走错的一步**：旧主机**仍在正常提供音色列表**（`VOICE_LIST`），只有合成被拒。
于是症状看起来像"HTTPS 通、WSS 403"，很容易被误判成鉴权或代理问题。
上游记录见 rany2/edge-tts#490、修复方案见 #491。

## 做法

上游 PR #491 的修法：新主机 `api.msedgeservices.com` **接受同一个 legacy token**，
但要作为 `Ocp-Apim-Subscription-Key` 传。这里在导入时把 URL 指过去。

**关键细节**：`edge_tts/communicate.py` 是 `from .constants import WSS_URL`，
所以**必须改 `edge_tts.communicate.WSS_URL`**，改 `edge_tts.constants.WSS_URL` 不生效。

顺带修 `DRM.parse_rfc2616_date`：它用 `strptime("%a, %d %b %Y %H:%M:%S %Z")`，
而 `%a`/`%b` **跟随进程 locale**。在中文/葡语/法语等 locale 下解析不了 HTTP 日期
（实测本机切到系统 locale 后返回 `None`），于是"时钟偏移自动校正"失效，
真 403 会被 `SkewAdjustmentError` 盖住 —— 排查时更难看出真正原因。

## 何时可以删掉

`pip install -U edge-tts` 装到含 #491 的版本后，本模块即可删除。
设 `EDGE_TTS_LEGACY_HOST=1` 可临时退回旧主机（万一某些地区旧主机仍可用）。
"""
from __future__ import annotations

import logging
import os
from datetime import timezone
from email.utils import parsedate_to_datetime
from typing import Optional

logger = logging.getLogger(__name__)

#: 新合成主机（Edge 155 用的就是它）
NEW_WSS_HOST = "api.msedgeservices.com/tts/cognitiveservices/websocket/v1"

_applied = False


def apply() -> bool:
    """把 edge-tts 指向新合成主机。返回是否做了改动（幂等）。

    失败不抛异常 —— 兼容层不该让整个服务起不来，真出问题会在合成时暴露。
    """
    global _applied
    if _applied:
        return False

    if os.getenv("EDGE_TTS_LEGACY_HOST") == "1":
        logger.info("[edge_tts_compat] EDGE_TTS_LEGACY_HOST=1，保留旧主机")
        _applied = True
        return False

    try:
        import edge_tts.communicate as _comm
        from edge_tts.constants import TRUSTED_CLIENT_TOKEN
    except (ImportError, AttributeError) as e:
        logger.warning("[edge_tts_compat] 无法导入 edge_tts，跳过（%s）", e)
        return False

    try:
        if NEW_WSS_HOST in _comm.WSS_URL:
            # 上游已经修好了（或本模块被重复执行）
            _applied = True
            return False

        # 注意：必须改 communicate 上的名字，改 constants 不生效（见模块 docstring）
        _comm.WSS_URL = (
            f"wss://{NEW_WSS_HOST}?Ocp-Apim-Subscription-Key={TRUSTED_CLIENT_TOKEN}"
        )
        _fix_date_parsing()
        _applied = True
        logger.info(
            "[edge_tts_compat] 已把合成端点切到 %s（旧主机自 2026-10 起返回 403）",
            NEW_WSS_HOST,
        )
        return True
    except (Exception, SystemExit) as e:  # noqa: BLE001 - 兼容层不该拖垮启动
        logger.warning("[edge_tts_compat] 应用失败，将沿用上游默认: %s", e)
        return False


def _fix_date_parsing() -> None:
    """让 HTTP 日期解析不依赖进程 locale（上游 #491 的第二个修复）。

    `%a`/`%b` 跟随 locale，中文/葡语/法语等 locale 下解析失败 → 时钟校正失效 →
    真 403 被 `SkewAdjustmentError` 盖住，排查时看不到真正原因。
    """
    try:
        from edge_tts.drm import DRM
    except ImportError:
        return

    def _parse(date: str) -> Optional[float]:
        try:
            parsed = parsedate_to_datetime(date)
        except (TypeError, ValueError, IndexError):
            return None
        if parsed.tzinfo is None:
            # HTTP 日期不带时区时按 UTC 处理
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()

    DRM.parse_rfc2616_date = staticmethod(_parse)


def reset_for_tests() -> None:
    """仅供测试：清掉"已应用"标记，便于重复验证。"""
    global _applied
    _applied = False
