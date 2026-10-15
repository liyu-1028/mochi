"""ASR 路由测试（fake websockets，禁联网）。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
import websockets
from fastapi.testclient import TestClient

from mochi_server.config import AppConfig, ModelConnectionConfig
from mochi_server.main import create_app


@pytest.fixture
def client():
    with TestClient(create_app(config=AppConfig())) as c:
        yield c


def _bind_connection(client: TestClient) -> None:
    registry = client.app.state.registry
    registry.key_store.set_key("bailian-voice", "sk-test")
    config = registry.config.model_copy(deep=True)
    config.model.connections["bailian-voice"] = ModelConnectionConfig(
        preset_id="dashscope", display_name="百炼（语音）", endpoints={}
    )
    config.voice.connection_id = "bailian-voice"
    registry.update_config(config)


def _event(name: str, **payload) -> str:
    return json.dumps({"header": {"event": name}, "payload": payload})


def _sentence(text: str, *, end: bool) -> str:
    return _event("result-generated", output={"sentence": {"text": text, "sentence_end": end}})


class _FakeWS:
    """按序回放服务端帧，记录客户端发送（文本/二进制）。"""

    def __init__(self, incoming: list[str]):
        self._incoming = list(incoming)
        self.sent: list[bytes | str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def send(self, data):
        self.sent.append(data)

    async def recv(self):
        if not self._incoming:
            raise AssertionError("服务端帧耗尽（缺少 task-finished）")
        return self._incoming.pop(0)


def _patch_ws(
    monkeypatch, incoming: list[str] | None = None, connect_error: Exception | None = None
):
    """patch asr_routes.websockets（模块级名字；SimpleNamespace 不污染真实库）。"""
    from mochi_server.api import asr_routes

    frames: list[_FakeWS] = []

    class _Connect:
        def __call__(self, *args, **kwargs):
            if connect_error:
                raise connect_error
            return self

        async def __aenter__(self):
            ws = _FakeWS(incoming or [])
            frames.append(ws)
            return ws

        async def __aexit__(self, *exc):
            return False

    fake = SimpleNamespace(connect=_Connect(), WebSocketException=websockets.WebSocketException)
    monkeypatch.setattr(asr_routes, "websockets", fake)
    return frames


def test_transcribe_unconfigured_409(client):
    resp = client.post("/asr/transcribe", files={"file": ("s.wav", b"RIFF", "audio/wav")})
    assert resp.status_code == 409
    assert "设置 → 语音" in resp.json()["detail"]


def test_transcribe_privacy_local_only_409(client):
    registry = client.app.state.registry
    config = registry.config.model_copy(deep=True)
    config.privacy.local_only = True
    registry.update_config(config)
    resp = client.post("/asr/transcribe", files={"file": ("s.wav", b"RIFF", "audio/wav")})
    assert resp.status_code == 409
    assert "隐私模式" in resp.json()["detail"]


def test_transcribe_oversize_413(client):
    _bind_connection(client)
    resp = client.post(
        "/asr/transcribe",
        files={"file": ("s.wav", b"x" * (20 * 1024 * 1024 + 1), "audio/wav")},
    )
    assert resp.status_code == 413


def test_transcribe_empty_422(client):
    _bind_connection(client)
    resp = client.post("/asr/transcribe", files={"file": ("s.wav", b"", "audio/wav")})
    assert resp.status_code == 422


def test_transcribe_success(client, monkeypatch):
    """中间结果同句演进覆盖、sentence_end 定稿、收尾 pending 补齐。"""
    _bind_connection(client)
    frames = _patch_ws(
        monkeypatch,
        incoming=[
            _event("task-started"),
            _sentence("你", end=False),
            _sentence("你好", end=False),  # 同句演进：覆盖不拼接
            _sentence("你好。", end=True),
            _sentence("世界", end=False),  # finish 前最后一句未定稿
            _event("task-finished"),
        ],
    )
    audio = b"x" * 40_000  # 跨两个 16KB 分帧
    resp = client.post("/asr/transcribe", files={"file": ("speech.wav", audio, "audio/wav")})
    assert resp.status_code == 200
    assert resp.json() == {"text": "你好。世界"}

    ws = frames[0]
    run_task = json.loads(ws.sent[0])
    assert run_task["payload"]["model"] == "paraformer-realtime-v2"
    assert run_task["payload"]["parameters"]["format"] == "wav"
    assert run_task["header"]["action"] == "run-task"
    assert json.loads(ws.sent[-1])["header"]["action"] == "finish-task"
    binary = [s for s in ws.sent[1:-1] if isinstance(s, (bytes, bytearray))]
    assert b"".join(binary) == audio  # 分帧无损
    assert len(binary) == 3  # 40000 = 16384 + 16384 + 7232


def test_transcribe_cloud_fail_502(client, monkeypatch):
    _bind_connection(client)
    _patch_ws(monkeypatch, incoming=[_event("task-failed")])
    resp = client.post("/asr/transcribe", files={"file": ("s.wav", b"RIFF", "audio/wav")})
    assert resp.status_code == 502
    assert "语音识别失败" in resp.json()["detail"]


def test_transcribe_connect_fail_502(client, monkeypatch):
    _bind_connection(client)
    _patch_ws(monkeypatch, connect_error=websockets.WebSocketException("refused"))
    resp = client.post("/asr/transcribe", files={"file": ("s.wav", b"RIFF", "audio/wav")})
    assert resp.status_code == 502
    assert "无法连接" in resp.json()["detail"]


def test_transcribe_empty_text_returns_200_blank(client, monkeypatch):
    """空识别结果（极短按/没说话）返回 200 空文本，前端按「没听清」提示。"""
    _bind_connection(client)
    _patch_ws(monkeypatch, incoming=[_event("task-started"), _event("task-finished")])
    resp = client.post("/asr/transcribe", files={"file": ("s.wav", b"RIFF", "audio/wav")})
    assert resp.status_code == 200
    assert resp.json() == {"text": ""}
