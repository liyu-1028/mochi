"""ASR 语音识别端点（ADR-0007-R1：与 TTS 共用百炼连接）。

与 TTS 的 204 静默降级刻意不同：语音输入是显式用户动作，未配置/隐私
模式/云端失败都明确报错（409/413/502），让用户知道为什么没反应。
识别走 Paraformer WebSocket 实时识别（DashScope 无 OpenAI 兼容 ASR 路由，
文件转写 API 只收公网 URL，本地录音只能推流）：run-task → 音频分帧 →
finish-task；文本聚合按句覆盖（中间结果是当前句的演进，sentence_end 定稿）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid

import websockets
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile

from ..events import CamelModel
from ..tts.cosyvoice_engine import SpeechConnection, resolve_speech_connection
from .security import localhost_only

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/asr", tags=["asr"], dependencies=[Depends(localhost_only)])

#: paraformer-realtime 推流上限（60s 16kHz mono PCM16 ≈ 1.9MB，留足余量）
MAX_ASR_FILE_BYTES = 20 * 1024 * 1024
ASR_MODEL = "paraformer-realtime-v2"
ASR_TIMEOUT_S = 60.0
ASR_WS_URL = "wss://dashscope.aliyuncs.com/api/v1/services/audio/asr/recognition"
_CHUNK = 16 * 1024


class AsrResult(CamelModel):
    text: str


class ASRError(Exception):
    """云端拒绝/协议失败（路由层转 502）。"""


def _event_error(msg: dict) -> str:
    header = msg.get("header") or {}
    code = header.get("error_code") or header.get("event") or "unknown"
    return f"{code}：{header.get('error_message', '')}"


async def transcribe(audio: bytes, *, conn: SpeechConnection) -> str:
    """一段完整 WAV（前端恒 16kHz mono PCM16）→ 文本。"""
    task_id = uuid.uuid4().hex
    run_task = {
        "header": {"action": "run-task", "task_id": task_id, "streaming": "out"},
        "payload": {
            "model": ASR_MODEL,
            "task_group": "audio",
            "task": "asr",
            "function": "recognition",
            # 前端恒传 wav 容器（apps audio/wav.ts）；按住说话场景顺手过滤语气词
            "parameters": {
                "format": "wav",
                "sample_rate": 16000,
                "disfluency_removal_enabled": True,
            },
            "input": {},
        },
    }
    finish_task = {
        "header": {"action": "finish-task", "task_id": task_id, "streaming": "out"},
        "payload": {"input": {}},
    }
    parts: list[str] = []
    pending = ""  # 当前句最新中间结果（收尾时最后一句可能未定稿）

    async with websockets.connect(
        ASR_WS_URL, additional_headers={"Authorization": f"Bearer {conn.api_key}"}
    ) as ws:
        await ws.send(json.dumps(run_task))
        started = json.loads(await asyncio.wait_for(ws.recv(), ASR_TIMEOUT_S))
        if (started.get("header") or {}).get("event") != "task-started":
            raise ASRError(_event_error(started))  # 鉴权/配额错误在此暴露
        for i in range(0, len(audio), _CHUNK):
            await ws.send(audio[i : i + _CHUNK])
        await ws.send(json.dumps(finish_task))
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), ASR_TIMEOUT_S))
            event = (msg.get("header") or {}).get("event")
            if event == "result-generated":
                sentence = (msg.get("payload") or {}).get("output", {}).get("sentence") or {}
                text = sentence.get("text", "")
                if sentence.get("sentence_end"):
                    parts.append(text)
                    pending = ""
                else:
                    pending = text  # 同句演进，覆盖
            elif event == "task-finished":
                break
            elif event == "task-failed":
                raise ASRError(_event_error(msg))
    if pending:
        parts.append(pending)
    return "".join(parts).strip()


@router.post("/transcribe")
async def transcribe_file(file: UploadFile, request: Request) -> AsrResult:
    registry = request.app.state.registry
    if registry is None:
        raise HTTPException(status_code=503, detail="配置服务未就绪")
    config = registry.config
    if config.privacy.local_only:
        raise HTTPException(status_code=409, detail="隐私模式已开启，语音输入不可用")
    conn = resolve_speech_connection(config, registry.key_store)
    if conn is None:
        raise HTTPException(status_code=409, detail="请先在 设置 → 语音 配置百炼连接")

    content = await file.read()
    if len(content) > MAX_ASR_FILE_BYTES:
        raise HTTPException(status_code=413, detail="音频过大（上限 20MB）")
    if not content:
        raise HTTPException(status_code=422, detail="音频为空")

    try:
        text = await transcribe(content, conn=conn)
    except ASRError as exc:
        logger.warning("[asr] 识别失败：%s", exc)
        raise HTTPException(status_code=502, detail=f"语音识别失败：{exc}") from exc
    except (websockets.WebSocketException, TimeoutError, OSError) as exc:
        logger.warning("[asr] 连接失败：%s", exc)
        raise HTTPException(status_code=502, detail="语音识别失败：无法连接百炼服务") from exc
    return AsrResult(text=text)
