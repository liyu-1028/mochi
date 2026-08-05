"""REST 管理端点测试：provider CRUD、Key 脱敏、守卫、连通性、日志脱敏。"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from mochi_server.agent.registry import ProviderRegistry
from mochi_server.api.security import SensitiveDataFilter, scrub_sensitive
from mochi_server.config import AppConfig, ModelConfig, ModelProviderConfig, load_config
from mochi_server.main import create_app
from mochi_server.secrets import KeyStore, key_ref_for

_RAW_KEY = "sk-live-secret-ab12"


def _cloud_config() -> AppConfig:
    return AppConfig(
        model=ModelConfig(
            default_provider="cloud",
            providers={
                "cloud": ModelProviderConfig(
                    kind="openai_compatible",
                    display_name="云端",
                    base_url="https://api.example.com/v1",
                    model="example-chat",
                    key_ref=key_ref_for("cloud"),
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
    assert "sk-***ab12" in text  # 只回掩码
    providers = resp.json()["model"]["providers"]
    assert providers[0]["keyRef"] == "mochi:provider:cloud"
    assert providers[0]["isDefault"] is True


def test_list_providers_masked(client):
    resp = client.get("/config/providers")
    assert resp.status_code == 200
    assert _RAW_KEY not in resp.text
    assert resp.json()[0]["maskedKey"] == "sk-***ab12"


# ---------------------------------------------------------------------------
# 创建 / 更新 / 删除
# ---------------------------------------------------------------------------


def test_create_provider_stores_key_in_keychain(client):
    resp = client.post(
        "/config/providers",
        json={
            "id": "deepseek",
            "kind": "openai_compatible",
            "displayName": "DeepSeek",
            "baseUrl": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "apiKey": "sk-new-key-xy98",
        },
    )
    assert resp.status_code == 201, resp.text
    assert "sk-new-key-xy98" not in resp.text
    assert resp.json()["maskedKey"] == "sk-***xy98"

    # Key 进了钥匙串；配置文件只有 key_ref，无明文
    assert KeyStore().get_key("deepseek") == "sk-new-key-xy98"
    config_text = client.app.state.config_path.read_text(encoding="utf-8")
    assert "mochi:provider:deepseek" in config_text
    assert "sk-new-key-xy98" not in config_text

    # registry 已热更新（切换无需重启）
    registry: ProviderRegistry = client.app.state.registry
    assert "deepseek" in registry.config.model.providers


def test_create_provider_conflict(client):
    resp = client.post(
        "/config/providers",
        json={"id": "cloud", "kind": "ollama", "displayName": "x", "model": "m"},
    )
    assert resp.status_code == 409


def test_create_provider_invalid_id(client):
    resp = client.post(
        "/config/providers",
        json={"id": "Bad ID!", "kind": "ollama", "displayName": "x", "model": "m"},
    )
    assert resp.status_code == 422


def test_update_provider_partial_and_rotate_key(client):
    resp = client.put(
        "/config/providers/cloud",
        json={"model": "example-chat-v2", "apiKey": "sk-rotated-77"},
    )
    assert resp.status_code == 200
    assert resp.json()["model"] == "example-chat-v2"
    assert "sk-rotated-77" not in resp.text
    assert KeyStore().get_key("cloud") == "sk-rotated-77"


def test_update_missing_provider(client):
    assert client.put("/config/providers/ghost", json={"model": "m"}).status_code == 404


def test_delete_provider_removes_key_and_falls_back_to_trial(client):
    resp = client.delete("/config/providers/cloud")
    assert resp.status_code == 204
    assert KeyStore().get_key("cloud") is None  # 钥匙串条目同步删除

    registry: ProviderRegistry = client.app.state.registry
    assert registry.config.model.default_provider == "trial"


def test_set_default_provider(client):
    client.post(
        "/config/providers",
        json={"id": "ollama", "kind": "ollama", "displayName": "本地", "model": "qwen3:8b"},
    )
    resp = client.put("/config/providers/ollama/default")
    assert resp.status_code == 200
    assert resp.json()["defaultProvider"] == "ollama"
    assert client.app.state.registry.config.model.default_provider == "ollama"


def test_set_default_unknown_provider(client):
    assert client.put("/config/providers/ghost/default").status_code == 404


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
# 连通性测试与 Ollama 状态
# ---------------------------------------------------------------------------


def test_connectivity_trial_always_ok(client):
    resp = client.post("/config/providers/trial/test")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_connectivity_unknown_provider(client):
    resp = client.post("/config/providers/ghost/test")
    assert resp.json()["ok"] is False


def test_connectivity_uses_adapter_ping(client, monkeypatch):
    from mochi_server.agent.adapters.openai_compat import OpenAICompatibleAdapter

    async def fake_ping(self):
        return True, "连接成功"

    monkeypatch.setattr(OpenAICompatibleAdapter, "ping", fake_ping)
    resp = client.post("/config/providers/cloud/test")
    assert resp.json() == {"ok": True, "hint": "连接成功"}


def test_ollama_status_endpoint(client, monkeypatch):
    from mochi_server.agent import ollama_probe
    from mochi_server.agent.ollama_probe import OllamaProbeResult

    async def fake_probe(base_url=None, **kwargs):
        return OllamaProbeResult(available=True, models=["qwen3:8b"])

    monkeypatch.setattr(ollama_probe, "probe_ollama", fake_probe)
    monkeypatch.setattr("mochi_server.api.config_routes.probe_ollama", fake_probe)
    resp = client.get("/config/providers/ollama-status")
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
        "/config/providers",
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
        "/config/providers/trial/default",
        headers={
            "origin": "http://evil.example.com",
            "access-control-request-method": "PUT",
        },
    )
    assert resp.status_code == 400
    assert "access-control-allow-origin" not in resp.headers


def test_cors_headers_present_on_actual_get(client):
    resp = client.get("/config/providers", headers={"origin": "http://localhost:1420"})
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "http://localhost:1420"


def test_no_cors_headers_without_origin(client):
    # 非浏览器客户端（curl / 未来 Tauri IPC 直连）不带 Origin，行为不变
    resp = client.get("/config/providers")
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
