"""U11 — dashboard proxy helpers + Control API dashboard routes.

Helper functions are pure (see also tests/pbt/test_u11_properties.py); the route
tests run the real app over ASGI with fake services. The 502 and passthrough
tests use real loopback sockets (a closed port / a canned HTTP responder), and
the WS-bridge test relays to a real in-process websockets echo server.
"""

from __future__ import annotations

import asyncio
import socket

import httpx

from caduceus.common.models import AgentKind
from caduceus.daemon.control_api import build_control_app
from caduceus.daemon.dashboard_proxy import HOP_BY_HOP, filter_headers, prefix_for, upstream_url

from tests.fakes import build_fake_services, make_agent


# ---------- pure helpers ----------

def test_upstream_url_pins_authority():
    assert upstream_url("http", 1234, "api/x", "a=1") == "http://127.0.0.1:1234/api/x?a=1"
    assert upstream_url("http", 1234, "") == "http://127.0.0.1:1234/"
    # `//evil.com/x` collapses into a path under the pinned authority
    assert upstream_url("http", 1234, "//evil.com/x") == "http://127.0.0.1:1234/evil.com/x"
    assert upstream_url("ws", 9, "/api/pty", "t=1") == "ws://127.0.0.1:9/api/pty?t=1"
    # dot segments are forwarded verbatim (upstream's business), authority intact
    assert upstream_url("http", 1234, "../../etc").startswith("http://127.0.0.1:1234/")


def test_filter_headers_drops_hop_by_hop_and_connection_named():
    out = filter_headers([
        ("Connection", "close, X-Custom-Hop"),
        ("X-Custom-Hop", "die"),
        ("Keep-Alive", "timeout=5"),
        ("Transfer-Encoding", "chunked"),
        ("Cookie", "s=1"),
        ("Content-Type", "text/html"),
    ])
    assert out == [("Cookie", "s=1"), ("Content-Type", "text/html")]


def test_filter_headers_drop_host_and_preserves_duplicates_in_order():
    out = filter_headers([
        ("Host", "ctl:9700"),
        ("Set-Cookie", "a=1"),
        ("Set-Cookie", "b=2"),
    ], drop_host=True)
    assert out == [("Set-Cookie", "a=1"), ("Set-Cookie", "b=2")]
    # without drop_host, Host passes (response direction never carries one anyway)
    assert ("Host", "h") in filter_headers([("Host", "h")])


def test_prefix_for():
    assert prefix_for("my-agent") == "/agents/my-agent/dashboard"
    assert not prefix_for("x").endswith("/")


def test_hop_by_hop_is_the_rfc_set():
    assert "te" in HOP_BY_HOP and "upgrade" in HOP_BY_HOP and "cookie" not in HOP_BY_HOP


# ---------- route harness ----------

def _dash_agent(name="d1", port=59991, password="pw-secret-xyz"):
    rec = make_agent(name=name)
    rec.dashboard_port = port
    rec.dashboard_password = password
    return rec


def _client(services):
    app = build_control_app(services)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://ctl")


async def test_credentials_route_shape():
    services = build_fake_services(agents=[_dash_agent()])
    async with _client(services) as c:
        body = (await c.get("/agents/d1/dashboard-credentials")).json()
    assert body == {"username": "d1", "password": "pw-secret-xyz",
                    "url": "/agents/d1/dashboard/"}


async def test_credentials_404_semantics():
    plain = make_agent(name="plain")               # local, no dashboard
    remote = make_agent(name="rem", kind=AgentKind.remote)
    remote.dashboard_port = 5999                   # even if set, remote → 404 (BR-DB16)
    services = build_fake_services(agents=[plain, remote])
    async with _client(services) as c:
        assert (await c.get("/agents/ghost/dashboard-credentials")).status_code == 404
        assert (await c.get("/agents/plain/dashboard-credentials")).status_code == 404
        assert (await c.get("/agents/rem/dashboard-credentials")).status_code == 404


async def test_dashboard_root_redirects_308_preserving_query():
    services = build_fake_services(agents=[_dash_agent()])
    async with _client(services) as c:
        r = await c.get("/agents/d1/dashboard", params={"x": "1"})
    assert r.status_code == 308
    assert r.headers["location"] == "/agents/d1/dashboard/?x=1"


async def test_proxy_404_for_unknown_and_dashboardless():
    services = build_fake_services(agents=[make_agent(name="plain")])
    async with _client(services) as c:
        assert (await c.get("/agents/ghost/dashboard/")).status_code == 404
        assert (await c.get("/agents/plain/dashboard/x")).status_code == 404


async def test_proxy_502_when_dashboard_unreachable():
    # A freshly-closed loopback port refuses connections immediately.
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        dead_port = s.getsockname()[1]
    services = build_fake_services(agents=[_dash_agent(port=dead_port)])
    async with _client(services) as c:
        r = await c.get("/agents/d1/dashboard/")
    assert r.status_code == 502
    assert "dashboard unreachable" in r.json()["error"]["message"]


async def test_proxy_passthrough_injects_prefix_and_filters_headers():
    """Real byte-level check: X-Forwarded-Prefix reaches the upstream, no Host of
    the proxy leaks, and duplicate Set-Cookie response headers survive (BR-DB6/7)."""
    seen = {}

    async def handle(reader, writer):
        raw = await reader.readuntil(b"\r\n\r\n")
        seen["head"] = raw.decode("latin-1")
        writer.write(b"HTTP/1.1 200 OK\r\n"
                     b"Content-Length: 2\r\n"
                     b"Set-Cookie: a=1\r\n"
                     b"Set-Cookie: b=2\r\n"
                     b"Content-Type: text/plain\r\n\r\nok")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        services = build_fake_services(agents=[_dash_agent(port=port)])
        async with _client(services) as c:
            r = await c.get("/agents/d1/dashboard/login?next=%2F", headers={"Cookie": "s=1"})
    finally:
        server.close()
        await server.wait_closed()

    assert r.status_code == 200 and r.text == "ok"
    head = seen["head"]
    assert "GET /login?next=%2F HTTP/1.1" in head          # prefix stripped, encoding kept
    assert "x-forwarded-prefix: /agents/d1/dashboard" in head.lower()
    assert "cookie: s=1" in head.lower()                    # end-to-end header forwarded
    assert r.headers.get_list("set-cookie") == ["a=1", "b=2"]  # duplicates preserved


async def test_ws_bridge_relays_frames_both_ways():
    from starlette.testclient import TestClient
    from websockets.asyncio.server import serve as ws_serve

    got = {}

    async def echo(ws):
        got["path"] = ws.request.path
        got["cookie"] = ws.request.headers.get("Cookie")
        async for frame in ws:
            await ws.send(frame)          # echo text and bytes alike

    async with ws_serve(echo, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        services = build_fake_services(agents=[_dash_agent(port=port)])
        app = build_control_app(services)

        def drive():
            client = TestClient(app)
            with client.websocket_connect("/agents/d1/dashboard/api/pty?tk=1",
                                          headers={"Cookie": "sess=abc"}) as ws:
                ws.send_text("ping")
                assert ws.receive_text() == "ping"
                ws.send_bytes(b"\x00\x01")
                assert ws.receive_bytes() == b"\x00\x01"

        # TestClient is sync (its own portal); keep this loop free while it runs.
        await asyncio.get_running_loop().run_in_executor(None, drive)

    assert got["path"] == "/api/pty?tk=1"
    assert got["cookie"] == "sess=abc"


async def test_ws_bridge_rejects_dashboardless_agent():
    from starlette.testclient import TestClient

    services = build_fake_services(agents=[make_agent(name="plain")])
    app = build_control_app(services)

    def drive():
        client = TestClient(app)
        try:
            with client.websocket_connect("/agents/plain/dashboard/api/pty"):
                return "accepted"
        except Exception:
            return "rejected"

    assert await asyncio.get_running_loop().run_in_executor(None, drive) == "rejected"


# ---------- view projection ----------

def test_agent_view_dashboard_flag_and_secrecy():
    from caduceus.common.dto import AgentView

    rec = _dash_agent()
    view = AgentView.from_record(rec)
    assert view.dashboard is True
    assert "pw-secret-xyz" not in str(view.to_dict())
    assert AgentView.from_record(make_agent(name="p")).dashboard is False


# ---------- U11-L1: login-page rewrite ----------

def test_rewrite_login_page_prefixes_fetch_and_next():
    from caduceus.daemon.dashboard_proxy import rewrite_login_page

    src = ("fetch('/auth/password-login', {\n"
           "window.location.assign((data && data.next) || '/');")
    out = rewrite_login_page(src, "/agents/a1/dashboard")
    assert "fetch('/agents/a1/dashboard/auth/password-login'" in out
    assert "'/agents/a1/dashboard'" in out and "indexOf" in out
    assert rewrite_login_page(out, "/agents/a1/dashboard") == out   # idempotent
    assert rewrite_login_page("<html>plain</html>", "/p") == "<html>plain</html>"


async def test_proxy_rewrites_html_login_page_live():
    """The proxied login page (text/html) gets the prefix patch; content-length
    is recomputed and non-HTML bodies stay untouched-streamed (U11-L1)."""
    page = (b"<html><script>fetch('/auth/password-login', {})\n"
            b"window.location.assign((data && data.next) || '/');</script></html>")

    async def handle(reader, writer):
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n"
                     b"Content-Length: " + str(len(page)).encode() + b"\r\n\r\n" + page)
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        services = build_fake_services(agents=[_dash_agent(port=port)])
        async with _client(services) as c:
            r = await c.get("/agents/d1/dashboard/login")
    finally:
        server.close()
        await server.wait_closed()

    assert r.status_code == 200
    assert "fetch('/agents/d1/dashboard/auth/password-login'" in r.text
    assert int(r.headers["content-length"]) == len(r.content)      # recomputed
