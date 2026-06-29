"""PURE header sanitation (BR-4 token strip, BR-10 hop-by-hop strip).

The agent's bearer token MUST NOT be forwarded upstream. Upstream credentials,
if configured, are attached instead.
"""

from __future__ import annotations

from collections.abc import Mapping

# Hop-by-hop headers (RFC 7230) + length/host that httpx will recompute.
_HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "host",
        "content-length",
        "authorization",  # agent token — always stripped
    }
)


def sanitize_headers(headers: Mapping[str, str], upstream_auth: str | None = None) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in headers.items():
        if key.lower() in _HOP_BY_HOP:
            continue
        out[key] = value
    if upstream_auth:
        out["Authorization"] = f"Bearer {upstream_auth}"
    return out
