"""PyInstaller 打包入口（M0-S4 生产 sidecar）。

独立顶层脚本（不用包内相对导入，PyInstaller 以顶层模块分析入口）。
启动行为与 dev 的 ``uvicorn mochi_server.main:app`` 完全一致：
生产路径由 lifespan 探测 Ollama 并加载/生成配置（main.py 文档串）。

端口契约：前端硬编码 127.0.0.1:8199（useMochiConnection.resolveWsUrl）；
``MOCHI_SIDECAR_PORT`` 覆盖仅为端口发现机制预留（main.py TODO：runtime.json）。

父进程看门狗：桌面壳被 SIGTERM/SIGKILL 等强制终止时不经过 Tauri 的
RunEvent::Exit，sidecar 会成为孤儿进程。看门狗每 2s 检查 ppid，父进程
消失（被 launchd 接管）即给自己发 SIGTERM，走 uvicorn 优雅退出。
"""

from __future__ import annotations

import os
import signal
import threading
import time

import uvicorn

from mochi_server.main import app

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


if __name__ == "__main__":
    _start_parent_watchdog()
    uvicorn.run(
        app,
        host="127.0.0.1",  # 仅本机回环：防局域网暴露（安全红线，见 ADR-0002）
        port=int(os.environ.get("MOCHI_SIDECAR_PORT", "8199")),
        log_level="info",
    )
