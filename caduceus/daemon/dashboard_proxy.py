"""Pure helpers for the agent-dashboard reverse proxy (U11, FR-U11-3/4).

No I/O here — `control_api` wires these into the HTTP/WS routes. Kept pure so the
proxy's two safety properties are PBT-checkable (PBT-U11-1/2):

  * `upstream_url` can never escape the agent's loopback authority, whatever the
    incoming path/query looks like (BR-DB5).
  * `filter_headers` strips every RFC-7230 hop-by-hop header — the fixed set plus
    any tokens the `Connection` header nominates — in both directions (BR-DB7).
"""

from __future__ import annotations

from typing import Iterable

#: X-Forwarded-Prefix value for agent `name` (BR-DB6) — hermes' native sub-path
#: support rewrites SPA assets/cookies/redirects from it. Exactly this, no slash.
def prefix_for(name: str) -> str:
    return f"/agents/{name}/dashboard"


#: RFC 7230 §6.1 hop-by-hop headers (lowercase). `host` is dropped from requests
#: too — httpx/websockets set it for the upstream connection.
HOP_BY_HOP = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
})


def upstream_url(scheme: str, port: int, path: str, query: str = "") -> str:
    """Join `path` (+`query`) under the agent's dashboard authority.

    String concatenation on purpose — never `urljoin` — so the authority is pinned
    to `127.0.0.1:<port>` no matter what the path contains (`//evil`, `..`,
    encoded bytes, ...). The path is normalised to exactly one leading slash;
    everything after that is the upstream server's business (hermes does its own
    routing/404s).
    """
    p = "/" + path.lstrip("/")
    if query:
        p = f"{p}?{query}"
    return f"{scheme}://127.0.0.1:{port}{p}"


def rewrite_login_page(html: str, prefix: str) -> str:
    """Fix hermes' server-rendered login page under a path prefix (U11-L1).

    hermes 0.17.0 rewrites its SPA index for X-Forwarded-Prefix, but the login
    page's inline script still (a) POSTs to the absolute ``/auth/password-login``
    (which escapes the proxy → 404 → "sign-in failed") and (b) navigates to the
    unprefixed ``next`` on success. Both replacements are no-ops on any other
    document and naturally idempotent (the source patterns vanish once applied).
    """
    html = html.replace(
        "fetch('/auth/password-login'",
        f"fetch('{prefix}/auth/password-login'")
    html = html.replace(
        "window.location.assign((data && data.next) || '/');",
        "window.location.assign((function(n){n=n||'/';"
        f"return n.indexOf('{prefix}')===0?n:'{prefix}'+n;"
        "})((data && data.next) || '/'));")
    return html


def filter_headers(headers: Iterable[tuple[str, str]],
                   drop_host: bool = False) -> list[tuple[str, str]]:
    """Drop hop-by-hop headers (fixed set + `Connection`-nominated tokens).

    End-to-end headers (cookies included) pass through untouched, preserving
    order and duplicates. `drop_host=True` for the request direction.
    """
    items = [(k, v) for k, v in headers]
    named: set[str] = set()
    for k, v in items:
        if k.lower() == "connection":
            named.update(t.strip().lower() for t in v.split(",") if t.strip())
    out = []
    for k, v in items:
        lk = k.lower()
        if lk in HOP_BY_HOP or lk in named:
            continue
        if drop_host and lk == "host":
            continue
        out.append((k, v))
    return out
