"""AI-Gateway FastAPI app (OpenAI-compatible).

`build_aigateway_app(settings, token_lookup, upstream)` returns a FastAPI app
exposing `/v1/chat/completions` (stream + unary), `/v1/models`, and a generic
`/v1/{path}` pass-through. The daemon (U4) wires the real token_lookup + upstream.
"""

from __future__ import annotations

import json

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from caduceus.aigateway.auth import TokenLookup, authenticate
from caduceus.aigateway.errors_map import map_error
from caduceus.aigateway.headers import sanitize_headers
from caduceus.aigateway.models_augment import augment_models
from caduceus.aigateway.routing import build_route
from caduceus.aigateway.stream import pump_stream
from caduceus.aigateway.upstream import UpstreamClient
from caduceus.common.errors import ProxyError
from caduceus.common.settings import Settings


def _json_or_empty(raw: bytes) -> dict:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}


def build_aigateway_app(
    settings: Settings, token_lookup: TokenLookup, upstream: UpstreamClient
) -> FastAPI:
    app = FastAPI(title="caduceus AI-Gateway", docs_url=None, redoc_url=None)

    def _authenticate(request: Request) -> str:
        return authenticate(request.headers.get("authorization"), token_lookup)

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request):
        try:
            agent_id = _authenticate(request)
        except ProxyError as err:
            return JSONResponse(err.to_openai(), status_code=err.http_status)

        raw = await request.body()
        body = _json_or_empty(raw)
        stream = bool(body.get("stream"))
        route = build_route(body.get("model"), settings, agent_id)
        if route.rewrite_model:
            body["model"] = route.effective_model
            raw = json.dumps(body).encode()

        headers = sanitize_headers(dict(request.headers), settings.upstream_auth)
        headers["content-type"] = "application/json"

        if stream:
            cm = upstream.stream("POST", "chat/completions", headers=headers, content=raw)
            return StreamingResponse(pump_stream(cm), media_type="text/event-stream")

        try:
            resp = await upstream.request("POST", "chat/completions", headers=headers, content=raw)
        except Exception as exc:  # noqa: BLE001 — normalize all to OpenAI error
            err = map_error(exc)
            return JSONResponse(err.to_openai(), status_code=err.http_status)
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            media_type=resp.headers.get("content-type", "application/json"),
        )

    @app.get("/v1/models")
    async def models(request: Request):
        try:
            _authenticate(request)
        except ProxyError as err:
            return JSONResponse(err.to_openai(), status_code=err.http_status)

        data = None
        headers = sanitize_headers(dict(request.headers), settings.upstream_auth)
        try:
            resp = await upstream.request("GET", "models", headers=headers, content=None)
            if resp.status_code < 400:
                data = resp.json()
        except Exception:  # noqa: BLE001 — upstream down: still return the default alias
            data = None
        return JSONResponse(augment_models(data))

    @app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
    async def generic(request: Request, path: str):
        try:
            _authenticate(request)
        except ProxyError as err:
            return JSONResponse(err.to_openai(), status_code=err.http_status)

        raw = await request.body()
        headers = sanitize_headers(dict(request.headers), settings.upstream_auth)
        try:
            resp = await upstream.request(request.method, path, headers=headers, content=raw or None)
        except Exception as exc:  # noqa: BLE001
            err = map_error(exc)
            return JSONResponse(err.to_openai(), status_code=err.http_status)
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            media_type=resp.headers.get("content-type"),
        )

    return app
