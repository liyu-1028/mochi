"""KeyStore 钥匙串管理测试（内存后端由 conftest 全局注入）。"""

from __future__ import annotations

import pytest

from mochi_server.secrets import KeyStore, KeyStoreError, key_ref_for


@pytest.fixture
def store() -> KeyStore:
    return KeyStore()


def test_key_ref_naming():
    assert key_ref_for("my_cloud") == "mochi:provider:my_cloud"


def test_set_get_roundtrip(store):
    ref = store.set_key("my_cloud", "sk-live-secret-ab12")
    assert ref == "mochi:provider:my_cloud"
    assert store.get_key("my_cloud") == "sk-live-secret-ab12"


def test_get_missing_returns_none(store):
    assert store.get_key("ghost") is None


def test_delete_is_idempotent(store):
    store.set_key("p1", "secret")
    store.delete_key("p1")
    assert store.get_key("p1") is None
    store.delete_key("p1")  # 二次删除不抛错


def test_mask_long_secret():
    assert KeyStore.mask("sk-live-secret-ab12") == "sk-***ab12"


def test_mask_short_secret_fully_hidden():
    assert KeyStore.mask("short") == "***"


def test_dev_env_override_enabled(store, monkeypatch):
    store.set_key("cloud", "keychain-value")
    monkeypatch.setenv("MOCHI_DEV_KEYS", "1")
    monkeypatch.setenv("MOCHI_API_KEY_CLOUD", "env-value")
    assert store.get_key("cloud") == "env-value"


def test_dev_env_override_disabled_without_flag(store, monkeypatch):
    store.set_key("cloud", "keychain-value")
    monkeypatch.delenv("MOCHI_DEV_KEYS", raising=False)
    monkeypatch.setenv("MOCHI_API_KEY_CLOUD", "env-value")
    assert store.get_key("cloud") == "keychain-value"


def test_dev_env_provider_id_normalized(store, monkeypatch):
    monkeypatch.setenv("MOCHI_DEV_KEYS", "1")
    monkeypatch.setenv("MOCHI_API_KEY_MY_CLOUD", "env-value")
    assert store.get_key("my-cloud") == "env-value"


def test_keystore_error_wraps_backend_failure(monkeypatch):
    from keyring.errors import KeyringError

    class BrokenKeyring:
        def set_password(self, service, username, password):
            raise KeyringError("钥匙串被锁定")

    monkeypatch.setattr("mochi_server.secrets.keyring.get_keyring", lambda: BrokenKeyring())
    with pytest.raises(KeyStoreError, match="钥匙串写入失败"):
        KeyStore().set_key("p1", "secret")
