"""本地守卫与日志脱敏（功能清单 7.2：Key 永不落明文日志）。"""

from __future__ import annotations

import logging
import re

from fastapi import HTTPException, Request

# Host 头白名单：防 DNS 重绑定（浏览器跨源请求会携带真实主机名）。
# testserver/testclient 为 Starlette TestClient 固定值，浏览器不可能发出，不影响真实守卫。
_ALLOWED_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]", "testserver", "testclient"}
_LOCAL_CLIENTS = {"127.0.0.1", "::1", "testclient"}

# CORS 源白名单：只放行已知前端源（dev Vite 1420 + Tauri 桌面壳协议）。
# 严禁 ["*"]：通配会让用户浏览器里打开的任意网页都能跨源读写本机 /config/*
# （源校验是防恶意网页操控本地 API 的关键防线；OPTIONS 预检由中间件统一应答）。
ALLOWED_CORS_ORIGINS = frozenset(
    {
        "http://localhost:1420",  # Vite dev server（strictPort）
        "http://127.0.0.1:1420",
        "tauri://localhost",  # Tauri v2 macOS 桌面壳
        "http://tauri.localhost",  # Tauri v2 Windows/Linux 桌面壳
        "https://tauri.localhost",  # 个别平台的协议变体
    }
)


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
