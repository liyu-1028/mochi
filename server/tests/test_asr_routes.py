"""ASR 路由测试（fake websockets，禁联网）。"""

from __future__ import annotations

import asyncio
import json
import urllib.request
from types import SimpleNamespace

import pytest
import websockets
from fastapi.testclient import TestClient

from mochi_server.config import AppConfig, ModelConnectionConfig
from mochi_server.main import create_app
from mochi_server.tts.cosyvoice_engine import SpeechConnection


@pytest.fixture(autouse=True)
def isolated_proxies(monkeypatch):
    monkeypatch.setattr(urllib.request, "getproxies", lambda: {})
    monkeypatch.setattr(urllib.request, "proxy_bypass", lambda host: False)


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
    monkeypatch,
    incoming: list[str] | None = None,
    connect_error: Exception | None = None,
    expected_proxy: str | bool | None = True,
):
    """patch asr_routes.websockets（模块级名字；SimpleNamespace 不污染真实库）。"""
    from mochi_server.api import asr_routes

    frames: list[_FakeWS] = []

    class _Connect:
        def __call__(self, *args, **kwargs):
            # 官方 Paraformer WebSocket 协议；不能用普通 HTTP ASR 路径。
            assert args == ("wss://dashscope.aliyuncs.com/api-ws/v1/inference",)
            assert kwargs == {
                "additional_headers": {"Authorization": "Bearer sk-test"},
                "proxy": expected_proxy,
            }
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
    assert run_task["payload"]["parameters"]["sample_rate"] == 16000
    assert run_task["header"]["action"] == "run-task"
    # https://help.aliyun.com/zh/model-studio/paraformer-client-events
    assert run_task["header"]["streaming"] == "duplex"
    finish_task = json.loads(ws.sent[-1])
    assert finish_task["header"]["action"] == "finish-task"
    assert finish_task["header"]["streaming"] == "duplex"
    assert finish_task["header"]["task_id"] == run_task["header"]["task_id"]
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


def test_transcribe_unsupported_proxy_reports_readable_502(client, monkeypatch):
    _bind_connection(client)
    _patch_ws(
        monkeypatch, connect_error=ImportError("python-socks is required to use a SOCKS proxy")
    )
    resp = client.post("/asr/transcribe", files={"file": ("s.wav", b"RIFF", "audio/wav")})
    assert resp.status_code == 502
    assert "请启用 HTTP/HTTPS 代理" in resp.json()["detail"]
    assert "python-socks" not in resp.json()["detail"]


@pytest.mark.parametrize("bypass", [False, True])
def test_transcribe_respects_websocket_proxy_and_bypass(client, monkeypatch, bypass):
    _bind_connection(client)
    monkeypatch.setattr(
        urllib.request,
        "getproxies",
        lambda: {"wss": "http://ws-proxy.test:8080", "https": "http://https-proxy.test:8080"},
    )
    monkeypatch.setattr(urllib.request, "proxy_bypass", lambda host: bypass)
    _patch_ws(
        monkeypatch,
        incoming=[_event("task-started"), _event("task-finished")],
        expected_proxy=None if bypass else "http://ws-proxy.test:8080",
    )
    resp = client.post("/asr/transcribe", files={"file": ("s.wav", b"RIFF", "audio/wav")})
    assert resp.status_code == 200


def test_transcribe_empty_text_returns_200_blank(client, monkeypatch):
    """空识别结果（极短按/没说话）返回 200 空文本，前端按「没听清」提示。"""
    _bind_connection(client)
    _patch_ws(monkeypatch, incoming=[_event("task-started"), _event("task-finished")])
    resp = client.post("/asr/transcribe", files={"file": ("s.wav", b"RIFF", "audio/wav")})
    assert resp.status_code == 200
    assert resp.json() == {"text": ""}


@pytest.mark.asyncio
async def test_transcribe_uses_http_proxy_when_system_also_has_socks(monkeypatch):
    """真实 WebSocket + HTTP CONNECT：系统双代理不能触发未安装的 SOCKS 扩展。"""
    from websockets.asyncio import client as ws_client
    from websockets.asyncio.server import serve

    from mochi_server.api import asr_routes

    async def missing_socks(*args, **kwargs):
        raise ImportError("python-socks is required to use a SOCKS proxy")

    monkeypatch.setattr(ws_client, "connect_socks_proxy", missing_socks)
    monkeypatch.setattr(urllib.request, "proxy_bypass", lambda host: False)
    requests = []

    async def recognize(ws):
        assert ws.request.headers["Authorization"] == "Bearer sk-test"
        run = json.loads(await ws.recv())
        assert run["header"]["action"] == "run-task"
        await ws.send(_event("task-started"))
        assert await ws.recv() == b"recorded audio"
        finish = json.loads(await ws.recv())
        assert finish["header"]["action"] == "finish-task"
        await ws.send(_sentence("语音输入测试。", end=True))
        await ws.send(_event("task-finished"))

    async with serve(recognize, "127.0.0.1", 0) as cloud:
        cloud_port = cloud.sockets[0].getsockname()[1]

        async def forward(reader, writer):
            try:
                while data := await reader.read(65536):
                    writer.write(data)
                    await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        async def tunnel(reader, writer):
            headers = await reader.readuntil(b"\r\n\r\n")
            requests.append(headers.split(b"\r\n", 1)[0])
            upstream_reader, upstream_writer = await asyncio.open_connection(
                "127.0.0.1", cloud_port
            )
            writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
            await writer.drain()
            await asyncio.gather(forward(reader, upstream_writer), forward(upstream_reader, writer))

        async with await asyncio.start_server(tunnel, "127.0.0.1", 0) as proxy:
            proxy_port = proxy.sockets[0].getsockname()[1]
            monkeypatch.setattr(
                urllib.request,
                "getproxies",
                lambda: {"socks": "http://127.0.0.1:1", "https": f"http://127.0.0.1:{proxy_port}"},
            )
            monkeypatch.setattr(asr_routes, "ASR_WS_URL", "ws://speech.example.test/recognition")
            text = await asyncio.wait_for(
                asr_routes.transcribe(
                    b"recorded audio",
                    conn=SpeechConnection(connection_id="bailian-voice", api_key="sk-test"),
                ),
                timeout=5,
            )
    assert text == "语音输入测试。"
    assert requests == [b"CONNECT speech.example.test:80 HTTP/1.1"]
