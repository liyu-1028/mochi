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
