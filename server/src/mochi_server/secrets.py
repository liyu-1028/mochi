"""API Key 钥匙串管理（规范：docs/specs/config-format.md §3）。

红线：Key 永不落配置文件/日志，只存 OS 钥匙串；配置文件仅持有 key_ref。
- service 名即 key_ref：``mochi:provider:<id>``；
- 测试/CI 注入 :class:`InMemoryKeyring` 隔离真实钥匙串；
- dev 覆盖：仅当 ``MOCHI_DEV_KEYS=1`` 时读取 ``MOCHI_API_KEY_<ID>`` 环境变量，
  生产路径永不读环境变量（ADR-0002 D2）。

macOS 兜底（M1-CTX）：native keyring 条目 ACL 绑定创建进程的代码签名身份，
PyInstaller 每次重建 sidecar 都改变身份，旧条目对新进程不可写（set_password
报 -25244，前端表现为添加模型失败）。native 失败时改用 ``/usr/bin/security``
CLI——它以登录用户身份访问钥匙串、与调用方二进制身份无关，可跨重建读写。
"""

from __future__ import annotations

import contextlib
import logging
import os
import subprocess
import sys

import keyring
from keyring.backend import KeyringBackend
from keyring.errors import KeyringError

logger = logging.getLogger(__name__)

KEY_REF_PREFIX = "mochi:provider"
_USERNAME = "api_key"
_DEV_KEYS_ENV = "MOCHI_DEV_KEYS"
_DEV_KEY_PREFIX = "MOCHI_API_KEY_"
_SECURITY_CLI = "/usr/bin/security"


def _on_macos() -> bool:
    return sys.platform == "darwin"


def _cli_set(service: str, username: str, secret: str) -> None:
    """macOS `security` CLI 写入/更新条目（-U：已存在则更新）。"""
    subprocess.run(
        [_SECURITY_CLI, "add-generic-password", "-U", "-s", service, "-a", username, "-w", secret],
        check=True,
        capture_output=True,
    )


def _cli_get(service: str, username: str) -> str | None:
    """读取条目明文（经 stdout 捕获，不进 argv/日志）。不存在返回 None。"""
    result = subprocess.run(
        [_SECURITY_CLI, "find-generic-password", "-s", service, "-a", username, "-w"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.rstrip("\n")


def _cli_delete(service: str, username: str) -> None:
    subprocess.run(
        [_SECURITY_CLI, "delete-generic-password", "-s", service, "-a", username],
        capture_output=True,
    )


def key_ref_for(provider_id: str) -> str:
    """provider id → 钥匙串条目名（即配置文件中的 key_ref）。"""
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
        """写入 Key，返回 key_ref。native 失败（跨身份 ACL）时 CLI 兜底。"""
        ref = key_ref_for(provider_id)
        try:
            keyring.get_keyring().set_password(ref, _USERNAME, secret)
            return ref
        except KeyringError as exc:
            if _on_macos():
                logger.warning("native 钥匙串写入失败（%s），改用 security CLI 兜底", exc)
                try:
                    _cli_set(ref, _USERNAME, secret)
                    return ref
                except (subprocess.CalledProcessError, OSError) as cli_exc:
                    raise KeyStoreError(f"钥匙串写入失败：{cli_exc}") from cli_exc
            raise KeyStoreError(f"钥匙串写入失败：{exc}") from exc

    def get_key(self, provider_id: str) -> str | None:
        """读取 Key；不存在返回 None。dev 环境变量覆盖见模块文档。"""
        override = _dev_env_key(provider_id)
        if override is not None:
            return override
        ref = key_ref_for(provider_id)
        try:
            secret = keyring.get_keyring().get_password(ref, _USERNAME)
        except KeyringError:
            secret = None
        if secret is None and _on_macos():
            # 与 set_key 写路径对称的 CLI 兜底，覆盖两种 native 失败形态：
            # 1) 抛 KeyringError（条目被 ACL 明确拒绝）；
            # 2) 静默返回 None——跨重建签名身份不一致时 SecItemCopyMatching
            #    读不到旧条目但不抛异常，仅异常兜底会漏掉此路径（测试报告
            #    2026-08-05 Bug 2：重打包后已存 Key 读不出）。
            with contextlib.suppress(OSError):
                secret = _cli_get(ref, _USERNAME)
        return secret

    def delete_key(self, provider_id: str) -> None:
        """删除条目；条目不存在时静默（幂等）。"""
        ref = key_ref_for(provider_id)
        try:
            keyring.get_keyring().delete_password(ref, _USERNAME)
        except KeyringError:
            if _on_macos():
                with contextlib.suppress(OSError):
                    _cli_delete(ref, _USERNAME)

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
