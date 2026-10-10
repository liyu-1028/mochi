import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from mochi_server.api.update_routes import RELEASES_URL, ReleaseChecker
from mochi_server.config import AppConfig
from mochi_server.main import create_app


@pytest.mark.asyncio
async def test_checks_official_latest_without_following_redirect_or_sending_secrets():
    seen = []

    def handle(request):
        seen.append(request)
        assert str(request.url) == RELEASES_URL + "/latest"
        assert "authorization" not in request.headers
        return httpx.Response(302, headers={"location": RELEASES_URL + "/tag/v0.16.0"})

    checker = ReleaseChecker(httpx.MockTransport(handle))
    results = await asyncio.gather(checker.latest(), checker.latest())
    assert results[0].version == "0.16.0"
    assert results[0].url == RELEASES_URL + "/tag/v0.16.0"
    assert len(seen) == 1
    await checker.latest(force=True)
    assert len(seen) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "https://malicious.example/tag/v0.16.0",
        RELEASES_URL + "/tag/v0.16.0-rc.1",
        "https://github.com/other/repo/releases/tag/v0.16.0",
        RELEASES_URL + "/tag/v0.16.0?extra=1",
        RELEASES_URL + "/tag/not-a-version",
    ],
)
async def test_rejects_invalid_release_redirects(url):
    checker = ReleaseChecker(
        httpx.MockTransport(lambda r: httpx.Response(302, headers={"location": url}))
    )
    with pytest.raises(ValueError):
        await checker.latest()


@pytest.mark.asyncio
async def test_absent_release_is_cached():
    handler = []

    def handle(request):
        handler.append(request)
        return httpx.Response(404)

    checker = ReleaseChecker(httpx.MockTransport(handle))
    assert await checker.latest() is None
    assert await checker.latest() is None
    assert len(handler) == 1


def test_network_failure_can_be_retried_without_poisoning_cache():
    calls = []

    def handle(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ReadTimeout("timeout")
        return httpx.Response(302, headers={"location": RELEASES_URL + "/tag/v0.15.0"})

    with TestClient(create_app(config=AppConfig())) as client:
        client.app.state.release_checker = ReleaseChecker(httpx.MockTransport(handle))
        assert client.get("/updates/latest").status_code == 503
        response = client.get("/updates/latest")
        assert response.status_code == 200
        assert response.json()["version"] == "0.15.0"


def test_updates_are_localhost_only():
    with TestClient(create_app(config=AppConfig())) as client:
        assert (
            client.get("/updates/latest", headers={"Host": "untrusted.example"}).status_code == 403
        )
