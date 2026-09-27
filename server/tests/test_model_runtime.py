"""ModelRuntime：配置域到厂商/协议调用目标的唯一解析边界。"""

from __future__ import annotations

import pytest

from mochi_server.config import (
    AppConfig,
    ModelConfig,
    ModelConnectionConfig,
    ModelProfileConfig,
)
from mochi_server.model_runtime import ModelRuntime
from mochi_server.secrets import KeyStore


def _runtime(
    *,
    preset_id: str = "zhipu",
    protocol: str = "openai_responses",
    endpoints: dict | None = None,
) -> ModelRuntime:
    config = AppConfig(
        model=ModelConfig(
            default_profile="glm",
            connections={
                "zhipu-account": ModelConnectionConfig(
                    preset_id=preset_id,
                    display_name="智谱账号",
                    endpoints=endpoints or {},
                )
            },
            profiles={
                "glm": ModelProfileConfig(
                    connection_id="zhipu-account",
                    display_name="GLM",
                    protocol=protocol,  # type: ignore[arg-type]
                    model="glm-5.3-flash",
                    context_window=131072,
                )
            },
        )
    )
    return ModelRuntime(config, KeyStore())


def test_resolve_uses_protocol_specific_catalog_endpoint() -> None:
    target = _runtime().resolve("glm")
    assert target.preset_id == "zhipu"
    assert target.protocol == "openai_responses"
    assert target.base_url == "https://open.bigmodel.cn/api/v1"
    assert target.context_window == 131072


def test_resolve_connection_endpoint_overrides_catalog_default() -> None:
    target = _runtime(endpoints={"openai_responses": "https://gateway.example.com/v1"}).resolve(
        "glm"
    )
    assert target.base_url == "https://gateway.example.com/v1"


def test_resolve_rejects_protocol_not_supported_by_preset() -> None:
    runtime = _runtime(preset_id="anthropic", protocol="openai_chat")
    with pytest.raises(ValueError, match="不支持协议"):
        runtime.resolve("glm")


def test_resolve_missing_profile_is_readable() -> None:
    with pytest.raises(ValueError, match="模型配置 ghost 不存在"):
        _runtime().resolve("ghost")
