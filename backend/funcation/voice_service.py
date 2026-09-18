"""语音服务模块：可插拔 TTS 引擎 + 按角色的音色解析。

**引擎可插拔**：`ResolvedVoice.engine` 决定走哪条推理链。

- `edge`：云端 edge-tts，音色是固定名字（`zh-CN-XiaoxiaoNeural` 这类），零依赖、立刻可用；
- `clone`：本地音色克隆（吃 `reference_audio`），需要额外部署引擎。**没装就明确报错，
  绝不静默退回别的音色** —— 用户配了克隆音色却听到别人的声音，比直接报错更糟。

**音色解析链**（见 `voice_pack.resolve_voice_config`）：
角色绑定的语音包 → 旧的按角色写死映射（`LEGACY_CHARACTER_VOICES`）→ 环境变量兜底。
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import voice_pack, voice_store

logger = logging.getLogger(__name__)

# 缓存上限（条）；超出后不再写入（简单粗暴，够用）
_CACHE_MAX = 200

# edge-tts 云端重试：实测同一段文本同一组参数连打 4 次可能挂 2 次，必须重试
_EDGE_ATTEMPTS = 3
_EDGE_RETRY_DELAY = 0.4  # 秒，按次线性递增


class TTSEngineError(RuntimeError):
    """TTS 引擎不可用（未安装 / 配置非法）。API 层翻译成 4xx/5xx 并带上可读原因。"""


@dataclass
class ResolvedVoice:
    """一次合成最终生效的完整音色参数"""
    engine: str = voice_pack.DEFAULT_ENGINE
    voice_name: str = voice_pack.FALLBACK_VOICE
    speaking_rate: float = 1.0
    pitch: float = 0.0
    volume: float = 1.0
    style: str = ""
    reference_audio: Optional[str] = None
    reference_text: str = ""
    pack_id: Optional[str] = None
    pack_name: Optional[str] = None
    source: str = "default"

    @classmethod
    def from_mapping(cls, data: Dict[str, Any]) -> "ResolvedVoice":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in (data or {}).items() if k in known})

    def fingerprint(self) -> str:
        """音色指纹。缓存键要带上它，否则改了语音包还在放旧音频。"""
        raw = "|".join([
            self.engine,
            self.voice_name,
            f"{self.speaking_rate:.3f}",
            f"{self.pitch:.2f}",
            f"{self.volume:.3f}",
            self.style,
            self.reference_audio or "",
        ])
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]

    def describe(self) -> str:
        return f"{self.engine}:{self.voice_name} (rate={self.speaking_rate} pitch={self.pitch})"


@dataclass
class VoiceConfig:
    """旧的配置对象，保留给显式传 config 的调用方（已不参与主链路）"""
    provider: str = voice_pack.DEFAULT_ENGINE
    voice_name: str = voice_pack.FALLBACK_VOICE
    speaking_rate: float = 1.0
    pitch: float = 0.0
    volume: float = 1.0
    style: str = ""


class VoiceService:
    """语音服务：解析音色 + 分发到具体引擎 + 简单内存缓存"""

    def __init__(self):
        self.cache: Dict[str, bytes] = {}
        self._voices_cache: Optional[List[Dict[str, str]]] = None

    # ── 环境变量兜底 ──────────────────────────────────────────────────

    def env_defaults(self) -> Dict[str, Any]:
        """环境变量里的全局默认（最低优先级）"""
        def _f(name: str, default: float) -> float:
            try:
                return float(os.getenv(name, str(default)))
            except (TypeError, ValueError):
                return default

        return {
            "engine": voice_pack.DEFAULT_ENGINE,
            "voice_name": os.getenv("VOICE_NAME") or voice_pack.FALLBACK_VOICE,
            "speaking_rate": _f("SPEAKING_RATE", 1.0),
            "pitch": _f("PITCH", 0.0),
            "volume": _f("VOLUME", 1.0),
        }

    # ── 音色解析 ──────────────────────────────────────────────────────

    def resolve(self, character_id: str) -> ResolvedVoice:
        """解析某角色当前该用哪套音色（读全局语音包库 + 绑定）"""
        try:
            packs, bindings = voice_store.load_library()
        except Exception as e:  # noqa: BLE001 - 配置读不出来也要能说话
            logger.warning("[voice] 语音包库读取失败，退回默认音色: %s", e)
            packs, bindings = [], {}

        cfg = voice_pack.resolve_voice_config(
            character_id=character_id, packs=packs, bindings=bindings
        )
        return ResolvedVoice.from_mapping(cfg)

    # ── 合成 ──────────────────────────────────────────────────────────

    async def synthesize(self, text: str, voice: ResolvedVoice) -> bytes:
        """按 `voice.engine` 分发到具体引擎"""
        engine = (voice.engine or voice_pack.DEFAULT_ENGINE).lower()
        if engine == "edge":
            return await self._synth_edge(text, voice)
        if engine == "clone":
            return await self._synth_clone(text, voice)
        raise TTSEngineError(f"不支持的 TTS 引擎：{engine}")

    async def synthesize_speech(
        self,
        text: str,
        character_id: str,
        config: Optional[VoiceConfig] = None,
    ) -> bytes:
        """合成入口（保持旧签名）。

        不传 `config` 时按角色解析语音包；传了则用显式参数（PoC / 试听这类场景）。
        """
        if config is not None:
            voice = ResolvedVoice(
                engine=config.provider or voice_pack.DEFAULT_ENGINE,
                voice_name=config.voice_name or voice_pack.FALLBACK_VOICE,
                speaking_rate=config.speaking_rate,
                pitch=config.pitch,
                volume=config.volume,
                style=config.style,
                source="explicit",
            )
        else:
            voice = self.resolve(character_id)

        cache_key = self._cache_key(character_id, text, voice)
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        audio = await self.synthesize(text, voice)

        if len(self.cache) < _CACHE_MAX:
            self.cache[cache_key] = audio
        return audio

    @staticmethod
    def _cache_key(character_id: str, text: str, voice: ResolvedVoice) -> str:
        text_hash = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
        return f"{character_id}_{text_hash}_{voice.fingerprint()}"

    # ── 引擎实现 ──────────────────────────────────────────────────────

    async def _synth_edge(self, text: str, voice: ResolvedVoice) -> bytes:
        """edge-tts（云端）。rate/volume 是百分比、pitch 是 Hz，格式必须是 `+0%` / `+0Hz`。

        **必须重试**：edge-tts 是云端服务，实测会偶发抛 `NoAudioReceived`
        （同一段文本同一个参数，连打 4 次可能挂 2 次）。不重试的话，语音通话里
        这句话就直接没声音了 —— 用户只看到角色"张了张嘴"。
        """
        try:
            from edge_tts import Communicate
        except ImportError as e:
            raise TTSEngineError("edge-tts 未安装，请执行 pip install edge-tts") from e

        if not voice_pack.is_valid_voice_name(voice.voice_name):
            raise TTSEngineError(f"音色名不合法：{voice.voice_name!r}")

        rate_pct = int(round((voice.speaking_rate - 1.0) * 100))
        pitch_hz = int(round(voice.pitch))
        volume_pct = int(round((voice.volume - 1.0) * 100))

        last_error: Optional[Exception] = None
        for attempt in range(_EDGE_ATTEMPTS):
            try:
                communicate = Communicate(
                    text=text,
                    voice=voice.voice_name,
                    rate=f"{rate_pct:+d}%",
                    pitch=f"{pitch_hz:+d}Hz",
                    volume=f"{volume_pct:+d}%",
                )
                buffer = io.BytesIO()
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        buffer.write(chunk["data"])
                audio = buffer.getvalue()
                if audio:
                    return audio
                last_error = TTSEngineError("edge-tts 没有返回音频（文本可能为空或全是符号）")
            except Exception as e:  # noqa: BLE001 - 云端错误类型不稳定，统一重试
                last_error = e

            if attempt < _EDGE_ATTEMPTS - 1:
                delay = _EDGE_RETRY_DELAY * (attempt + 1)
                logger.warning(
                    "[voice] edge-tts 第 %d/%d 次失败（%s），%.1fs 后重试 — voice=%s",
                    attempt + 1, _EDGE_ATTEMPTS, last_error, delay, voice.voice_name,
                )
                await asyncio.sleep(delay)

        raise TTSEngineError(f"edge-tts 合成失败（已重试 {_EDGE_ATTEMPTS} 次）：{last_error}")

    async def _synth_clone(self, text: str, voice: ResolvedVoice) -> bytes:
        """本地音色克隆（预留）。

        刻意抛错而不是回退：用户选了克隆音色却听到默认音色，是比报错更糟的体验。
        接入步骤：装引擎 → 在这里按 `voice.reference_audio` 加载音色 → 返回 wav 字节。
        """
        if not voice.reference_audio:
            raise TTSEngineError("这个语音包没有参考音频，无法用克隆引擎合成")
        raise TTSEngineError(
            "克隆引擎尚未部署。当前只支持 edge 引擎；"
            "接入 XTTS / CosyVoice 后此语音包即可生效（参考音频已保存）。"
        )

    # ── 音色目录 ──────────────────────────────────────────────────────

    async def list_edge_voices(self, *, use_network: bool = True) -> List[Dict[str, str]]:
        """可用音色列表。

        优先问 edge-tts 要完整列表；网络不通就退回 `voice_pack.VOICE_CATALOG`
        静态表 —— 配置界面不能因为拿不到网络就变成空白。
        """
        if self._voices_cache is not None:
            return self._voices_cache

        if use_network:
            try:
                from edge_tts import list_voices as edge_list_voices

                raw = await asyncio.wait_for(edge_list_voices(), timeout=10)
                items = [
                    {
                        "short_name": v.get("ShortName", ""),
                        "label": v.get("FriendlyName", v.get("ShortName", "")),
                        "gender": v.get("Gender", ""),
                        "locale": v.get("Locale", ""),
                    }
                    for v in raw
                    if str(v.get("Locale", "")).startswith(("zh", "en"))
                ]
                if items:
                    self._voices_cache = sorted(items, key=lambda x: (x["locale"], x["short_name"]))
                    return self._voices_cache
            except Exception as e:  # noqa: BLE001 - 网络问题不该让配置页崩掉
                logger.warning("[voice] 获取在线音色列表失败，用内置静态表: %s", e)

        self._voices_cache = [
            {
                "short_name": v["short_name"],
                "label": v["label"],
                "gender": v["gender"],
                "locale": v["short_name"][:5],
            }
            for v in voice_pack.VOICE_CATALOG
        ]
        return self._voices_cache

    # ── 维护 ──────────────────────────────────────────────────────────

    def engine_available(self, engine: str) -> bool:
        """该引擎现在能不能真的合成。

        UI 拿它给语音包打「可用 / 引擎未部署」标记 —— 比让用户配完了才发现没声音好。
        """
        name = (engine or "").lower()
        if name == "edge":
            try:
                import edge_tts  # noqa: F401
                return True
            except ImportError:
                return False
        if name == "clone":
            # 接入本地克隆引擎后，这里改成探测真实依赖
            return False
        return False

    def available_engines(self) -> List[Dict[str, Any]]:
        return [
            {
                "engine": name,
                "available": self.engine_available(name),
                "label": {
                    "edge": "Edge TTS（云端，音色固定）",
                    "clone": "本地音色克隆（需部署引擎）",
                }.get(name, name),
            }
            for name in voice_pack.SUPPORTED_ENGINES
        ]

    def clear_cache(self):
        self.cache.clear()


# 全局语音服务实例
voice_service = VoiceService()
