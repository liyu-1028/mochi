"""REST 管理端点（ADR-0002 D3）：配置与模型提供方管理、会话历史回看、记忆管理。

不占用 WS 协议（v0.1 冻结且聚焦对话事件流）；配置/会话/记忆 CRUD 走请求-响应语义。
"""

from .config_routes import router as config_router
from .memory_routes import router as memory_router
from .session_routes import router as session_router
from .skin_routes import router as skin_router
from .tts_routes import router as tts_router

__all__ = ["config_router", "memory_router", "session_router", "skin_router", "tts_router"]
