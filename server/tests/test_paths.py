"""数据目录解析测试。"""

from __future__ import annotations

import pytest

from mochi_server import paths


def test_data_dir_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(tmp_path / "custom"))
    result = paths.get_data_dir()
    assert result == tmp_path / "custom"
    assert result.is_dir()  # 自动创建


def test_data_dir_env_override_no_create(tmp_path, monkeypatch):
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(tmp_path / "ghost"))
    result = paths.get_data_dir(create=False)
    assert result == tmp_path / "ghost"
    assert not result.exists()


def test_data_dir_default_aligns_with_tauri_identifier(monkeypatch):
    monkeypatch.delenv(paths.DATA_DIR_ENV, raising=False)
    result = paths.get_data_dir(create=False)
    # 与 Tauri app_data_dir 对齐：目录名为 bundle identifier（见 ADR-0002 D7）
    assert result.name == paths.APP_IDENTIFIER
    assert result.is_absolute()


def test_config_path_under_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(tmp_path))
    assert paths.get_config_path() == tmp_path / "config.toml"


@pytest.mark.parametrize("override", ["~/mochi-dev", "relative/dir"])
def test_env_override_resolves_absolute(override, monkeypatch):
    monkeypatch.setenv(paths.DATA_DIR_ENV, override)
    result = paths.get_data_dir(create=False)
    assert result.is_absolute()


class TestPortable:
    """便携模式（Windows zip 版）：mochi.portable 标记 → 解压目录即数据目录。"""

    def test_标记与_exe_同目录时命中(self, tmp_path):
        (tmp_path / paths.PORTABLE_MARKER).touch()
        exe = tmp_path / "mochi-server.exe"
        assert paths.find_portable_marker(exe) == tmp_path

    def test_安装布局向上三层命中根目录(self, tmp_path):
        # Windows 便携布局：<root>/resources/sidecar/mochi-server.exe
        (tmp_path / paths.PORTABLE_MARKER).touch()
        exe = tmp_path / "resources" / "sidecar" / "mochi-server.exe"
        assert paths.find_portable_marker(exe) == tmp_path

    def test_无标记返回_none(self, tmp_path):
        exe = tmp_path / "resources" / "sidecar" / "mochi-server.exe"
        assert paths.find_portable_marker(exe) is None

    def test_层级上限外的标记不命中(self, tmp_path):
        # sidecar 深 4 层，向上探测上限 4 层，根目录在第 5 层 → 不命中
        (tmp_path / paths.PORTABLE_MARKER).touch()
        exe = tmp_path / "a" / "b" / "c" / "d" / "mochi-server.exe"
        assert paths.find_portable_marker(exe) is None

    def test_环境变量优先于便携标记(self, tmp_path, monkeypatch):
        monkeypatch.setenv(paths.DATA_DIR_ENV, str(tmp_path / "env-dir"))
        monkeypatch.setattr(paths, "_portable_data_dir", lambda: tmp_path)
        assert paths.get_data_dir(create=False) == (tmp_path / "env-dir").resolve()

    def test_get_data_dir_便携命中时落到解压目录(self, tmp_path, monkeypatch):
        monkeypatch.delenv(paths.DATA_DIR_ENV, raising=False)
        monkeypatch.setattr(paths, "_portable_data_dir", lambda: tmp_path)
        assert paths.get_data_dir(create=False) == tmp_path
