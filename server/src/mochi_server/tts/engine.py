"""TTS 合成入口：缓存 → 引擎降级链（edge → local → 纯文本标记）。

5.1 红线「引擎失败自动降级纯文本、不阻塞对话」：全链失败返回
``(b"", "text-fallback")``，路由层据此 204，前端静默回纯文本。
"""

from __future__ import annotations

import logging

from . import TTSEngineError, cache, edge_engine, local_engine

make_key = cache.make_key

logger = logging.getLogger(__name__)

ENGINE_FALLBACK = "text-fallback"

_ENGINES = {"edge", "local"}


def media_type_for(engine: str) -> str:
    return edge_engine.MEDIA_TYPE if engine == "edge" else local_engine.MEDIA_TYPE


async def synthesize(
    text: str,
    *,
    voice_id: str,
    rate: float,
    volume: float,
    primary: str,
) -> tuple[bytes, str, bool]:
    """合成音频：返回 (audio, engine, cache_hit)。

    primary 取自 [voice].engine；链序 = 首选 + 另一引擎兜底。
    """
    key = make_key(text, voice_id, rate, volume)
    hit = cache.CACHE.get(key)  # 模块属性访问：测试重置 CACHE 即时生效
    if hit is not None:
        return hit[0], hit[1], True

    if primary not in _ENGINES:
        primary = "edge"
    chain = [primary, *(e for e in ("edge", "local") if e != primary)]

    for engine in chain:
        try:
            if engine == "edge":
                audio = await edge_engine.synthesize(text, voice_id, rate, volume)
            else:
                audio = await local_engine.synthesize(text, rate)
        except TTSEngineError as exc:
            logger.warning("[tts] 引擎 %s 合成失败，尝试下一级：%s", engine, exc)
            continue
        cache.CACHE.put(key, audio, engine)
        return audio, engine, False

    logger.warning("[tts] 全引擎失败，降级纯文本")
    return b"", ENGINE_FALLBACK, False
