"""REST 管理端点测试：模型配置、Key 脱敏、守卫、连通性、日志脱敏。"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from mochi_server.agent.registry import ProviderRegistry
from mochi_server.api.security import SensitiveDataFilter, scrub_sensitive
from mochi_server.config import (
    AppConfig,
    ModelConfig,
    ModelConnectionConfig,
    ModelProfileConfig,
    load_config,
)
from mochi_server.main import create_app
from mochi_server.secrets import KeyStore, key_ref_for

_RAW_KEY = "sk-live-secret-ab12"


def _cloud_config() -> AppConfig:
    return AppConfig(
        model=ModelConfig(
            default_profile="cloud",
            connections={
                "cloud": ModelConnectionConfig(
                    preset_id="custom",
                    display_name="云端",
                    endpoints={"openai_chat": "https://api.example.com/v1"},
                    key_ref=key_ref_for("cloud"),
                )
            },
            profiles={
                "cloud": ModelProfileConfig(
                    connection_id="cloud",
                    display_name="云端模型",
                    protocol="openai_chat",
                    model="example-chat",
                )
            },
        )
    )


@pytest.fixture
def client() -> TestClient:
    KeyStore().set_key("cloud", _RAW_KEY)  # 写入 conftest 注入的内存钥匙串
    with TestClient(create_app(config=_cloud_config())) as c:
        yield c


# ---------------------------------------------------------------------------
# 读取与脱敏
# ---------------------------------------------------------------------------


def test_get_config_never_echoes_raw_key(client):
    resp = client.get("/config")
    assert resp.status_code == 200
    text = resp.text
    assert _RAW_KEY not in text  # 红线：任何响应不得含明文 Key
    model = resp.json()["model"]
    assert model["connections"]["cloud"]["key_ref"] == "mochi:provider:cloud"
    assert model["default_profile"] == "cloud"


def test_list_model_profiles_masked(client):
    resp = client.get("/config/model-profiles")
    assert resp.status_code == 200
    assert _RAW_KEY not in resp.text
    assert resp.json()[0]["maskedKey"] == "sk-***ab12"


# ---------------------------------------------------------------------------
# 厂商目录与“测试并保存”
# ---------------------------------------------------------------------------


def _configure_payload(**overrides) -> dict:
    payload = {
        "profileId": "deepseek-chat",
        "connectionId": "deepseek",
        "presetId": "custom",
        "connectionName": "DeepSeek",
        "profileName": "DeepSeek Chat",
        "protocol": "openai_chat",
        "baseUrl": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "apiKey": "sk-new-key-xy98",
    }
    payload.update(overrides)
    return payload


def test_model_presets_expose_friendly_defaults(client):
    resp = client.get("/config/model-presets")
    assert resp.status_code == 200
    presets = {item["id"]: item for item in resp.json()}
    assert presets["dashscope"]["recommendedProtocol"] == "openai_responses"
    assert presets["zhipu"]["defaultEndpoints"]["openai_chat"].endswith("/paas/v4")
    assert presets["ollama"]["authKind"] == "none"


def test_configure_profile_tests_then_stores_key(client, monkeypatch):
    from mochi_server.agent import LangChainAdapter

    async def fake_ping(self):
        return True, "连接成功"

    monkeypatch.setattr(LangChainAdapter, "ping", fake_ping)
    resp = client.post(
        "/config/model-profiles/configure",
        json=_configure_payload(),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True
    assert "sk-new-key-xy98" not in resp.text
    assert resp.json()["profile"]["maskedKey"] == "sk-***xy98"

    # Key 进了钥匙串；配置文件只有 key_ref，无明文
    assert KeyStore().get_key("deepseek") == "sk-new-key-xy98"
    config_text = client.app.state.config_path.read_text(encoding="utf-8")
    assert "mochi:provider:deepseek" in config_text
    assert "sk-new-key-xy98" not in config_text

    registry: ProviderRegistry = client.app.state.registry
    assert "deepseek" in registry.config.model.connections
    assert registry.config.model.profiles["deepseek-chat"].connection_id == "deepseek"


def test_configure_failure_does_not_persist_key_or_config(client, monkeypatch):
    from mochi_server.agent import LangChainAdapter

    async def fake_ping(self):
        return False, "模型不存在"

    monkeypatch.setattr(LangChainAdapter, "ping", fake_ping)
    resp = client.post(
        "/config/model-profiles/configure",
        json=_configure_payload(),
    )
    assert resp.json() == {"ok": False, "hint": "模型不存在"}
    assert KeyStore().get_key("deepseek") is None
    assert "deepseek" not in client.app.state.registry.config.model.connections


def test_configure_invalid_id(client):
    resp = client.post(
        "/config/model-profiles/configure",
        json=_configure_payload(profileId="Bad ID!"),
    )
    assert resp.status_code == 422


def test_edit_profile_reuses_existing_key(client, monkeypatch):
    from mochi_server.agent import LangChainAdapter

    captured = {}

    async def fake_ping(self):
        captured["key"] = self._model.openai_api_key.get_secret_value()
        return True, "连接成功"

    monkeypatch.setattr(LangChainAdapter, "ping", fake_ping)
    resp = client.post(
        "/config/model-profiles/configure",
        json={
            "profileId": "cloud",
            "connectionId": "cloud",
            "presetId": "custom",
            "connectionName": "云端",
            "profileName": "云端模型 v2",
            "protocol": "openai_chat",
            "baseUrl": "https://api.example.com/v1",
            "model": "example-chat-v2",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["profile"]["model"] == "example-chat-v2"
    assert captured["key"] == _RAW_KEY


def test_add_second_profile_reuses_one_connection_and_key(client, monkeypatch):
    from mochi_server.agent import LangChainAdapter

    async def fake_ping(self):
        return True, "连接成功"

    monkeypatch.setattr(LangChainAdapter, "ping", fake_ping)
    resp = client.post(
        "/config/model-profiles/configure",
        json={
            "profileId": "cloud-reasoning",
            "connectionId": "cloud",
            "presetId": "custom",
            "connectionName": "云端",
            "profileName": "推理模型",
            "protocol": "openai_responses",
            "baseUrl": "https://api.example.com/v1",
            "model": "example-reasoning",
        },
    )
    assert resp.status_code == 200
    config = client.app.state.registry.config.model
    assert list(config.connections) == ["cloud"]
    assert set(config.profiles) == {"cloud", "cloud-reasoning"}
    assert config.connections["cloud"].endpoints == {
        "openai_chat": "https://api.example.com/v1",
        "openai_responses": "https://api.example.com/v1",
    }
    assert KeyStore().get_key("cloud") == _RAW_KEY


def test_config_save_failure_restores_previous_key(client, monkeypatch):
    from mochi_server.agent import LangChainAdapter

    async def fake_ping(self):
        return True, "连接成功"

    def fail_save(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(LangChainAdapter, "ping", fake_ping)
    monkeypatch.setattr("mochi_server.api.config_routes.save_config", fail_save)
    resp = client.post(
        "/config/model-profiles/configure",
        json={
            "profileId": "cloud",
            "connectionId": "cloud",
            "presetId": "custom",
            "connectionName": "云端",
            "profileName": "云端模型",
            "protocol": "openai_chat",
            "baseUrl": "https://api.example.com/v1",
            "model": "example-chat-v2",
            "apiKey": "sk-replacement",
        },
    )
    assert resp.status_code == 500
    assert KeyStore().get_key("cloud") == _RAW_KEY
    assert client.app.state.registry.config.model.profiles["cloud"].model == "example-chat"


def test_delete_connection_removes_profiles_key_and_falls_back_to_trial(client):
    resp = client.delete("/config/model-connections/cloud")
    assert resp.status_code == 204
    assert KeyStore().get_key("cloud") is None  # 钥匙串条目同步删除

    registry: ProviderRegistry = client.app.state.registry
    assert registry.config.model.default_profile == "trial"
    assert registry.config.model.profiles == {}


def test_set_default_profile(client):
    resp = client.put("/config/model-profiles/trial/default")
    assert resp.status_code == 200
    assert resp.json()["defaultProfile"] == "trial"
    assert client.app.state.registry.config.model.default_profile == "trial"


def test_set_default_unknown_profile(client):
    assert client.put("/config/model-profiles/ghost/default").status_code == 404


# ---------------------------------------------------------------------------
# 通用设置（界面语言，M1-CTX）
# ---------------------------------------------------------------------------


def test_update_general_language_persists(client):
    resp = client.put("/config/general", json={"language": "en"})
    assert resp.status_code == 200
    assert resp.json()["language"] == "en"
    assert client.app.state.registry.config.general.language == "en"
    # 原子落盘：重新从磁盘读取仍在
    on_disk = load_config(client.app.state.config_path)
    assert on_disk.general.language == "en"


def test_update_general_invalid_language_rejected(client):
    resp = client.put("/config/general", json={"language": "fr"})
    assert resp.status_code == 422
    assert client.app.state.registry.config.general.language == "zh-CN"


def test_update_general_empty_body_keeps_defaults(client):
    resp = client.put("/config/general", json={})
    assert resp.status_code == 200
    assert resp.json()["language"] == "zh-CN"


def test_update_general_power_save_persists(client):
    """省电模式（2.6）：PUT 生效 + 原子落盘 + camelCase 回显。"""
    resp = client.put("/config/general", json={"powerSave": True})
    assert resp.status_code == 200
    assert resp.json()["powerSave"] is True
    assert client.app.state.registry.config.general.power_save is True
    on_disk = load_config(client.app.state.config_path)
    assert on_disk.general.power_save is True


# ---------------------------------------------------------------------------
# [voice] 读写（M1-S0 托盘静音）
# ---------------------------------------------------------------------------


def test_get_voice_returns_camel_case_defaults(client):
    resp = client.get("/config/voice")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ttsEnabled"] is True
    assert data["engine"] == "edge"
    assert data["voiceId"] == "zh-CN-XiaoxiaoNeural"
    assert data["volume"] == 1.0
    assert data["rate"] == 1.0
    assert data["muted"] is False


def test_put_voice_muted_persists(client):
    resp = client.put("/config/voice", json={"muted": True})
    assert resp.status_code == 200
    assert resp.json()["muted"] is True
    assert client.app.state.registry.config.voice.muted is True
    # 原子落盘：重新从磁盘读取仍在
    on_disk = load_config(client.app.state.config_path)
    assert on_disk.voice.muted is True


def test_put_voice_partial_update_keeps_others(client):
    resp = client.put("/config/voice", json={"volume": 0.5})
    assert resp.status_code == 200
    data = resp.json()
    assert data["volume"] == 0.5
    assert data["muted"] is False  # 未传字段不变
    assert data["voiceId"] == "zh-CN-XiaoxiaoNeural"


def test_put_voice_out_of_range_rejected(client):
    resp = client.put("/config/voice", json={"volume": 1.5})
    assert resp.status_code == 422
    assert client.app.state.registry.config.voice.volume == 1.0
    resp = client.put("/config/voice", json={"engine": "piper"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# [character.persona] 人格配置（功能清单 6.13）
# ---------------------------------------------------------------------------


def test_get_persona_returns_current_and_presets(client):
    resp = client.get("/config/persona")
    assert resp.status_code == 200
    data = resp.json()
    assert data["current"] == {
        "soulPreset": "",
        "soulCustom": "",
        "personalityPreset": "",
        "personalityCustom": "",
        "stylePreset": "",
        "styleCustom": "",
    }
    presets = data["presets"]
    assert set(presets.keys()) == {"soul", "personality", "style"}
    for dimension in presets.values():
        assert len(dimension) >= 4
        assert dimension[0]["name"]["zh-CN"] and dimension[0]["name"]["en"]


def test_put_persona_partial_update_persists(client):
    resp = client.put("/config/persona", json={"soulPreset": "warm_sun"})
    assert resp.status_code == 200
    assert resp.json()["soulPreset"] == "warm_sun"
    assert resp.json()["personalityPreset"] == ""  # 未传字段保持
    assert client.app.state.registry.config.character.persona.soul_preset == "warm_sun"
    on_disk = load_config(client.app.state.config_path)
    assert on_disk.character.persona.soul_preset == "warm_sun"


def test_put_persona_custom_text(client):
    resp = client.put("/config/persona", json={"styleCustom": "说话像海盗"})
    assert resp.status_code == 200
    assert resp.json()["styleCustom"] == "说话像海盗"


def test_put_persona_invalid_preset_rejected(client):
    resp = client.put("/config/persona", json={"soulPreset": "no_such_id"})
    assert resp.status_code == 422
    # 跨维度引用同样非法：warm_sun 是 soul 预设，不属于 style
    resp = client.put("/config/persona", json={"stylePreset": "warm_sun"})
    assert resp.status_code == 422
    assert client.app.state.registry.config.character.persona.soul_preset == ""


def test_put_persona_custom_too_long_rejected(client):
    resp = client.put("/config/persona", json={"soulCustom": "字" * 501})
    assert resp.status_code == 422


def test_put_persona_reset_to_default(client):
    client.put(
        "/config/persona",
        json={"soulPreset": "warm_sun", "styleCustom": "自定义风格"},
    )
    resp = client.put(
        "/config/persona",
        json={
            "soulPreset": "",
            "soulCustom": "",
            "personalityPreset": "",
            "personalityCustom": "",
            "stylePreset": "",
            "styleCustom": "",
        },
    )
    assert resp.status_code == 200
    assert all(value == "" for value in resp.json().values())


def test_get_config_includes_persona(client):
    client.put("/config/persona", json={"personalityPreset": "tsundere_cat"})
    resp = client.get("/config")
    # /config 为原始 dump（snake_case，专属端点才出 camelCase——与 voice/general 一致）
    assert resp.json()["character"]["persona"]["personality_preset"] == "tsundere_cat"


# ---------------------------------------------------------------------------
# 连通性测试与 Ollama 状态
# ---------------------------------------------------------------------------


def test_connectivity_trial_always_ok(client):
    resp = client.post("/config/model-profiles/trial/test")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_connectivity_unknown_profile(client):
    resp = client.post("/config/model-profiles/ghost/test")
    assert resp.json()["ok"] is False


def test_connectivity_uses_adapter_ping(client, monkeypatch):
    from mochi_server.agent import LangChainAdapter

    async def fake_ping(self):
        return True, "连接成功"

    monkeypatch.setattr(LangChainAdapter, "ping", fake_ping)
    resp = client.post("/config/model-profiles/cloud/test")
    assert resp.json() == {"ok": True, "hint": "连接成功"}


def test_configure_invalid_preset_rejected(client):
    resp = client.post(
        "/config/model-profiles/configure",
        json=_configure_payload(presetId="nope"),
    )
    assert resp.status_code == 422


def test_ollama_status_endpoint(client, monkeypatch):
    from mochi_server.agent import ollama_probe
    from mochi_server.agent.ollama_probe import OllamaProbeResult

    async def fake_probe(base_url=None, **kwargs):
        return OllamaProbeResult(available=True, models=["qwen3:8b"])

    monkeypatch.setattr(ollama_probe, "probe_ollama", fake_probe)
    monkeypatch.setattr("mochi_server.api.config_routes.probe_ollama", fake_probe)
    resp = client.get("/config/models/ollama-status")
    assert resp.status_code == 200
    assert resp.json()["available"] is True
    assert resp.json()["models"] == ["qwen3:8b"]


# ---------------------------------------------------------------------------
# CORS 跨域预检（回归：测试报告 2026-08-03 OPTIONS 405）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:1420",  # Vite dev server
        "http://127.0.0.1:1420",
        "tauri://localhost",  # Tauri v2 macOS 桌面壳
        "http://tauri.localhost",  # Tauri v2 Windows/Linux 桌面壳
    ],
)
def test_cors_preflight_allowed_for_known_origins(client, origin):
    resp = client.options(
        "/config/model-profiles/configure",
        headers={
            "origin": origin,
            "access-control-request-method": "POST",
            "access-control-request-headers": "content-type",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == origin
    assert "POST" in resp.headers["access-control-allow-methods"]


def test_cors_preflight_rejects_foreign_origin(client):
    # 恶意网页的源不得通过预检（安全红线：不用通配源）
    resp = client.options(
        "/config/model-profiles/trial/default",
        headers={
            "origin": "http://evil.example.com",
            "access-control-request-method": "PUT",
        },
    )
    assert resp.status_code == 400
    assert "access-control-allow-origin" not in resp.headers


def test_cors_headers_present_on_actual_get(client):
    resp = client.get("/config/model-profiles", headers={"origin": "http://localhost:1420"})
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "http://localhost:1420"


def test_no_cors_headers_without_origin(client):
    # 非浏览器客户端（curl / 未来 Tauri IPC 直连）不带 Origin，行为不变
    resp = client.get("/config/model-profiles")
    assert resp.status_code == 200
    assert "access-control-allow-origin" not in resp.headers


# ---------------------------------------------------------------------------
# 安全守卫与日志脱敏
# ---------------------------------------------------------------------------


def test_illegal_host_header_rejected(client):
    resp = client.get("/config", headers={"host": "evil.example.com"})
    assert resp.status_code == 403


def test_scrub_sensitive_masks_key_values():
    assert "***" in scrub_sensitive("api_key=sk-live-secret-ab12")
    assert "sk-live-secret-ab12" not in scrub_sensitive("key: sk-live-secret-ab12")
    # 普通文本不受影响
    assert scrub_sensitive("加载配置成功") == "加载配置成功"


def test_log_filter_scrubs_records(caplog):
    logger = logging.getLogger("mochi.test.redaction")
    logger.addFilter(SensitiveDataFilter())
    with caplog.at_level(logging.INFO, logger="mochi.test.redaction"):
        logger.info("用户提交了 api_key=%s", _RAW_KEY)
    assert _RAW_KEY not in caplog.text
    assert "***" in caplog.text
