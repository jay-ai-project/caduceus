"""Integration tests for the AI-Gateway app (ASGI, stub upstream).

Covers BR-1 (auth), BR-2 (model rewrite), BR-5 (streaming), BR-7 (502),
BR-8 (/v1/models), and the P6 stream/unary equivalence oracle.

Uses only fixtures from conftest (`gw_app`, `make_app`, `auth_headers`).
"""

from __future__ import annotations

import json

import httpx
import pytest


async def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gw")


async def test_missing_token_401(gw_app):
    async with await _client(gw_app) as c:
        r = await c.post("/v1/chat/completions", json={"model": "default"})
    assert r.status_code == 401
    assert r.json()["error"]["type"] == "authentication_error"


async def test_invalid_token_401(gw_app):
    async with await _client(gw_app) as c:
        r = await c.post(
            "/v1/chat/completions",
            headers={"authorization": "Bearer nope"},
            json={"model": "default"},
        )
    assert r.status_code == 401


async def test_default_model_is_rewritten(gw_app, auth_headers):
    async with await _client(gw_app) as c:
        r = await c.post("/v1/chat/completions", headers=auth_headers, json={"model": "default"})
    assert r.status_code == 200
    # stub echoes the model it actually received -> must be the resolved default
    assert r.json()["model"] == "stub-model"


async def test_explicit_model_passthrough(gw_app, auth_headers):
    async with await _client(gw_app) as c:
        r = await c.post("/v1/chat/completions", headers=auth_headers, json={"model": "foo/bar"})
    assert r.json()["model"] == "foo/bar"


async def test_streaming_passthrough(gw_app, auth_headers):
    async with await _client(gw_app) as c:
        async with c.stream(
            "POST",
            "/v1/chat/completions",
            headers=auth_headers,
            json={"model": "default", "stream": True},
        ) as resp:
            assert resp.status_code == 200
            body = b"".join([chunk async for chunk in resp.aiter_raw()]).decode()
    assert "[DONE]" in body
    assert "echo:" in body


async def test_models_augmented(gw_app, auth_headers):
    async with await _client(gw_app) as c:
        r = await c.get("/v1/models", headers=auth_headers)
    ids = [m["id"] for m in r.json()["data"]]
    assert "default" in ids
    assert "stub-upstream-model" in ids


async def test_upstream_down_returns_502(make_app, auth_headers):
    app = make_app(failing=True)
    async with await _client(app) as c:
        r = await c.post("/v1/chat/completions", headers=auth_headers, json={"model": "default"})
    assert r.status_code == 502
    assert r.json()["error"]["type"] == "upstream_error"


@pytest.mark.parametrize("model", ["default", "foo/bar", "vendor/model-x"])
async def test_p6_stream_unary_equivalence(make_app, auth_headers, model):
    """Oracle (P6): assistant content assembled from the stream equals the unary
    content for the same request."""
    async with await _client(make_app()) as c:
        unary = await c.post("/v1/chat/completions", headers=auth_headers, json={"model": model})
        unary_content = unary.json()["choices"][0]["message"]["content"]

    assembled = ""
    async with await _client(make_app()) as c:
        async with c.stream(
            "POST",
            "/v1/chat/completions",
            headers=auth_headers,
            json={"model": model, "stream": True},
        ) as resp:
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                payload = line[len("data:"):].strip()
                if payload == "[DONE]":
                    break
                delta = json.loads(payload)["choices"][0]["delta"].get("content", "")
                assembled += delta

    assert assembled == unary_content
