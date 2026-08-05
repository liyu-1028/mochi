"""全局测试隔离：真实钥匙串与用户数据目录不进测试。"""

from __future__ import annotations

import keyring
import pytest

from mochi_server import paths
from mochi_server.secrets import InMemoryKeyring


@pytest.fixture(autouse=True)
def isolated_keyring():
    """全部测试使用内存钥匙串，绝不触碰开发机真实 Keychain。"""
    previous = keyring.get_keyring()
    keyring.set_keyring(InMemoryKeyring())
    yield
    keyring.set_keyring(previous)


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """全部测试的数据目录指向临时目录。"""
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(tmp_path / "mochi-data"))


@pytest.fixture(autouse=True)
def isolated_macos_flag(monkeypatch):
    """默认视为非 macOS：get_key 的 None 兜底会 spawn /usr/bin/security，
    测试不得触碰。macOS 兜底专项测试在测试体内显式置 True 覆盖。"""
    monkeypatch.setattr("mochi_server.secrets._on_macos", lambda: False)
