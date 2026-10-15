"""读参考音频的时长（尽力而为，**不引第三方依赖**）。

## 为什么只用标准库

克隆效果最好的就是**无损 WAV**，而那恰好是标准库 `wave` 能读的。
mp3/m4a/ogg 等压缩格式要读时长得引 mutagen / soundfile / librosa ——
为了"管理员偶尔上传一次"的校验给整个后端加依赖不划算，何况我们
本来就刻意绕开 ffmpeg（`pydub` 就是这个原因被排除的）。

所以这里**只覆盖 WAV，其他格式返回 `None`**（= 不知道），由调用方给通用提示。
将来真要全格式支持，加 mutagen 是一行的事。

**任何失败都返回 None，绝不抛** ——  Duration 读不出来不该让上传失败。
"""
from __future__ import annotations

import logging
import wave
from typing import Optional

logger = logging.getLogger(__name__)

#: 低于这个时长给警告。OpenVoice 的零样本克隆需要足够的音色信息，
#: 官方建议 5-10 秒；短于这个值能传但效果会明显差。
VOICE_REF_MIN_SECONDS = 4.0

#: 推荐区间文案（前端直接用）
VOICE_REF_HINT = (
    "建议用 5-10 秒、单人、安静的录音（WAV 效果最好）。"
    "太短、有背景音乐或多人说话都会让克隆音色变糊。"
)


def probe_duration_seconds(path: str) -> Optional[float]:
    """返回音频时长（秒）；读不出来返回 `None`。

    只认 WAV（RIFF/WAVE）。`path` 不存在、不是 WAV、文件损坏
    一律 `None` + 一条 debug 日志（不抛）。
    """
    try:
        with wave.open(path, "rb") as w:
            frames = w.getnframes()
            rate = w.getframerate()
            if not rate:
                return None
            return frames / float(rate)
    except (wave.Error, EOFError, OSError) as e:
        # wave.Error 覆盖"不是 WAV / 文件损坏"；OSError 覆盖"文件不存在/权限"
        logger.debug("[audio_probe] 读不到时长（%s）：%s", path, e)
        return None
    except (Exception, SystemExit) as e:  # noqa: BLE001 - 探测绝不能炸掉上传
        logger.debug("[audio_probe] 读取时长出现意外错误（%s）：%s", path, e)
        return None


def duration_warning(seconds: Optional[float]) -> Optional[str]:
    """时长过短时返回警告文案；没问题或未知都返回 `None`。

    `None` 表示"不知道"（非 WAV）—— **不要因此报警**，
    否则用户上传 mp3 也会看到红色警告。
    """
    if seconds is None:
        return None
    if seconds < VOICE_REF_MIN_SECONDS:
        return (
            f"这段音频只有 {seconds:.1f} 秒，偏短了，克隆出来的音色可能不像。"
            f"{VOICE_REF_HINT}"
        )
    return None
