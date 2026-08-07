"""TTS 语音合成（M1-S2，功能清单 5.1）。

三级降级链：edge-tts（默认，免费无 Key）→ 本地引擎（macOS say / Windows SAPI）
→ 纯文本降级（不阻塞对话）。音频经独立 HTTP 流通道分发（agent-events-v0.1 §10），
不占 WebSocket 协议。
"""


class TTSEngineError(Exception):
    """合成失败：上层降级链接管，不直接暴露给用户。"""
