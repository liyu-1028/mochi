"""模型厂商目录：为设置界面提供友好默认值，运行时不硬编码在前端。

目录只描述稳定的接入知识（认证方式、支持协议、默认端点）；模型名称仍允许
用户手填，避免把快速变化的厂商模型清单固化进发行包。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .config import OLLAMA_DEFAULT_BASE_URL, WireProtocol

AuthKind = Literal["api_key", "none"]


class ProviderPreset(BaseModel):
    id: str
    display_name: str
    description: str
    auth_kind: AuthKind
    protocols: list[WireProtocol]
    recommended_protocol: WireProtocol
    default_endpoints: dict[WireProtocol, str] = Field(default_factory=dict)
    model_placeholder: str
    allows_custom_endpoint: bool = True


_PRESETS = (
    ProviderPreset(
        id="dashscope",
        display_name="阿里云百炼",
        description="适合通义千问及百炼托管模型",
        auth_kind="api_key",
        protocols=["openai_responses", "openai_chat"],
        recommended_protocol="openai_responses",
        default_endpoints={
            "openai_chat": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "openai_responses": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        },
        model_placeholder="如 qwen3.8-flash",
    ),
    ProviderPreset(
        id="zhipu",
        display_name="智谱 AI",
        description="GLM 系列模型，Chat 与 Responses 使用不同地址",
        auth_kind="api_key",
        protocols=["openai_responses", "openai_chat"],
        recommended_protocol="openai_responses",
        default_endpoints={
            "openai_chat": "https://open.bigmodel.cn/api/paas/v4",
            "openai_responses": "https://open.bigmodel.cn/api/v1",
        },
        model_placeholder="如 glm-5.3-flash",
    ),
    ProviderPreset(
        id="openai",
        display_name="OpenAI",
        description="OpenAI 官方接口",
        auth_kind="api_key",
        protocols=["openai_responses", "openai_chat"],
        recommended_protocol="openai_responses",
        default_endpoints={
            "openai_chat": "https://api.openai.com/v1",
            "openai_responses": "https://api.openai.com/v1",
        },
        model_placeholder="如 gpt-5-mini",
    ),
    ProviderPreset(
        id="anthropic",
        display_name="Anthropic",
        description="Claude 官方 Messages 接口",
        auth_kind="api_key",
        protocols=["anthropic_messages"],
        recommended_protocol="anthropic_messages",
        default_endpoints={},
        model_placeholder="如 claude-sonnet-4-5",
    ),
    ProviderPreset(
        id="ollama",
        display_name="Ollama（本地）",
        description="运行在本机，无需 API Key",
        auth_kind="none",
        protocols=["openai_chat"],
        recommended_protocol="openai_chat",
        default_endpoints={"openai_chat": OLLAMA_DEFAULT_BASE_URL},
        model_placeholder="如 qwen3:8b",
    ),
    ProviderPreset(
        id="custom",
        display_name="自定义兼容接口",
        description="适用于其他 OpenAI 或 Anthropic 兼容服务",
        auth_kind="api_key",
        protocols=["openai_chat", "openai_responses", "anthropic_messages"],
        recommended_protocol="openai_chat",
        default_endpoints={},
        model_placeholder="填写服务商提供的模型名称",
    ),
)

CATALOG = {preset.id: preset for preset in _PRESETS}


def get_preset(preset_id: str) -> ProviderPreset:
    try:
        return CATALOG[preset_id]
    except KeyError as exc:
        raise ValueError(f"未知模型厂商模板：{preset_id}") from exc


def catalog_view() -> list[dict]:
    return [preset.model_dump(mode="json", by_alias=True) for preset in _PRESETS]
