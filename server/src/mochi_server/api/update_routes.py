"""公开发布版本检测；只请求 Mochi 的 GitHub 最新发布跳转，不使用匿名 REST 配额。"""

from __future__ import annotations

import asyncio
import re
import time
from urllib.parse import urljoin, urlsplit
from urllib.request import getproxies

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from ..events import CamelModel
from .security import localhost_only

RELEASES_URL = "https://github.com/liyu-1028/mochi/releases"
_TAG = re.compile(r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")
router = APIRouter(prefix="/updates", tags=["updates"], dependencies=[Depends(localhost_only)])


class ReleaseInfo(CamelModel):
    version: str
    url: str


class ReleaseChecker:
    """每个应用进程共享一小时缓存和在途锁，失败不伪装为最新版本。"""

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport
        self._checked_at: float | None = None
        self._release: ReleaseInfo | None = None
        self._lock = asyncio.Lock()

    async def latest(self, *, force: bool = False) -> ReleaseInfo | None:
        async with self._lock:
            if (
                not force
                and self._checked_at is not None
                and time.monotonic() - self._checked_at < 3600
            ):
                return self._release
            # Respect the user's existing OS/environment proxy. Local API requests never use it.
            proxy = None if self._transport else getproxies().get("https")
            async with httpx.AsyncClient(
                timeout=5.0,
                follow_redirects=False,
                proxy=proxy,
                transport=self._transport,
                trust_env=self._transport is None,
            ) as client:
                response = await client.get(f"{RELEASES_URL}/latest")
            if response.status_code == 404:
                release = None
            elif response.status_code in (301, 302, 303, 307, 308):
                url = urljoin(f"{RELEASES_URL}/latest", response.headers.get("location", ""))
                parsed = urlsplit(url)
                prefix = "/liyu-1028/mochi/releases/tag/"
                tag = parsed.path.removeprefix(prefix)
                if (
                    parsed.scheme != "https"
                    or parsed.netloc != "github.com"
                    or not parsed.path.startswith(prefix)
                    or not _TAG.fullmatch(tag)
                    or parsed.query
                    or parsed.fragment
                ):
                    raise ValueError("Invalid release redirect")
                release = ReleaseInfo(version=tag.removeprefix("v"), url=url)
            else:
                raise ValueError(f"GitHub HTTP {response.status_code}")
            self._release = release
            self._checked_at = time.monotonic()
            return release


@router.get("/latest")
async def latest_release(request: Request, force: bool = False) -> ReleaseInfo | None:
    checker: ReleaseChecker = request.app.state.release_checker
    try:
        return await checker.latest(force=force)
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="暂时无法连接 GitHub 检查更新") from exc
