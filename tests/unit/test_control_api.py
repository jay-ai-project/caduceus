"""U4 — Control API routes over fake services (in-process ASGI)."""

from __future__ import annotations

import httpx
import pytest

from caduceus.common.models import AgentKind
from caduceus.config.editor import ReadOnlyError
from caduceus.daemon.control_api import build_control_app
from caduceus.transport.events import HistoryTurn

from tests.fakes import FakeChatService, FakeConfigService, build_fake_services, make_agent


def _client(services):
    app = build_control_app(services)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://ctl")


async def test_healthz_and_status():
    services = build_fake_services(agents=[make_agent(name="a1")])
    async with _client(services) as c:
        assert (await c.get("/healthz")).json() == {"ok": True}
        st = (await c.get("/status")).json()
        assert st["running"] is True and st["agent_count"] == 1


async def test_list_agents_strips_secrets():
    rec = make_agent(name="a1", session_id="sess")
    rec.token = "SECRET-TOKEN"
    services = build_fake_services(agents=[rec])
    async with _client(services) as c:
        resp = await c.get("/agents")
        body = resp.text
        data = resp.json()
    assert "SECRET-TOKEN" not in body
    assert data[0]["name"] == "a1" and data[0]["has_session"] is True


async def test_create_agent_streams_progress_then_done():
    import json

    services = build_fake_services()
    async with _client(services) as c:
        async with c.stream("POST", "/agents", json={"name": "new1"}) as resp:
            assert resp.status_code == 200
            events = [json.loads(line[len("data:"):]) for line in
                      [ln async for ln in resp.aiter_lines() if ln.startswith("data:")]]
    phases = [e["phase"] for e in events if e["event"] == "progress"]
    assert "creating sandbox" in phases                    # progress streamed
    done = [e for e in events if e["event"] == "done"]
    assert len(done) == 1 and done[0]["agent"]["name"] == "new1"  # final result


async def test_chat_streams_sse():
    services = build_fake_services(chat_script=None, agents=[make_agent(name="a1")])
    async with _client(services) as c:
        async with c.stream("POST", "/agents/a1/chat", json={"message": "hi"}) as resp:
            assert resp.status_code == 200
            chunks = [line async for line in resp.aiter_lines() if line.startswith("data:")]
    assert any('"type": "token"' in ch for ch in chunks)
    assert any('"type": "done"' in ch for ch in chunks)


async def test_config_get_and_put():
    services = build_fake_services(agents=[make_agent(name="a1")])
    async with _client(services) as c:
        got = await c.get("/agents/a1/config")
        assert got.status_code == 200 and "skills" in got.json()
        put = await c.put("/agents/a1/config", json={"add_skills": ["x"]})
        assert put.status_code == 200 and put.json()["verified"] is True


async def test_remote_config_returns_409():
    services = build_fake_services()
    services.config_service = FakeConfigService(raise_on_set=ReadOnlyError("remote read-only"))
    async with _client(services) as c:
        resp = await c.put("/agents/r1/config", json={"add_skills": ["x"]})
    assert resp.status_code == 409
    assert "read-only" in resp.json()["error"]["message"]


# ---- U5: Web UI serving + history endpoint ------------------------
async def test_root_redirects_to_ui():
    services = build_fake_services()
    async with _client(services) as c:
        resp = await c.get("/")  # AsyncClient does not auto-follow
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/ui/"


async def test_ui_index_is_served():
    services = build_fake_services()
    async with _client(services) as c:
        resp = await c.get("/ui/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Caduceus" in resp.text


async def test_history_endpoint_returns_turns():
    services = build_fake_services(agents=[make_agent(name="a1")])
    services.chat_service = FakeChatService(history=[HistoryTurn("user", "hi"), HistoryTurn("assistant", "yo")])
    async with _client(services) as c:
        resp = await c.get("/agents/a1/history")
    assert resp.status_code == 200
    assert resp.json()["turns"] == [{"role": "user", "text": "hi"}, {"role": "assistant", "text": "yo"}]


async def test_history_unknown_agent_errors():
    services = build_fake_services()
    async with _client(services) as c:
        resp = await c.get("/agents/nope/history")
    assert resp.status_code == 404


async def test_logs_local_only():
    rec_remote = make_agent(name="r1", kind=AgentKind.remote)
    services = build_fake_services(agents=[rec_remote])
    async with _client(services) as c:
        resp = await c.get("/agents/r1/logs")
    assert resp.status_code == 409
