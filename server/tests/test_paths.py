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
