"""Sidecar 运行时信息文件 <userData>/runtime.json（M1-S0 端口发现）。

sidecar 启动就绪后写入实际服务的端口/pid/协议版本，桌面壳轮询读取后
通知前端按真实端口连接（Rust 侧对应 apps/desktop/src-tauri/src/runtime.rs）。

端口契约：``MOCHI_SIDECAR_PORT`` 环境变量（缺省 8199）。release 模式由
桌面壳 spawn 子进程时注入；dev 模式 CLI ``--port`` 与缺省值一致即可。
写入/删除失败只记录日志，绝不阻断启动（端口发现是增强，不是主链路）。
"""

from __future__ import annotations

import json
import logging
import os
import time

from .events import PROTOCOL_VERSION
from .paths import get_data_dir

logger = logging.getLogger(__name__)

RUNTIME_FILE_NAME = "runtime.json"
PORT_ENV = "MOCHI_SIDECAR_PORT"
DEFAULT_PORT = 8199


def resolve_port() -> int:
    """当前 sidecar 服务端口：MOCHI_SIDECAR_PORT > 缺省 8199。"""
    raw = os.environ.get(PORT_ENV)
    if raw is None:
        return DEFAULT_PORT
    try:
        return int(raw)
    except ValueError:
        logger.warning("%s=%r 非法，回退默认端口 %s", PORT_ENV, raw, DEFAULT_PORT)
        return DEFAULT_PORT


def get_runtime_path():
    return get_data_dir() / RUNTIME_FILE_NAME


def write_runtime_file(port: int) -> None:
    """原子写入（tmp + os.replace），避免桌面壳读到半截 JSON。"""
    payload = {
        "port": port,
        "pid": os.getpid(),
        "protocolVersion": PROTOCOL_VERSION,
        "startedAt": int(time.time() * 1000),
    }
    target = get_runtime_path()
    tmp = target.with_name(target.name + ".tmp")
    try:
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, target)
        logger.info("runtime.json 已写入：port=%s pid=%s", port, payload["pid"])
    except OSError:
        logger.exception("runtime.json 写入失败（不阻断启动，前端退回默认端口）")


def remove_runtime_file() -> None:
    try:
        get_runtime_path().unlink(missing_ok=True)
    except OSError:
        logger.exception("runtime.json 删除失败（下次启动会覆盖）")
