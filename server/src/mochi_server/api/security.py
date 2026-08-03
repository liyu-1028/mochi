"""本地守卫与日志脱敏（功能清单 7.2：Key 永不落明文日志）。"""

from __future__ import annotations

import logging
import re

from fastapi import HTTPException, Request

# Host 头白名单：防 DNS 重绑定（浏览器跨源请求会携带真实主机名）。
# testserver/testclient 为 Starlette TestClient 固定值，浏览器不可能发出，不影响真实守卫。
_ALLOWED_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]", "testserver", "testclient"}
_LOCAL_CLIENTS = {"127.0.0.1", "::1", "testclient"}


def localhost_only(request: Request) -> None:
    """FastAPI 依赖：仅放行本机来源（客户端地址 + Host 头双重校验）。"""
    client = request.client
    if client is None or client.host not in _LOCAL_CLIENTS:
        raise HTTPException(status_code=403, detail="仅限本机访问")
    host = request.headers.get("host", "").split(":")[0].strip("[]").lower()
    if host and host not in _ALLOWED_HOSTS:
        raise HTTPException(status_code=403, detail="非法 Host 头")


# 敏感键值对脱敏：匹配 key/secret/token 等键名后紧跟的值
_SECRET_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|authorization|secret|password|token|key)(\s*[:=]\s*)([^\s,;'\"}]+)"
)


def scrub_sensitive(text: str) -> str:
    return _SECRET_PATTERN.sub(r"\1\2***", text)


class SensitiveDataFilter(logging.Filter):
    """日志脱敏过滤器：挂到 root logger，兜住一切第三方库日志。"""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # 格式化异常不因脱敏放大
            return True
        sanitized = scrub_sensitive(message)
        if sanitized != message:
            record.msg = sanitized
            record.args = ()
        return True
