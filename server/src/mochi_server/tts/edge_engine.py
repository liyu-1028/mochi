"""edge-tts 引擎（S2 默认：免费无 Key、音色多）。

输出 mp3 字节流；任何失败抛 TTSEngineError，由 engine.py 降级链接管。
rate/volume 以相对百分比传参：1.0 → +0%（引擎默认），0.5 → -50%，2.0 → +100%。
"""

from __future__ import annotations

import edge_tts

from . import TTSEngineError

ENGINE_NAME = "edge"
MEDIA_TYPE = "audio/mpeg"


def _pct(value: float) -> str:
    return f"{round((value - 1) * 100):+d}%"


async def synthesize(text: str, voice_id: str, rate: float, volume: float) -> bytes:
    communicate = edge_tts.Communicate(text, voice_id, rate=_pct(rate), volume=_pct(volume))
    chunks: list[bytes] = []
    async for chunk in communicate.stream():
        if chunk["type"] == "audio" and chunk["data"]:
            chunks.append(chunk["data"])
    if not chunks:
        raise TTSEngineError("edge-tts 未返回音频数据")
    return b"".join(chunks)
