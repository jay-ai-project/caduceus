"""HermesApiTransport (U8) — SSE mapping, session, health, history, stop.

Drives the transport against an in-memory `httpx.MockTransport` (no real hermes).
"""

from __future__ import annotations

import httpx
import pytest

from caduceus.common.models import AgentKind, AgentRecord, HealthLevel
from caduceus.transport.events import ChatEventType
from caduceus.transport.hermes_api import (
    HermesApiTransport,
    _map_event,
    _parse_history,
    _session_id_of,
)

SSE_BODY = (
    "event: run.started\n"
    'data: {"run_id": "run_x"}\n'
    "\n"
    "event: assistant.delta\n"
    'data: {"delta": "Hel"}\n'
    "\n"
    "event: assistant.delta\n"
    'data: {"delta": "lo"}\n'
    "\n"
    "event: tool.progress\n"
    'data: {"tool_name": "_thinking", "delta": "hmm"}\n'
    "\n"
    "event: tool.started\n"
    'data: {"tool_name": "bash", "args": {"cmd": "ls"}}\n'
    "\n"
    "event: tool.completed\n"
    'data: {"tool_name": "bash", "preview": "file1"}\n'
    "\n"
    "event: done\n"
    "data: {}\n"
    "\n"
)


def _rec():
    return AgentRecord(name="a", kind=AgentKind.local, token="tok",
                       endpoint="http://127.0.0.1:49001")


def _mock_transport(record: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        record.setdefault("calls", []).append((request.method, request.url.path))
        p = request.url.path
        if p == "/api/sessions" and request.method == "POST":
            return httpx.Response(200, json={"id": "sess-1"})
        if p.endswith("/chat/stream"):
            return httpx.Response(200, text=SSE_BODY,
                                  headers={"content-type": "text/event-stream"})
        if p == "/health":
            return httpx.Response(200, json={"ok": True})
        if p.endswith("/messages"):
            return httpx.Response(200, json={"messages": [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": [{"type": "text", "text": "yo"}]},
            ]})
        if p.startswith("/v1/runs/") and p.endswith("/stop"):
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404)
    return httpx.MockTransport(handler)


def _wire(t: HermesApiTransport, record: dict):
    mock = _mock_transport(record)

    def _new_client():
        base = (t.rec.endpoint or "").rstrip("/")
        return httpx.AsyncClient(base_url=base, transport=mock,
                                 headers={"Authorization": f"Bearer {t.rec.token}"})
    t._new_client = _new_client  # type: ignore[method-assign]


# ---- pure mapping -------------------------------------------------
def test_map_event_kinds():
    assert _map_event("assistant.delta", {"delta": "x"}).type == ChatEventType.token
    assert _map_event("tool.progress", {"tool_name": "_thinking", "delta": "t"}).type == ChatEventType.thinking
    tc = _map_event("tool.started", {"tool_name": "bash", "args": {"a": 1}})
    assert tc.type == ChatEventType.tool_call and tc.meta["name"] == "bash"
    assert _map_event("done", {}).type == ChatEventType.done
    assert _map_event("run.completed", {}).type == ChatEventType.done
    assert _map_event("error", {"message": "boom"}).type == ChatEventType.error
    # unknown / structural events are ignored, never raise
    assert _map_event("message.started", {"message": {}}) is None
    assert _map_event("assistant.delta", {}) is None  # empty delta


# ---- live-confirmed response shapes (Build & Test) ----------------
def test_session_id_nested_and_flat():
    # hermes 0.17.0: {"object":"hermes.session","session":{"id":...}}
    assert _session_id_of({"object": "hermes.session", "session": {"id": "api_1"}}) == "api_1"
    assert _session_id_of({"id": "flat"}) == "flat"           # flat fallback
    assert _session_id_of({"nope": 1}) is None


def test_parse_history_data_key():
    # hermes 0.17.0: {"object":"list","data":[{role,content,...}]}
    payload = {"object": "list", "data": [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c1"}]},  # empty → skipped
        {"role": "assistant", "content": "yo"},
    ]}
    turns = _parse_history(payload)
    assert [(t.role, t.text) for t in turns] == [("user", "hi"), ("assistant", "yo")]


# ---- streamed turn ------------------------------------------------
async def test_chat_stream_maps_and_terminates():
    t = HermesApiTransport(_rec())
    _wire(t, {})
    events = [ev async for ev in t.chat_stream("hi")]
    types = [e.type for e in events]
    assert types.count(ChatEventType.token) == 2
    assert ChatEventType.thinking in types
    assert types.count(ChatEventType.tool_call) == 2
    # exactly one terminal, and it's last (terminal invariant)
    assert sum(1 for e in events if e.is_terminal()) == 1
    assert events[-1].type == ChatEventType.done
    assert t.session_id == "sess-1"     # created on open
    assert t._run_id == "run_x"         # captured for stop
    await t.close()


async def test_health_ok():
    t = HermesApiTransport(_rec())
    _wire(t, {})
    hs = await t.health()
    assert hs.level == HealthLevel.healthy and hs.shallow
    await t.close()


async def test_load_history():
    t = HermesApiTransport(_rec())
    _wire(t, {})
    turns = await t.load_history("sess-1")
    assert [(x.role, x.text) for x in turns] == [("user", "hi"), ("assistant", "yo")]
    await t.close()


async def test_stop_run_hits_runs_endpoint():
    t = HermesApiTransport(_rec())
    rec: dict = {}
    _wire(t, rec)
    t._run_id = "run_x"
    await t._stop_run()
    assert ("POST", "/v1/runs/run_x/stop") in rec["calls"]
    await t.close()


async def test_health_unreachable_endpoint():
    # a bad endpoint (no mock) → unhealthy, never raises
    t = HermesApiTransport(AgentRecord(name="b", kind=AgentKind.local, token="t",
                                       endpoint="http://127.0.0.1:1"))
    hs = await t.health()
    assert hs.level == HealthLevel.unhealthy and not hs.shallow
    await t.close()
