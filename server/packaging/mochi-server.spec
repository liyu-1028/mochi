# -*- mode: python ; coding: utf-8 -*-
# Mochi sidecar 生产构建（M0-S4，功能清单 1.2）。
#
# 构建方式：scripts/package-sidecar.sh（勿手工运行 pyinstaller，
# 该脚本负责 --clean 与产物落位 Tauri bundle.resources）。
#
# 选型记录见 docs/internal/adr/0004-packaging.md：
# - onedir + noarchive：onedir 每次启动都解压千余文件且走 zipimport，
#   实测冷启动 13-27s；onedir+noarchive（模块以 .pyc 散文件落盘）暖缓存
#   实测 spawn→/health <1s，满足 1.1 冷启动 ≤5s 验收
# - console=False：用户全程不接触终端（1.2 验收）；终端手动运行时 stderr 仍可见
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# uvicorn 用 importlib 动态挑选 loop/http/websocket/lifespan 实现，静态分析追踪不到；
# 显式声明后 PyInstaller 会分析这些模块并连带收集 uvloop/httptools/websockets。
hiddenimports = [
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
]
# keyring 经 entry points 动态发现后端（macOS Keychain / Windows Credentials 等）
hiddenimports += collect_submodules("keyring.backends")
# python-multipart 由 FastAPI 运行时按需导入（UploadFile，M1-S1 皮肤导入）
hiddenimports += ["multipart", "multipart.multipart"]
# edge-tts（M1-S2 TTS）：aiohttp 按平台动态挑选子模块，静态分析易漏；
# certifi 的 CA 包是数据文件，不 collect 则 HTTPS 握手失败
hiddenimports += ["edge_tts", "aiohttp", "certifi"]
hiddenimports += collect_submodules("aiohttp")

datas = collect_data_files("keyring")  # backends.toml 等优先级配置
datas += collect_data_files("certifi")  # cacert.pem

a = Analysis(
    ["entry.py"],
    pathex=["../src"],  # 相对 spec 文件目录 → server/src
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=True,  # 关键：散文件 .pyc 落盘，绕开 zipimport 的冷启动开销
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="mochi-server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="mochi-server",
)
