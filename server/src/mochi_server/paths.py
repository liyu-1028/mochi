"""数据目录解析（规范：docs/specs/config-format.md §1/§2）。

sidecar 独立于桌面壳运行，需自行解析用户数据目录：
- 与 Tauri app_data_dir（identifier=app.mochi.desktop）字面对齐，双端同目录；
- ``MOCHI_DATA_DIR`` 环境变量覆盖（dev/测试专用）。
"""

from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_data_dir

APP_IDENTIFIER = "app.mochi.desktop"
DATA_DIR_ENV = "MOCHI_DATA_DIR"


def get_data_dir(*, create: bool = True) -> Path:
    """用户数据目录。优先级：MOCHI_DATA_DIR > platformdirs（与 Tauri 对齐）。"""
    override = os.environ.get(DATA_DIR_ENV)
    path = Path(override).expanduser().resolve() if override else Path(_platform_data_dir())
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
