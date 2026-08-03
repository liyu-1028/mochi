"""API Key 钥匙串管理（规范：docs/specs/config-format.md §3）。

红线：Key 永不落配置文件/日志，只存 OS 钥匙串；配置文件仅持有 key_ref。
- service 名即 key_ref：``mochi:provider:<id>``；
- 测试/CI 注入 :class:`InMemoryKeyring` 隔离真实钥匙串；
- dev 覆盖：仅当 ``MOCHI_DEV_KEYS=1`` 时读取 ``MOCHI_API_KEY_<ID>`` 环境变量，
  生产路径永不读环境变量（ADR-0002 D2）。
"""

from __future__ import annotations

import contextlib
import os

import keyring
from keyring.backend import KeyringBackend
from keyring.errors import KeyringError

KEY_REF_PREFIX = "mochi:provider"
_USERNAME = "api_key"
_DEV_KEYS_ENV = "MOCHI_DEV_KEYS"
_DEV_KEY_PREFIX = "MOCHI_API_KEY_"


def key_ref_for(provider_id: str) -> str:
    """provider id → 钥匙串条目名（即配置文件中的 key_ref 值）。"""
    return f"{KEY_REF_PREFIX}:{provider_id}"


class KeyStoreError(RuntimeError):
    """钥匙串读写失败（无可用后端、权限问题等）。"""


class InMemoryKeyring(KeyringBackend):
    """进程内钥匙串：测试/CI 隔离用，行为与真实后端一致。"""

    priority = 1  # 仅供显式 set_keyring 注入，不参与自动发现竞争

    def __init__(self) -> None:
        super().__init__()
        self._store: dict[tuple[str, str], str] = {}

    def set_password(self, service: str, username: str, password: str) -> None:
        self._store[(service, username)] = password

    def get_password(self, service: str, username: str) -> str | None:
        return self._store.get((service, username))

    def delete_password(self, service: str, username: str) -> None:
        if (service, username) not in self._store:
            raise KeyringError(f"条目不存在：{service}")
        del self._store[(service, username)]


class KeyStore:
    """钥匙串访问封装。所有 Key 读写必须经过本类。"""

    def set_key(self, provider_id: str, secret: str) -> str:
        """写入 Key，返回 key_ref。"""
        ref = key_ref_for(provider_id)
        try:
            keyring.get_keyring().set_password(ref, _USERNAME, secret)
        except KeyringError as exc:
            raise KeyStoreError(f"钥匙串写入失败：{exc}") from exc
        return ref

    def get_key(self, provider_id: str) -> str | None:
        """读取 Key；不存在返回 None。dev 环境变量覆盖见模块文档。"""
        override = _dev_env_key(provider_id)
        if override is not None:
            return override
        try:
            return keyring.get_keyring().get_password(key_ref_for(provider_id), _USERNAME)
        except KeyringError:
            return None

    def delete_key(self, provider_id: str) -> None:
        """删除 Key；条目不存在时静默（幂等）。"""
        with contextlib.suppress(KeyringError):
            keyring.get_keyring().delete_password(key_ref_for(provider_id), _USERNAME)

    @staticmethod
    def mask(secret: str) -> str:
        """脱敏展示：保留首 3 位与末 4 位（如 ``sk-***ab12``）。"""
        if len(secret) <= 8:
            return "***"
        return f"{secret[:3]}***{secret[-4:]}"


def _dev_env_key(provider_id: str) -> str | None:
    if os.environ.get(_DEV_KEYS_ENV) != "1":
        return None
    env_name = _DEV_KEY_PREFIX + provider_id.upper().replace("-", "_")
    return os.environ.get(env_name)
