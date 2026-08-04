"""诊断专用入口：给冻结态启动各阶段打时间戳（写 /tmp/mochi-timing.log）。

不用于生产（生产入口为 entry.py）；仅供 M0-S4 冷启动瓶颈定位。
桩点：imports → uvicorn.run → loop 初始化 → lifespan（probe/config）→ 就绪。
"""

from __future__ import annotations

import time

_T0 = time.time()


def _mark(label: str) -> None:
    with open("/tmp/mochi-timing.log", "a") as f:
        f.write(f"{time.time() - _T0:8.3f}s  {label}\n")


_mark("entry 开始")

import os  # noqa: E402

import uvicorn  # noqa: E402

_mark("import uvicorn")

import mochi_server.main as main_mod  # noqa: E402
from mochi_server.main import app  # noqa: E402

_mark("import mochi_server.main（含 create_app）")

# --- 桩：probe_ollama / load_config（lifespan 内两大步骤） ---
_orig_probe = main_mod.probe_ollama
_orig_load = main_mod.load_config


async def _timed_probe(*args, **kwargs):
    _mark("probe_ollama 开始")
    result = await _orig_probe(*args, **kwargs)
    _mark(f"probe_ollama 结束（available={result.available}）")
    return result


def _timed_load(*args, **kwargs):
    _mark("load_config 开始")
    result = _orig_load(*args, **kwargs)
    _mark("load_config 结束")
    return result


main_mod.probe_ollama = _timed_probe
main_mod.load_config = _timed_load

# --- 桩：lifespan 包装（测 uvicorn.run → lifespan 之间的 loop 初始化耗时） ---
from contextlib import asynccontextmanager  # noqa: E402

_orig_lifespan = app.router.lifespan_context


@asynccontextmanager
async def _timed_lifespan(a):
    _mark("lifespan 开始（此前为 loop 初始化/socket 绑定）")
    async with _orig_lifespan(a):
        _mark("lifespan startup 完成（开始接受连接）")
        yield


app.router.lifespan_context = _timed_lifespan

if __name__ == "__main__":
    _mark("uvicorn.run 调用")
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.environ.get("MOCHI_SIDECAR_PORT", "8199")),
        log_level="info",
    )
