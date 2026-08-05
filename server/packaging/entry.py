"""PyInstaller 打包入口（M0-S4 生产 sidecar）。

独立顶层脚本（不用包内相对导入，PyInstaller 以顶层模块分析入口）。
启动行为与 dev 的 ``uvicorn mochi_server.main:app`` 完全一致：
生产路径由 lifespan 探测 Ollama 并加载/生成配置（main.py 文档串）。

端口契约（M1-S0 端口发现）：首选 ``MOCHI_SIDECAR_PORT``（缺省 8199）；
被占用时自动改用空闲端口。实际端口经 lifespan 写入 <userData>/runtime.json，
桌面壳轮询读取后通知前端（useMochiConnection/configClient 据此切换地址）。

父进程看门狗：桌面壳被 SIGTERM/SIGKILL 等强制终止时不经过 Tauri 的
RunEvent::Exit，sidecar 会成为孤儿进程。看门狗每 2s 检查 ppid，父进程
消失（被 launchd 接管）即给自己发 SIGTERM，走 uvicorn 优雅退出。
"""

from __future__ import annotations

import os
import signal
import socket
import threading
import time

import uvicorn

from mochi_server.main import app
from mochi_server.runtime import PORT_ENV, resolve_port

_WATCH_INTERVAL_S = 2.0


def _start_parent_watchdog() -> None:
    parent_pid = os.getppid()

    def _watch() -> None:
        while True:
            time.sleep(_WATCH_INTERVAL_S)
            if os.getppid() != parent_pid:
                os.kill(os.getpid(), signal.SIGTERM)
                return

    thread = threading.Thread(target=_watch, name="parent-watchdog", daemon=True)
    thread.start()


def _port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _find_free_port() -> int:
    """bind 0 端口让内核分配（仅回环，安全红线不放松）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _resolve_serving_port() -> int:
    preferred = resolve_port()
    if _port_available(preferred):
        return preferred
    fallback = _find_free_port()
    print(f"[mochi] 端口 {preferred} 被占用，改用 {fallback}（经 runtime.json 告知桌面壳）")
    return fallback


if __name__ == "__main__":
    _start_parent_watchdog()
    serving_port = _resolve_serving_port()
    # 回写实际端口：lifespan 的 runtime.json 以此为唯一事实源
    os.environ[PORT_ENV] = str(serving_port)
    uvicorn.run(
        app,
        host="127.0.0.1",  # 仅本机回环：防局域网暴露（安全红线，见 ADR-0002）
        port=serving_port,
        log_level="info",
    )
