"""StreamPump — bridge an upstream SSE stream to the client (BR-5).

- forwards chunks immediately (no buffering)
- on client disconnect, the async generator is closed -> the `async with`
  exits -> the upstream request is cancelled (no orphan calls)
- on a mid-stream upstream error, emits one OpenAI-style error SSE event
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from caduceus.aigateway.errors_map import map_error
from caduceus.common.errors import ProxyError


def sse_error_event(err: ProxyError) -> bytes:
    return f"data: {json.dumps(err.to_openai())}\n\n".encode()


async def pump_stream(upstream_cm) -> AsyncIterator[bytes]:
    """`upstream_cm` is the httpx streaming context manager from UpstreamClient.stream()."""
    try:
        async with upstream_cm as resp:
            if resp.status_code >= 400:
                body = await resp.aread()
                detail = body.decode("utf-8", "replace")[:500] or f"upstream status {resp.status_code}"
                yield sse_error_event(ProxyError(resp.status_code, "upstream_error", detail))
                return
            async for chunk in resp.aiter_raw():
                yield chunk
    except Exception as exc:  # connection dropped mid-stream, timeout, etc.
        yield sse_error_event(map_error(exc))
