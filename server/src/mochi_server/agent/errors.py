"""Agent 业务错误：携带协议错误负载，由 RunManager 统一转为 run.error。"""

from __future__ import annotations

from ..events import ErrorPayload


class AgentError(Exception):
    """可预期的业务错误（Key 无效、模型不可达、限流等）。

    与未知异常的区别：payload 由适配层精心构造（用户可读文案 + hint，
    禁止裸露堆栈——功能清单 6.7），RunManager 直接透传给前端。
    """

    def __init__(self, payload: ErrorPayload) -> None:
        super().__init__(payload.message)
        self.payload = payload
