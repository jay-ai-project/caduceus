"""PURE error mapping (BR-7): exceptions -> ProxyError (OpenAI error shape)."""

from __future__ import annotations

import httpx

from caduceus.common.errors import ProxyError, timeout_error, upstream_error


def map_error(exc: Exception) -> ProxyError:
    """Map any forwarding exception to a normalized ProxyError.

    Total function: always returns a ProxyError with a valid http_status.
    """
    if isinstance(exc, ProxyError):
        return exc
    if isinstance(exc, httpx.TimeoutException):
        return timeout_error()
    if isinstance(exc, httpx.HTTPError):
        # connect errors, protocol errors, etc.
        return upstream_error(f"Upstream request failed: {type(exc).__name__}")
    return upstream_error(f"Unexpected proxy error: {type(exc).__name__}", status=500)
