"""TTS 音色精选表（S2，5.1「≥2 音色」）。

edge-tts 官方全量音色表需联网拉取；精选静态表离线确定、打包可靠，
默认音与 VoiceConfig.voice_id 默认值一致（config.py）。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VoiceOption:
    """可选音色：id 为 edge-tts 音色名，前端 select 直接回传。"""

    id: str
    name: str
    lang: str
    gender: str


VOICES: tuple[VoiceOption, ...] = (
    VoiceOption("zh-CN-XiaoxiaoNeural", "晓晓", "zh-CN", "female"),
    VoiceOption("zh-CN-YunxiNeural", "云希", "zh-CN", "male"),
    VoiceOption("zh-CN-YunjianNeural", "云健", "zh-CN", "male"),
    VoiceOption("en-US-AriaNeural", "Aria", "en-US", "female"),
    VoiceOption("en-US-GuyNeural", "Guy", "en-US", "male"),
)

_KNOWN = {v.id for v in VOICES}


def is_known_voice(voice_id: str) -> bool:
    return voice_id in _KNOWN


def voice_catalog() -> list[dict[str, str]]:
    """GET /tts/voices 响应体（camelCase 与前端约定一致）。"""
    return [{"id": v.id, "name": v.name, "lang": v.lang, "gender": v.gender} for v in VOICES]
