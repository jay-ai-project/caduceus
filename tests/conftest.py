"""Shared test fixtures: a deterministic OpenAI-shaped stub upstream + builders.

The stub lets us test U1 in isolation (no real LLM) and serves as the oracle
for the streaming/unary equivalence property (P6).
"""

from __future__ import annotations

import os

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from hypothesis import settings as hyp_settings

from caduceus.aigateway.app import build_aigateway_app
from caduceus.aigateway.upstream import UpstreamClient
from caduceus.common.settings import Settings, Timeouts

# Hypothesis: log a reproduction blob on failure (PBT-08 reproducibility).
hyp_settings.register_profile("ci", print_blob=True)
hyp_settings.load_profile(os.getenv("HYPOTHESIS_PROFILE", "default"))

GOOD_TOKEN = "good-token"


def token_lookup(token: str) -> str | None:
    return "agent-1" if token == GOOD_TOKEN else None


def make_stub_upstream() -> FastAPI:
    stub = FastAPI()

    @stub.post("/v1/chat/completions")
    async def chat_completions(request: Request):  # noqa: ANN202
        body = await request.json()
        model = body.get("model")
        content = f"echo:{model}"
        if body.get("stream"):
            async def gen():
                # Two deltas whose concatenation == the unary content (oracle for P6).
                yield b'data: {"choices":[{"delta":{"content":"echo:"}}]}\n\n'
                yield (
                    'data: {"choices":[{"delta":{"content":%s}}]}\n\n'
                    % _json_str(model)
                ).encode()
                yield b"data: [DONE]\n\n"

            return StreamingResponse(gen(), media_type="text/event-stream")
        return JSONResponse(
            {
                "id": "stub",
                "object": "chat.completion",
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
            }
        )

    @stub.get("/v1/models")
    async def models():  # noqa: ANN202
        return JSONResponse(
            {"object": "list", "data": [{"id": "stub-upstream-model", "object": "model"}]}
        )

    return stub


def _json_str(s: str) -> str:
    import json

    return json.dumps(s)


def make_settings(**kw) -> Settings:
    base = dict(
        upstream_base_url="http://up/v1",          # test stub URL (not a real/personal endpoint)
        default_model="stub-model",                 # neutral test model (no personal value baked in)
        timeouts=Timeouts(connect=5, read=5, unary_total=5),
    )
    base.update(kw)
    return Settings(**base)


def make_upstream_client(stub_app: FastAPI, settings: Settings) -> UpstreamClient:
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=stub_app), base_url="http://up")
    return UpstreamClient(settings, client=client)


def make_failing_upstream_client(settings: Settings) -> UpstreamClient:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return UpstreamClient(settings, client=client)


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
def stub_upstream() -> FastAPI:
    return make_stub_upstream()


@pytest.fixture
def gw_app(settings, stub_upstream):
    upstream = make_upstream_client(stub_upstream, settings)
    return build_aigateway_app(settings, token_lookup, upstream)


@pytest.fixture
def auth_headers():
    return {"authorization": f"Bearer {GOOD_TOKEN}"}


@pytest.fixture
def make_app():
    """Factory: build an AI-Gateway app with a fresh stub (or a failing) upstream."""

    def _make(settings: Settings | None = None, failing: bool = False):
        settings = settings or make_settings()
        if failing:
            upstream = make_failing_upstream_client(settings)
        else:
            upstream = make_upstream_client(make_stub_upstream(), settings)
        return build_aigateway_app(settings, token_lookup, upstream)

    return _make
