"""TTS HTTP 端点（M1-S2，功能清单 5.1）。

音频走独立 HTTP 流通道（agent-events-v0.1 §10 排除语音流，协议零改动）：
- ``POST /tts/stream``：合成并流式返回音频；``X-TTS-Engine`` 上报实际引擎
  （edge|local|text-fallback|muted），``X-TTS-Cache`` 上报命中；
- ``GET /tts/voices``：静态精选音色表（零网络）。

降级语义：引擎全链失败 / 静音 / 空文本 → 204，前端静默回纯文本，不阻塞对话。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import Field

from ..events import CamelModel
from ..tts import engine, voices
from .security import localhost_only

router = APIRouter(prefix="/tts", tags=["tts"], dependencies=[Depends(localhost_only)])

MAX_TTS_TEXT_LENGTH = 5000
_CHUNK_SIZE = 64 * 1024


class TtsStreamRequest(CamelModel):
    """合成请求：缺省字段回退 [voice] 配置（设置面板/托盘为事实源）。"""

    text: str
    voice_id: str | None = None
    rate: float | None = Field(default=None, ge=0.5, le=2.0)
    volume: float | None = Field(default=None, ge=0.0, le=1.0)


def _registry(request: Request):
    registry = request.app.state.registry
    if registry is None:
        raise HTTPException(status_code=503, detail="配置服务未就绪")
    return registry


async def _chunked(data: bytes):
    for i in range(0, len(data), _CHUNK_SIZE):
        yield data[i : i + _CHUNK_SIZE]


@router.post("/stream")
async def stream_tts(body: TtsStreamRequest, request: Request) -> Response:
    """合成音频流；204 = 无音频可播（静音/空文本/纯文本降级）。"""
    voice = _registry(request).config.voice
    if not voice.tts_enabled or voice.muted:
        return Response(status_code=204, headers={"X-TTS-Engine": "muted"})

    text = body.text.strip()
    if not text:
        return Response(status_code=204, headers={"X-TTS-Engine": "text-fallback"})
    if len(text) > MAX_TTS_TEXT_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"文本过长（上限 {MAX_TTS_TEXT_LENGTH} 字符）",
        )

    voice_id = body.voice_id or voice.voice_id
    if not voices.is_known_voice(voice_id):
        raise HTTPException(status_code=400, detail=f"未知音色：{voice_id}")

    audio, used_engine, cache_hit = await engine.synthesize(
        text,
        voice_id=voice_id,
        rate=body.rate if body.rate is not None else voice.rate,
        volume=body.volume if body.volume is not None else voice.volume,
        primary=voice.engine,
    )
    headers = {
        "X-TTS-Engine": used_engine,
        "X-TTS-Cache": "hit" if cache_hit else "miss",
    }
    if used_engine == engine.ENGINE_FALLBACK:
        return Response(status_code=204, headers=headers)
    return StreamingResponse(
        _chunked(audio), media_type=engine.media_type_for(used_engine), headers=headers
    )


@router.get("/voices")
async def list_voices(request: Request) -> dict:
    """音色目录（静态精选，零网络）+ 当前默认音。"""
    return {"voices": voices.voice_catalog(), "default": _registry(request).config.voice.voice_id}
