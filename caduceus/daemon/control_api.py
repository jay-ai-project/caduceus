"""Control API — loopback HTTP surface for the CLI (C4, FR-G3/G4).

Thin routes over the wired services (humble object): translate request → service
call → JSON/SSE. Errors map to JSON + status. `chat`/`logs` stream as SSE.
`agent ls` projects records to secret-free `AgentView`s.
"""

from __future__ import annotations

import asyncio
import json
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from caduceus.common.dto import (
    AgentView,
    ConfigChange,
    CreateSpec,
    GatewayConfigChange,
    GatewayStatus,
    RegisterSpec,
)
from caduceus.common.errors import ProxyError
from caduceus.common.models import AgentKind
from caduceus.config.editor import ReadOnlyError
from caduceus.webui import mount_webui

VERSION = "0.1.0"


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
        if status_provider is not None:
            gs = await status_provider()
        else:
            gs = GatewayStatus(
                running=True, control_listener=services.settings.control_bind,
                aigateway_listener=services.settings.aigateway_bind,
                agent_count=len(registry.list()), version=VERSION,
            )
        return gs.to_dict()

    @app.post("/agents")
    async def create(request: Request, wait: bool = False):
        # Default (wait=false, FR-U7-2): register the agent as `creating`, kick off
        # background provisioning, and return a single `accepted` event immediately —
        # `agent ls` then reflects the live creating→running→healthy progression.
        # wait=true: stream live provisioning progress as SSE → final done/error.
        spec = CreateSpec.from_dict(await request.json())

        if not wait:
            async def gen_bg():
                try:
                    rec = await agents.create(spec.name, wait=False)
                    yield _sse({"event": "accepted", "agent": AgentView.from_record(rec).to_dict()})
                except Exception as exc:  # noqa: BLE001 — surface as an in-band error event
                    yield _sse({"event": "error", **_err_event(exc)})

            return StreamingResponse(gen_bg(), media_type="text/event-stream")

        q: "asyncio.Queue" = asyncio.Queue()

        async def progress(phase: str, detail: str = "") -> None:
            await q.put({"event": "progress", "phase": phase, "detail": detail})

        async def run():
            try:
                rec = await agents.create(spec.name, progress=progress)
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
    async def list_agents(deep: bool = False, probe: bool = True):
        # `probe=false` → cheap listing (cached health) for the Web UI dashboard poll.
        try:
            recs = await agents.list(deep=deep, probe=probe)
            return [AgentView.from_record(r, r.last_health).to_dict() for r in recs]
        except Exception as exc:  # noqa: BLE001
            return _err(exc)

    @app.delete("/agents/{name}")
    async def remove(name: str, force: bool = False):
        try:
            await agents.remove(name, force=force)
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
        if rec.kind == AgentKind.remote or not rec.sandbox_name:
            return _err(ReadOnlyError("logs are available for local agents only"))

        async def gen():
            async for line in services.provisioner.logs(rec.sandbox_name, follow=follow):
                yield _sse({"line": line})

        return StreamingResponse(gen(), media_type="text/event-stream")

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
