"""CosyVoice 云端引擎（ADR-0007 修订）：阿里云百炼原生 HTTP API。

DashScope 的 OpenAI 兼容端点没有 audio/speech / audio/transcriptions 路由
（实测 404），语音必须走原生 API：TTS = SpeechSynthesizer HTTP（非流式
返回音频 URL，二次 GET 取 mp3）；ASR = Paraformer WebSocket 实时识别
（见 api/asr_routes.py，文件转写 API 只收公网 URL 不适用本地录音）。
不引入 dashscope 原生 SDK；任何云端异常统一包成 TTSEngineError
（D-3 教训：防击穿降级语义）。
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

from . import TTSEngineError

if TYPE_CHECKING:  # 仅类型引用，避免 config ⇄ tts 运行时环
    from ..config import AppConfig
    from ..secrets import KeyStore

logger = logging.getLogger(__name__)

ENGINE_NAME = "cosyvoice"
MEDIA_TYPE = "audio/mpeg"
TTS_MODEL = "cosyvoice-v3-flash"  # 系统音色全集（v3.5 不支持系统音色）
_TIMEOUT_S = 60.0
_PROBE_TEXT = "你好"

#: 百炼原生 TTS 端点（公网域名，无需 workspace 专属域名）
TTS_URL = "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer"

#: 语音连接在 connections 里的固定 id（语音页创建；聊天侧可复用挂 profile）
VOICE_CONNECTION_ID = "bailian-voice"


@dataclass(frozen=True)
class SpeechConnection:
    connection_id: str
    api_key: str


def resolve_speech_connection(config: AppConfig, key_store: KeyStore) -> SpeechConnection | None:
    """voice.connection_id → connection + KeyStore 取 Key。

    返回 None = 未配置（无绑定 / 连接被删 / Key 被删），调用方按
    cloud-unconfigured 语义短路。原生端点固定，无需 base_url 回退。
    """
    if config.voice.connection_id is None:
        return None
    connection_id = config.voice.connection_id
    if connection_id not in config.model.connections:
        return None
    api_key = key_store.get_key(connection_id)
    if not api_key:
        return None
    return SpeechConnection(connection_id=connection_id, api_key=api_key)


def _build_http_client() -> httpx.AsyncClient:
    """每次合成新建即关：单用户低频，免客户端/Key 失效的缓存管理；
    测试经 monkeypatch 注入 MockTransport。"""
    return httpx.AsyncClient(timeout=_TIMEOUT_S)


def _raise_dashscope_error(resp: httpx.Response) -> None:
    """DashScope 错误体 {"code","message"} → TTSEngineError。"""
    try:
        payload = resp.json()
        code = payload.get("code") or f"HTTP {resp.status_code}"
        message = payload.get("message", "")
    except ValueError:
        code, message = f"HTTP {resp.status_code}", (resp.text or "")[:200]
    if resp.status_code in (401, 403):
        message = "API Key 无效或未开通百炼语音服务"
    raise TTSEngineError(f"CosyVoice 合成失败（{code}）：{message}")


async def synthesize(text: str, *, voice_id: str, rate: float, conn: SpeechConnection) -> bytes:
    """整段合成 mp3：非流式先取音频 URL 再下载（url 优先，data base64 兜底）。

    volume 不传云端——音量由前端增益；rate/speed 进 input（原生布局）。
    """
    payload = {
        "model": TTS_MODEL,
        "input": {"text": text, "voice": voice_id, "format": "mp3", "rate": rate},
    }
    headers = {"Authorization": f"Bearer {conn.api_key}"}
    async with _build_http_client() as client:
        resp = await client.post(TTS_URL, headers=headers, json=payload)
        if resp.status_code != 200:
            _raise_dashscope_error(resp)
        audio = (resp.json().get("output") or {}).get("audio") or {}
        if not isinstance(audio, dict):
            audio = {}
        if audio.get("data"):  # 兼容流式风格的内联 base64 返回
            return base64.b64decode(audio["data"])
        url = audio.get("url")
        if not url:
            raise TTSEngineError("CosyVoice 合成失败：云端未返回音频")
        download = await client.get(url)
        if download.status_code != 200:
            raise TTSEngineError(f"CosyVoice 音频下载失败（HTTP {download.status_code}）")
        if not download.content:
            raise TTSEngineError("CosyVoice 合成失败：音频为空")
        return download.content


async def probe(conn: SpeechConnection) -> tuple[bool, str]:
    """真实合成一句短文本（按字符计费成本≈0）；连接配置与设置页测试共用。"""
    try:
        audio = await synthesize(_PROBE_TEXT, voice_id="longxing_v3", rate=1.0, conn=conn)
    except TTSEngineError as exc:
        logger.warning("[tts] 语音连接探测失败：%s", exc)
        return False, str(exc)
    return len(audio) > 0, "" if audio else "云端未返回音频"
