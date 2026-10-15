"""TTS 合成入口：缓存 → CosyVoice 云端引擎 → 纯文本降级。

5.1 红线「引擎失败自动降级纯文本、不阻塞对话」：云端失败返回
``(b"", "text-fallback")``，路由层据此 204，前端静默回纯文本。
未配置连接的 cloud-unconfigured 短路在路由层完成（不进本模块）。
"""

from __future__ import annotations

import logging

from . import TTSEngineError, cache, cosyvoice_engine
from .cosyvoice_engine import SpeechConnection

make_key = cache.make_key

logger = logging.getLogger(__name__)

ENGINE_FALLBACK = "text-fallback"
ENGINE_UNCONFIGURED = "cloud-unconfigured"


def media_type_for() -> str:
    return cosyvoice_engine.MEDIA_TYPE


async def synthesize(
    text: str,
    *,
    voice_id: str,
    rate: float,
    conn: SpeechConnection,
) -> tuple[bytes, str, bool]:
    """合成音频：返回 (audio, engine, cache_hit)。失败降级纯文本。"""
    key = make_key(text, voice_id, rate)
    hit = cache.CACHE.get(key)  # 模块属性访问：测试重置 CACHE 即时生效
    if hit is not None:
        return hit[0], hit[1], True

    try:
        audio = await cosyvoice_engine.synthesize(text, voice_id=voice_id, rate=rate, conn=conn)
    except TTSEngineError as exc:
        logger.warning("[tts] 云端合成失败，降级纯文本：%s", exc)
        return b"", ENGINE_FALLBACK, False
    cache.CACHE.put(key, audio, cosyvoice_engine.ENGINE_NAME)
    return audio, cosyvoice_engine.ENGINE_NAME, False
