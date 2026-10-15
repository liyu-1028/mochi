"""TTS 语音合成（ADR-0007 修订）：阿里云百炼 CosyVoice 云端唯一引擎。

云端失败降级纯文本（不阻塞对话）；未配置连接由路由层按
cloud-unconfigured 短路。音频经独立 HTTP 流通道分发（agent-events-v0.1
§10），不占 WebSocket 协议。
"""


class TTSEngineError(Exception):
    """合成失败：上层降级兜底，不直接暴露给用户。"""
