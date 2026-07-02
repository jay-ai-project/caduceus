"""Control API — loopback HTTP surface for the CLI (C4, FR-G3/G4).

Thin routes over the wired services (humble object): translate request → service
call → JSON/SSE. Errors map to JSON + status. `chat`/`logs` stream as SSE.
`agent ls` projects records to secret-free `AgentView`s.
"""

from __future__ import annotations

import asyncio
import json
import logging

import httpx
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse, RedirectResponse, Response, StreamingResponse
from starlette.background import BackgroundTask

from caduceus.common.dto import (
    AgentView,
    ConfigChange,
    CreateSpec,
    DashboardCredentials,
    GatewayConfigChange,
    RegisterSpec,
)
from caduceus.common.errors import ProxyError, invalid_request_error
from caduceus.common.models import AgentKind
from caduceus.config.editor import ReadOnlyError
from caduceus.daemon.dashboard_proxy import (
    filter_headers,
    prefix_for,
    rewrite_login_page,
    upstream_url,
)
from caduceus.webui import mount_webui

log = logging.getLogger("caduceus.control")

#: HTTP methods the dashboard proxy relays (BR-DB8 — everything the SPA uses).
_PROXY_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


def _sse(obj: dict) -> bytes:
    return f"data: {json.dumps(obj)}\n\n".encode()


def build_control_app(services, status_provider=None) -> FastAPI:
    app = FastAPI(title="caduceus Control API", docs_url=None, redoc_url=None)
    agents = services.agent_service
    chat = services.chat_service
    config = services.config_service
    registry = services.registry

    def _err(exc: Exception) -> JSONResponse:
        if isinstance(exc, ReadOnlyError):
            return JSONResponse({"error": {"message": str(exc), "type": "read_only"}}, status_code=409)
        if isinstance(exc, ProxyError):
            return JSONResponse(exc.to_openai(), status_code=exc.http_status)
        return JSONResponse({"error": {"message": str(exc), "type": "internal_error"}}, status_code=500)

    def _err_event(exc: Exception) -> dict:
        """Flatten an exception to an in-band SSE error payload (for streamed routes)."""
        body = _err(exc).body
        try:
            payload = json.loads(body)
            msg = payload.get("error", {}).get("message", str(exc))
        except (ValueError, TypeError, AttributeError):
            msg = str(exc)
        return {"message": msg}

    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    @app.get("/status")
    async def status():
        gs = await (status_provider or services.status_snapshot)()
        return gs.to_dict()

    @app.get("/api/events")
    async def events():
        # U9: single long-lived SSE stream powering the Web UI dashboard. Replaces the
        # old 3s poll of `/status` + `/agents?probe=false`: the client subscribes once,
        # receives a snapshot on connect, then a fresh snapshot on every state change
        # (registry mutation or supervisor health sweep). `: comment` lines are SSE
        # keepalives, ignored by the browser's EventSource.
        async def gen():
            async for snap in services.event_bus.subscribe():
                yield b": keepalive\n\n" if snap is None else _sse(snap)

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/agents")
    async def create(request: Request, wait: bool = False):
        # Default (wait=false, FR-U7-2): register the agent as `creating`, kick off
        # background provisioning, and return a single `accepted` event immediately —
        # `agent ls` then reflects the live creating→running→healthy progression.
        # wait=true: stream live provisioning progress as SSE → final done/error.
        try:
            spec = CreateSpec.from_dict(await request.json())
        except Exception as exc:  # noqa: BLE001 — malformed body → 400, not a 500
            return _err(invalid_request_error(f"invalid request body: {exc}"))

        if not wait:
            async def gen_bg():
                try:
                    rec = await agents.create(spec.name, wait=False, model=spec.model,
                                              image=spec.image, dashboard=spec.dashboard)
                    yield _sse({"event": "accepted", "agent": AgentView.from_record(rec).to_dict()})
                except Exception as exc:  # noqa: BLE001 — surface as an in-band error event
                    yield _sse({"event": "error", **_err_event(exc)})

            return StreamingResponse(gen_bg(), media_type="text/event-stream")

        q: "asyncio.Queue" = asyncio.Queue()

        async def progress(phase: str, detail: str = "") -> None:
            await q.put({"event": "progress", "phase": phase, "detail": detail})

        async def run():
            try:
                rec = await agents.create(spec.name, progress=progress, model=spec.model,
                                          image=spec.image, dashboard=spec.dashboard)
                await q.put({"event": "done", "agent": AgentView.from_record(rec).to_dict()})
            except Exception as exc:  # noqa: BLE001 — surface as an in-band error event
                await q.put({"event": "error", **_err_event(exc)})
            finally:
                await q.put(None)

        async def gen():
            task = asyncio.create_task(run())
            try:
                while True:
                    item = await q.get()
                    if item is None:
                        break
                    yield _sse(item)
            finally:
                await task

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.post("/agents/register")
    async def register(request: Request):
        try:
            spec = RegisterSpec.from_dict(await request.json())
            rec, guidance = await agents.register(spec.name, spec.endpoint, spec.auth)
            return {"agent": AgentView.from_record(rec).to_dict(), "guidance": guidance}
        except Exception as exc:  # noqa: BLE001
            return _err(exc)

    @app.get("/agents")
    async def list_agents(deep: bool = False):
        # Live listing for the CLI `agent ls` (one docker ps + per-agent /health probe).
        # The Web UI no longer calls this — it consumes /api/events, whose snapshot uses
        # the cheap probe-free registry projection directly (agent_service.list(probe=False)).
        try:
            recs = await agents.list(deep=deep, probe=True)
            return [AgentView.from_record(r, r.last_health).to_dict() for r in recs]
        except Exception as exc:  # noqa: BLE001
            return _err(exc)

    @app.delete("/agents/{name}")
    async def remove(name: str):
        try:
            await agents.remove(name)
            return Response(status_code=204)
        except Exception as exc:  # noqa: BLE001
            return _err(exc)

    @app.post("/agents/{name}/stop")
    async def stop(name: str):
        try:
            return AgentView.from_record(await agents.stop(name)).to_dict()
        except Exception as exc:  # noqa: BLE001
            return _err(exc)

    @app.post("/agents/{name}/start")
    async def start(name: str):
        try:
            return AgentView.from_record(await agents.start(name)).to_dict()
        except Exception as exc:  # noqa: BLE001
            return _err(exc)

    @app.post("/agents/{name}/chat")
    async def chat_stream(name: str, request: Request):
        raw = await request.body()
        message = _extract_message(raw)

        async def gen():
            async for ev in chat.chat_stream(name, message):
                yield _sse(ev.to_dict())

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.post("/agents/{name}/chat/cancel")
    async def chat_cancel(name: str):
        # U10/R10: cooperative cancel of the in-flight turn (Web UI Stop button).
        # The streaming /chat response ends with done{cancelled}; nothing to stop
        # → {"cancelled": false} (idempotent, still 200).
        if registry.get(name) is None:
            return _err(ProxyError(404, "invalid_request_error", f"no such agent '{name}'"))
        return {"cancelled": chat.cancel(name)}

    @app.get("/agents/{name}/history")
    async def history(name: str):
        # Best-effort prior-turn replay for the Web UI (FR-W10). Unknown agent →
        # error; any load failure is swallowed by ChatService → empty turns.
        if registry.get(name) is None:
            return _err(ProxyError(404, "invalid_request_error", f"no such agent '{name}'"))
        turns = await chat.history(name)
        return {"turns": [t.to_dict() for t in turns]}

    @app.get("/gateway/config")
    async def get_gateway_config():
        # Live effective upstream/model the running gateway is serving with (BR-GC5/GC8).
        return services.gateway_config_service.view().to_dict()

    @app.post("/gateway/config")
    async def set_gateway_config(request: Request):
        try:
            change = GatewayConfigChange.from_dict(await request.json())
            return services.gateway_config_service.apply(change).to_dict()
        except ValueError as exc:  # validation (BR-GC2/GC3) → usage error
            return JSONResponse(
                {"error": {"message": str(exc), "type": "invalid_request_error"}}, status_code=400)
        except Exception as exc:  # noqa: BLE001
            return _err(exc)

    @app.get("/agents/{name}/config")
    async def get_config(name: str):
        try:
            return (await config.get_config(name)).to_dict()
        except Exception as exc:  # noqa: BLE001
            return _err(exc)

    @app.put("/agents/{name}/config")
    async def set_config(name: str, request: Request):
        try:
            change = ConfigChange.from_dict(await request.json())
            return (await config.set_config(name, change)).to_dict()
        except Exception as exc:  # noqa: BLE001
            return _err(exc)

    @app.get("/agents/{name}/logs")
    async def logs(name: str, follow: bool = False):
        rec = registry.get(name)
        if rec is None:
            return _err(ProxyError(404, "invalid_request_error", f"no such agent '{name}'"))
        if rec.kind == AgentKind.remote or not rec.container_name:
            return _err(ReadOnlyError("logs are available for local agents only"))

        async def gen():
            async for line in services.provisioner.logs(rec.container_name, follow=follow):
                yield _sse({"line": line})

        return StreamingResponse(gen(), media_type="text/event-stream")

    # ---- agent dashboard routing (U11) ----------------------------------
    # Same-origin reverse proxy onto the agent's in-container `hermes dashboard`.
    # Auth is the dashboard's own login gate; the exposure boundary is this API's
    # 127.0.0.1 bind (BR-DB10). Streaming client shared for the daemon's lifetime.
    proxy_client = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=None, write=None, pool=None))
    app.router.add_event_handler("shutdown", proxy_client.aclose)

    def _dashboard_rec(name: str):
        """Resolve a proxyable record or the 404 to answer with (BR-DB5/DB16)."""
        rec = registry.get(name)
        if rec is None:
            return None, ProxyError(404, "invalid_request_error", f"no such agent '{name}'")
        if rec.kind == AgentKind.remote or not rec.dashboard_port:
            return None, ProxyError(404, "invalid_request_error",
                                    f"agent '{name}' has no dashboard")
        return rec, None

    @app.get("/agents/{name}/dashboard-credentials")
    async def dashboard_credentials(name: str):
        rec, err = _dashboard_rec(name)
        if err is not None or not rec.dashboard_password:
            return _err(err or ProxyError(404, "invalid_request_error",
                                          f"agent '{name}' has no dashboard"))
        return DashboardCredentials(
            username=rec.name, password=rec.dashboard_password,
            url=f"{prefix_for(name)}/").to_dict()

    @app.api_route("/agents/{name}/dashboard", methods=_PROXY_METHODS)
    async def dashboard_root(name: str, request: Request):
        # BR-DB9: the SPA needs the trailing slash so relative URLs resolve under
        # the prefix. 308 preserves the method.
        rec, err = _dashboard_rec(name)
        if err is not None:
            return _err(err)
        url = f"{prefix_for(name)}/"
        if request.url.query:
            url = f"{url}?{request.url.query}"
        return RedirectResponse(url, status_code=308)

    @app.api_route("/agents/{name}/dashboard/{path:path}", methods=_PROXY_METHODS)
    async def dashboard_proxy(name: str, path: str, request: Request):
        rec, err = _dashboard_rec(name)
        if err is not None:
            return _err(err)
        # Use the raw (still percent-encoded) path so encoded bytes survive the
        # round trip; agent names are [a-z0-9-] so the prefix strip is exact.
        raw = request.scope.get("raw_path", request.url.path.encode()).decode("latin-1")
        prefix = prefix_for(name)
        tail = raw[len(prefix):] if raw.startswith(prefix) else path
        target = upstream_url("http", rec.dashboard_port, tail,
                              request.scope.get("query_string", b"").decode("latin-1"))
        headers = [(k, v) for k, v in filter_headers(request.headers.items(), drop_host=True)
                   if k.lower() != "accept-encoding"]
        # Identity encoding keeps HTML rewritable (U11-L1) — loopback, so no
        # compression is lost that matters.
        headers.append(("Accept-Encoding", "identity"))
        headers.append(("X-Forwarded-Prefix", prefix))  # BR-DB6
        upstream_req = proxy_client.build_request(
            request.method, target, headers=headers, content=request.stream())
        try:
            upstream = await proxy_client.send(upstream_req, stream=True)
        except httpx.HTTPError as exc:
            return _err(ProxyError(502, "upstream_error",
                                   f"dashboard unreachable: {type(exc).__name__}: {exc}"))
        # Upstream headers minus hop-by-hop, verbatim — raw_headers keeps
        # duplicates (multiple Set-Cookie) that a dict would collapse (BR-DB7).
        raw_pairs = filter_headers([(k.decode("latin-1"), v.decode("latin-1"))
                                    for k, v in upstream.headers.raw])

        if "text/html" in upstream.headers.get("content-type", ""):
            # HTML documents are small — buffer and patch hermes' login page,
            # whose inline script escapes the prefix (U11-L1). No-op elsewhere.
            try:
                body = rewrite_login_page(
                    (await upstream.aread()).decode("utf-8", "replace"), prefix
                ).encode("utf-8")
            finally:
                await upstream.aclose()
            response = Response(content=body, status_code=upstream.status_code)
            response.raw_headers = (
                [(k.encode("latin-1"), v.encode("latin-1")) for k, v in raw_pairs
                 if k.lower() != "content-length"]
                + [(b"content-length", str(len(body)).encode())])
            return response

        response = StreamingResponse(
            upstream.aiter_raw(), status_code=upstream.status_code,
            background=BackgroundTask(upstream.aclose))
        response.raw_headers = [(k.encode("latin-1"), v.encode("latin-1"))
                                for k, v in raw_pairs]
        return response

    @app.websocket("/agents/{name}/dashboard/{path:path}")
    async def dashboard_ws(name: str, path: str, websocket: WebSocket):
        # BR-DB11/12: bidirectional frame relay for the dashboard's embedded
        # chat/terminal (/api/pty, /api/ws). Faults stay local to this connection.
        rec, err = _dashboard_rec(name)
        if err is not None:
            await websocket.close(code=4404)
            return

        from websockets.asyncio.client import connect as ws_connect

        query = websocket.scope.get("query_string", b"").decode("latin-1")
        target = upstream_url("ws", rec.dashboard_port, path, query)
        fwd_headers = [(k, v) for k, v in websocket.headers.items()
                       if k.lower() in ("cookie", "authorization")]
        offered = websocket.scope.get("subprotocols") or None
        try:
            upstream = await ws_connect(target, additional_headers=fwd_headers,
                                        subprotocols=offered, open_timeout=5.0)
        except Exception as exc:  # noqa: BLE001 — connect failure → this socket only
            log.warning("dashboard ws connect for %s failed: %s", name, exc)
            await websocket.close(code=1014)  # bad gateway
            return

        await websocket.accept(subprotocol=upstream.subprotocol)

        async def client_to_upstream():
            while True:
                msg = await websocket.receive()
                if msg["type"] == "websocket.disconnect":
                    return
                if msg.get("text") is not None:
                    await upstream.send(msg["text"])
                elif msg.get("bytes") is not None:
                    await upstream.send(msg["bytes"])

        async def upstream_to_client():
            async for frame in upstream:
                if isinstance(frame, str):
                    await websocket.send_text(frame)
                else:
                    await websocket.send_bytes(frame)

        pumps = [asyncio.create_task(client_to_upstream()),
                 asyncio.create_task(upstream_to_client())]
        try:
            await asyncio.wait(pumps, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for t in pumps:
                t.cancel()
            await asyncio.gather(*pumps, return_exceptions=True)
            await upstream.close()
            try:
                await websocket.close()
            except RuntimeError:
                pass  # already closed by the client side

    mount_webui(app)  # FR-W1: serve the static SPA at /ui (+ `/` redirect)
    return app


def _extract_message(raw: bytes) -> str:
    if not raw:
        return ""
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return str(obj.get("message", ""))
        if isinstance(obj, str):
            return obj
    except (ValueError, TypeError):
        pass
    return raw.decode("utf-8", "replace")
