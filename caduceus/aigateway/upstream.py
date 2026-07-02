"""UpstreamClient — async HTTP client to the real LLM upstream (httpx).

Streaming pass-through with explicit timeouts (R-1) and a shared keep-alive pool.
"""

from __future__ import annotations

import httpx

from caduceus.common.settings import Settings


class UpstreamClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self._settings = settings
        t = settings.timeouts
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(connect=t.connect, read=t.read, write=t.read, pool=t.connect)
        )

    def _url(self, subpath: str) -> str:
        return self._settings.upstream_base_url.rstrip("/") + "/" + subpath.lstrip("/")

    def stream(self, method: str, subpath: str, *, headers: dict, content: bytes | None):
        """Return an httpx streaming context manager (caller uses `async with`)."""
        return self._client.stream(method, self._url(subpath), headers=headers, content=content)

    async def request(self, method: str, subpath: str, *, headers: dict, content: bytes | None) -> httpx.Response:
        return await self._client.request(method, self._url(subpath), headers=headers, content=content)

    async def aclose(self) -> None:
        await self._client.aclose()
