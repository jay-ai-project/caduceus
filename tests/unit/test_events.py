"""U9 — EventBus + `/api/events` push stream + Registry/Supervisor broadcast hooks.

Covers the server side of replacing the dashboard's polling with SSE push:
  - EventBus: snapshot-on-connect, broadcast, coalescing, idle keepalive,
    fault isolation, and subscriber cleanup on disconnect.
  - Registry.set_on_change fires after every persisted mutation.
  - Supervisor fires on_change after each sweep.
  - GET /api/events serves an SSE snapshot frame.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from caduceus.daemon.control_api import build_control_app
from caduceus.daemon.events import EventBus
from caduceus.agents.registry import Registry
from caduceus.transport.supervisor import Supervisor
from caduceus.common.models import HealthLevel, HealthStatus

from tests.fakes import build_fake_services, make_agent


# ---------------- EventBus ----------------

async def test_subscribe_yields_snapshot_on_connect():
    bus = EventBus(lambda: _const({"type": "snapshot", "n": 1}))
    agen = bus.subscribe()
    try:
        first = await asyncio.wait_for(agen.__anext__(), 1)
        assert first == {"type": "snapshot", "n": 1}
    finally:
        await agen.aclose()


async def test_notify_broadcasts_current_snapshot():
    box = {"v": 1}
    bus = EventBus(lambda: _const({"v": box["v"]}))
    agen = bus.subscribe()
    await asyncio.wait_for(agen.__anext__(), 1)  # drain initial
    box["v"] = 2
    await bus.notify()
    pushed = await asyncio.wait_for(agen.__anext__(), 1)
    assert pushed == {"v": 2}
    await agen.aclose()


async def test_notify_coalesces_to_latest_only():
    box = {"v": 0}
    bus = EventBus(lambda: _const({"v": box["v"]}))
    agen = bus.subscribe()
    await asyncio.wait_for(agen.__anext__(), 1)  # initial
    box["v"] = 1
    await bus.notify()
    box["v"] = 2
    await bus.notify()  # supersedes the previous, unconsumed push
    got = await asyncio.wait_for(agen.__anext__(), 1)
    assert got == {"v": 2}                       # latest only
    with pytest.raises(asyncio.TimeoutError):    # no stale second frame queued
        await asyncio.wait_for(agen.__anext__(), 0.1)
    await agen.aclose()


async def test_notify_is_noop_without_subscribers():
    calls = {"n": 0}

    async def provider():
        calls["n"] += 1
        return {}

    bus = EventBus(provider)
    await bus.notify()
    assert calls["n"] == 0                        # provider never invoked when idle


async def test_idle_yields_keepalive_tick():
    bus = EventBus(lambda: _const({"v": 1}))
    agen = bus.subscribe(keepalive=0.05)
    await asyncio.wait_for(agen.__anext__(), 1)   # initial snapshot
    tick = await asyncio.wait_for(agen.__anext__(), 1)
    assert tick is None                           # keepalive on idle
    await agen.aclose()


async def test_notify_swallows_snapshot_failure():
    state = {"fail": False}

    async def provider():
        if state["fail"]:
            raise RuntimeError("boom")
        return {"ok": True}

    bus = EventBus(provider)
    agen = bus.subscribe()
    await asyncio.wait_for(agen.__anext__(), 1)   # initial ok
    state["fail"] = True
    await bus.notify()                            # must not raise
    with pytest.raises(asyncio.TimeoutError):     # nothing pushed on failure
        await asyncio.wait_for(agen.__anext__(), 0.1)
    await agen.aclose()


async def test_subscriber_removed_on_disconnect():
    bus = EventBus(lambda: _const({}))
    agen = bus.subscribe()
    await asyncio.wait_for(agen.__anext__(), 1)
    assert bus.subscriber_count == 1
    await agen.aclose()                           # simulates client disconnect
    assert bus.subscriber_count == 0


# ---------------- producer hooks ----------------

async def test_registry_on_change_fires_on_mutations(tmp_path):
    reg = Registry(tmp_path / "state.json")
    hits = {"n": 0}

    async def on_change():
        hits["n"] += 1

    reg.set_on_change(on_change)
    await reg.upsert(make_agent(name="a1"))
    await reg.set_session("a1", "sess-1")
    await reg.delete("a1")
    assert hits["n"] == 3


async def test_registry_set_session_no_notify_for_missing_agent(tmp_path):
    reg = Registry(tmp_path / "state.json")
    hits = {"n": 0}

    async def on_change():
        hits["n"] += 1

    reg.set_on_change(on_change)
    await reg.set_session("ghost", "sess")        # no such agent → no broadcast
    assert hits["n"] == 0


async def test_supervisor_notifies_after_sweep():
    rec = make_agent(name="a1")
    hits = {"n": 0}

    async def on_change():
        hits["n"] += 1

    async def health(r, deep):
        return HealthStatus(HealthLevel.healthy, shallow=True, deep=True, checked_at="t")

    sup = Supervisor(
        list_agents=lambda: [rec],
        health_check=health,
        restart=_noop,
        mark_failed=_noop,
        on_change=on_change,
    )
    sup.start()
    await asyncio.sleep(0.05)                      # let one sweep run
    await sup.stop()
    assert hits["n"] >= 1


# ---------------- endpoint ----------------

async def test_api_events_streams_snapshot_frame():
    # Drive the route with a *finite* subscription (one snapshot + one keepalive) so
    # the ASGI transport can complete — the endpoint's job is only SSE framing; the
    # real (infinite) bus behaviour is covered by the EventBus unit tests above.
    services = build_fake_services(agents=[make_agent(name="demo")])
    snap = await services.event_bus._snapshot()  # exact live snapshot shape

    class _FiniteBus:
        async def subscribe(self):
            yield snap
            yield None  # keepalive tick

    services.event_bus = _FiniteBus()
    app = build_control_app(services)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://ctl") as c:
        async with c.stream("GET", "/api/events") as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            body = "".join([chunk async for chunk in resp.aiter_text()])

    frames = [b for b in body.split("\n\n") if b.strip()]
    data = json.loads(frames[0][len("data:"):])
    assert data["type"] == "snapshot"
    assert data["status"]["agent_count"] == 1
    assert [a["name"] for a in data["agents"]] == ["demo"]
    assert frames[1].startswith(":")  # keepalive comment line


# ---------------- helpers ----------------

async def _const(value):
    return value


async def _noop(*args, **kwargs):
    return None
