"""REST 管理端点（ADR-0002 D3）：配置与模型提供方管理、会话历史回看。

不占用 WS 协议（v0.1 冻结且聚焦对话事件流）；配置/会话 CRUD 走请求-响应语义。
"""

from .config_routes import router as config_router
from .session_routes import router as session_router

__all__ = ["config_router", "session_router"]
