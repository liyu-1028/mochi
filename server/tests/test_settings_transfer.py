"""设置备份实际端点往返；全部使用隔离的配置与内存钥匙串。"""

import pytest
from fastapi.testclient import TestClient

from mochi_server.config import AppConfig
from mochi_server.main import create_app


@pytest.fixture
def client():
    with TestClient(create_app(config=AppConfig())) as client:
        yield client


def test_export_import_roundtrip_preserves_visible_settings(client):
    client.put("/config/general", json={"language": "en", "powerSave": True})
    client.put("/config/voice", json={"ttsEnabled": False, "volume": 0.35, "rate": 1.3})
    client.put("/config/agent", json={"maxReplyChars": 220})
    client.put("/config/persona", json={"styleCustom": "说话温柔简洁"})
    response = client.get("/config/export")
    assert response.status_code == 200
    backup = response.json()
    assert backup["character"]["activeSkin"] == "mochi-vrm"
    assert backup["voice"]["ttsEnabled"] is False
    assert backup["persona"]["styleCustom"] == "说话温柔简洁"
    assert "model" not in backup and "keyRef" not in response.text
    client.put("/config/general", json={"language": "zh-CN", "powerSave": False})
    client.put("/config/voice", json={"ttsEnabled": True, "volume": 0.8})
    client.put("/config/agent", json={"maxReplyChars": 1000})
    client.put("/config/persona", json={"styleCustom": ""})
    result = client.post("/config/import", json=backup)
    assert result.status_code == 200
    assert client.get("/config").json()["general"]["language"] == "en"
    assert client.get("/config").json()["general"]["powerSave"] is True
    assert client.get("/config/voice").json()["volume"] == 0.35
    assert client.get("/config/agent").json()["maxReplyChars"] == 220
    assert client.get("/config/persona").json()["current"]["styleCustom"] == "说话温柔简洁"


@pytest.mark.parametrize(
    "invalid",
    [
        {"voice": {"volume": 7}},
        {"character": {"activeSkin": "not-installed"}},
        {"persona": {"soulPreset": "missing-preset"}},
        {"version": 99},
        {"voice": []},
    ],
)
def test_invalid_section_changes_nothing(client, invalid):
    before = client.get("/config").json()
    payload = {"general": {"language": "en", "powerSave": True}, **invalid}
    response = client.post("/config/import", json=payload)
    assert response.status_code == 422
    assert client.get("/config").json() == before


def test_legacy_snake_case_backup_imports_character_and_voice(client):
    result = client.post(
        "/config/import",
        json={
            "exportedAt": "2026-10-09T00:00:00Z",
            "general": {"language": "en"},
            "character": {"active_skin": ""},
            "voice": {"tts_enabled": False, "voice_id": "zh-CN-XiaoyiNeural"},
        },
    )
    assert result.status_code == 200
    assert client.get("/config/character").json()["activeSkin"] == ""
    assert client.get("/config/voice").json()["ttsEnabled"] is False
    assert client.get("/config/voice").json()["voiceId"] == "zh-CN-XiaoyiNeural"


@pytest.mark.parametrize("empty", [{}, {"foo": "bar"}, {"voice": {}}])
def test_empty_backup_is_not_reported_as_success(client, empty):
    before = client.get("/config").json()
    assert client.post("/config/import", json=empty).status_code == 422
    assert client.get("/config").json() == before


def test_export_excludes_voice_connection(client):
    """导出红线（§3/§8）：语音引擎绑定（connectionId）不进备份。"""
    client.put("/config/voice", json={"ttsEnabled": True, "volume": 0.6})
    data = client.get("/config/export").json()
    assert data["voice"]["volume"] == 0.6
    assert "connectionId" not in data["voice"]


def test_import_maps_legacy_voice_id(client):
    """旧 snake_case 备份里的 edge 音色 id 导入时映射为 CosyVoice。"""
    resp = client.post(
        "/config/import",
        json={"voice": {"tts_enabled": True, "voice_id": "zh-CN-YunxiNeural", "volume": 0.7}},
    )
    assert resp.status_code == 200
    assert client.get("/config/voice").json()["voiceId"] == "longanyang"


def test_import_ignores_unknown_voice_binding(client):
    """手改备份带本机不存在的 connectionId：忽略绑定，其余语音偏好照常导入。"""
    resp = client.post(
        "/config/import",
        json={"voice": {"tts_enabled": True, "connectionId": "ghost", "rate": 1.5}},
    )
    assert resp.status_code == 200
    voice = client.get("/config/voice").json()
    assert voice["rate"] == 1.5
    assert voice["connectionId"] is None
