"""数据目录解析（规范：docs/specs/config-format.md §1/§2）。

sidecar 独立于桌面壳运行，需自行解析用户数据目录：
- 与 Tauri app_data_dir（identifier=app.mochi.desktop）字面对齐，双端同目录；
- ``MOCHI_DATA_DIR`` 环境变量覆盖（dev/测试专用）；
- 便携模式（Windows zip 版）：解压目录存在 ``mochi.portable`` 标记时，
  解压目录即数据目录（Rust 侧 datadir.rs 同语义探测，双侧对齐）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from platformdirs import user_data_dir

APP_IDENTIFIER = "app.mochi.desktop"
DATA_DIR_ENV = "MOCHI_DATA_DIR"

#: 便携模式标记文件名（zip 产物根目录内置）
PORTABLE_MARKER = "mochi.portable"
#: 从可执行文件向上探测的最大层级：sidecar 位于 <root>/resources/sidecar/，
#: 向上 3 层到根；余量 1 层。避免一路走到盘根误命中同名文件。
_PORTABLE_MAX_LEVELS = 4


def get_data_dir(*, create: bool = True) -> Path:
    """用户数据目录。优先级：MOCHI_DATA_DIR > 便携标记 > platformdirs。"""
    override = os.environ.get(DATA_DIR_ENV)
    if override:
        path = Path(override).expanduser().resolve()
    else:
        portable = _portable_data_dir()
        path = portable if portable is not None else Path(_platform_data_dir())
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def get_config_path() -> Path:
    """config.toml 路径（sidecar 为配置唯一事实源）。"""
    return get_data_dir() / "config.toml"


def get_skins_dir(*, create: bool = True) -> Path:
    """用户皮肤目录：<userData>/skins/（M1-S1，导入皮肤落盘处）。"""
    path = get_data_dir(create=create) / "skins"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def _platform_data_dir() -> str:
    # appauthor=False 避免 Windows 下出现 appname\appname 双层目录；
    # roaming=True 使 Windows 落在 %APPDATA%（与 Tauri app_data_dir 一致）。
    return user_data_dir(APP_IDENTIFIER, appauthor=False, roaming=True)


def _portable_data_dir() -> Path | None:
    """便携模式探测入口：从 sidecar 可执行文件向上找 ``mochi.portable``。"""
    try:
        exe = Path(sys.executable).resolve()
    except OSError:  # pragma: no cover - 可执行路径异常解析失败
        return None
    return find_portable_marker(exe)


def find_portable_marker(exe: Path) -> Path | None:
    """纯函数：从 ``exe`` 所在目录逐级向上（≤ _PORTABLE_MAX_LEVELS 层）
    找便携标记；命中则返回该目录（即数据目录），未命中返回 None。

    Windows 便携布局 ``<root>/resources/sidecar/mochi-server.exe``：
    向上 3 层命中根目录的标记。源码运行（uv run）时向上是仓库目录，
    不会有标记，自然回落默认目录。
    """
    for candidate in exe.parents[:_PORTABLE_MAX_LEVELS]:
        if (candidate / PORTABLE_MARKER).is_file():
            return candidate
    return None
