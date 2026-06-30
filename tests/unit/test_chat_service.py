"""U3 — ChatService: fail-fast gate, session continuity, relay, cancel."""

from __future__ import annotations

from caduceus.common.models import AgentKind, HealthLevel, HealthStatus, Lifecycle
from caduceus.transport.events import ChatEvent, ChatEventType, HistoryTurn
from caduceus.transport.chat import ChatService

from tests.fakes import FakeRegistry, FakeTransport, make_agent


async def _collect(agen):
    return [ev async for ev in agen]


def _healthy(rec, deep):  # health_check callable
    async def _():
        return HealthStatus(HealthLevel.healthy, shallow=True)

    return _()


async def test_unknown_agent_errors():
    cs = ChatService(FakeRegistry(), health_check=_healthy)
    out = await _collect(cs.chat_stream("nope", "hi"))
    assert len(out) == 1 and out[0].type == ChatEventType.error and out[0].code == "agent_not_found"


async def test_fail_fast_on_failed_lifecycle():
    rec = make_agent(lifecycle=Lifecycle.failed)
    cs = ChatService(FakeRegistry([rec]), health_check=_healthy, transport_factory=lambda r: FakeTransport(r))
    out = await _collect(cs.chat_stream("a1", "hi"))
    assert [e.type for e in out] == [ChatEventType.error]
    assert out[0].code == "agent_unavailable"


async def test_fail_fast_on_unhealthy():
    rec = make_agent(lifecycle=Lifecycle.running)

    def unhealthy(r, deep):
        async def _():
            return HealthStatus(HealthLevel.unhealthy, shallow=False, detail="endpoint unreachable")
        return _()

    cs = ChatService(FakeRegistry([rec]), health_check=unhealthy, transport_factory=lambda r: FakeTransport(r))
    out = await _collect(cs.chat_stream("a1", "hi"))
    assert [e.type for e in out] == [ChatEventType.error]
    assert out[0].code == "agent_unavailable"
    # zero token events on fail-fast (PBT-U3-5 spirit)
    assert not any(e.type == ChatEventType.token for e in out)


async def test_creating_agent_gets_one_retry():
    rec = make_agent(lifecycle=Lifecycle.creating)
    calls = {"n": 0}

    def flaky(r, deep):
        async def _():
            calls["n"] += 1
            ok = calls["n"] >= 2  # first probe unhealthy, second healthy
            return HealthStatus(HealthLevel.healthy if ok else HealthLevel.unhealthy, shallow=ok)
        return _()

    cs = ChatService(
        FakeRegistry([rec]), health_check=flaky,
        transport_factory=lambda r: FakeTransport(r, script=[ChatEvent.token_("ok"), ChatEvent.done_()]),
        creating_retry_delay=0.0,
    )
    out = await _collect(cs.chat_stream("a1", "hi"))
    assert calls["n"] == 2
    assert [e.type for e in out] == [ChatEventType.token, ChatEventType.done]


async def test_happy_relays_and_persists_new_session():
    rec = make_agent(session_id=None)
    reg = FakeRegistry([rec])
    ft = FakeTransport(rec, script=[ChatEvent.token_("he"), ChatEvent.token_("llo"), ChatEvent.done_()],
                       new_session_id="sess-1")
    cs = ChatService(reg, health_check=_healthy, transport_factory=lambda r: ft)
    out = await _collect(cs.chat_stream("a1", "hi"))
    assert [e.data for e in out if e.type == ChatEventType.token] == ["he", "llo"]
    assert reg.sessions_set == [("a1", "sess-1")]
    # pooled: the transport is kept open (warm) for reuse, not closed each turn
    assert ft.opened is True and ft.closed is False


async def test_resume_existing_session_not_repersisted():
    rec = make_agent(session_id="s-keep")
    reg = FakeRegistry([rec])
    ft = FakeTransport(rec, script=[ChatEvent.token_("x"), ChatEvent.done_()])
    cs = ChatService(reg, health_check=_healthy, transport_factory=lambda r: ft)
    await _collect(cs.chat_stream("a1", "hi"))
    assert reg.sessions_set == []  # unchanged → no write
    assert ft.session_id == "s-keep"


async def test_transparent_recreate_persists_new_session():
    rec = make_agent(session_id="gone")
    reg = FakeRegistry([rec])
    ft = FakeTransport(rec, script=[ChatEvent.token_("x"), ChatEvent.done_()],
                       reject_session="gone", new_session_id="fresh")
    cs = ChatService(reg, health_check=_healthy, transport_factory=lambda r: ft)
    await _collect(cs.chat_stream("a1", "hi"))
    assert reg.sessions_set == [("a1", "fresh")]


async def test_open_failure_is_fail_fast():
    rec = make_agent()
    ft = FakeTransport(rec, fail_open=True)
    cs = ChatService(FakeRegistry([rec]), health_check=_healthy, transport_factory=lambda r: ft)
    out = await _collect(cs.chat_stream("a1", "hi"))
    assert [e.type for e in out] == [ChatEventType.error]
    assert out[0].code == "agent_unavailable"


async def test_pooled_transport_reused_across_turns():
    rec = make_agent(session_id="s1")
    created: list[FakeTransport] = []

    def factory(r):
        ft = FakeTransport(r, script=[ChatEvent.token_("x"), ChatEvent.done_()])
        created.append(ft)
        return ft

    cs = ChatService(FakeRegistry([rec]), health_check=_healthy, transport_factory=factory)
    await _collect(cs.chat_stream("a1", "hi"))
    await _collect(cs.chat_stream("a1", "again"))
    assert len(created) == 1            # same transport reused across turns
    assert created[0].closed is False   # kept warm


async def test_close_agent_evicts_and_next_turn_respawns():
    rec = make_agent()
    created: list[FakeTransport] = []

    def factory(r):
        ft = FakeTransport(r)
        created.append(ft)
        return ft

    cs = ChatService(FakeRegistry([rec]), health_check=_healthy, transport_factory=factory)
    await _collect(cs.chat_stream("a1", "hi"))
    await cs.close_agent("a1")
    assert created[0].closed is True
    await _collect(cs.chat_stream("a1", "hi"))
    assert len(created) == 2            # respawned after eviction


async def test_broken_transport_is_evicted_and_respawned():
    rec = make_agent()
    created: list[FakeTransport] = []

    def factory(r):
        ft = FakeTransport(r, script=[ChatEvent.error_("boom", code="transport_broken")])
        created.append(ft)
        return ft

    cs = ChatService(FakeRegistry([rec]), health_check=_healthy, transport_factory=factory)
    out = await _collect(cs.chat_stream("a1", "hi"))
    assert out[-1].type == ChatEventType.error
    assert created[0].closed is True   # broken transport evicted
    await _collect(cs.chat_stream("a1", "hi"))
    assert len(created) == 2           # respawned


async def test_cooperative_cancel_preserves_session():
    rec = make_agent(session_id="s1")
    reg = FakeRegistry([rec])
    ft = FakeTransport(
        rec,
        script=[ChatEvent.token_("a"), ChatEvent.token_("b"), ChatEvent.token_("c"), ChatEvent.done_()],
    )
    cs = ChatService(reg, health_check=_healthy, transport_factory=lambda r: ft)
    agen = cs.chat_stream("a1", "hi")

    first = await agen.__anext__()
    assert first == ChatEvent.token_("a")
    ft.request_cancel()
    second = await agen.__anext__()
    assert second.type == ChatEventType.done and second.code == "cancelled"
    await agen.aclose()

    assert ft.cancel_sent is True
    assert reg.sessions_set == []  # session preserved (s1 unchanged)


# ---- U5: history (FR-W10, best-effort, local-only) ----------------
async def test_history_local_returns_turns():
    rec = make_agent(session_id="s1")
    turns = [HistoryTurn("user", "hi"), HistoryTurn("assistant", "yo")]
    cs = ChatService(FakeRegistry([rec]), transport_factory=lambda r: FakeTransport(r, history_turns=turns))
    assert await cs.history("a1") == turns


async def test_history_remote_is_empty():
    rec = make_agent(kind=AgentKind.remote, session_id="s1")
    cs = ChatService(FakeRegistry([rec]),
                     transport_factory=lambda r: FakeTransport(r, history_turns=[HistoryTurn("user", "x")]))
    assert await cs.history("a1") == []


async def test_history_sessionless_is_empty():
    rec = make_agent(session_id=None)
    cs = ChatService(FakeRegistry([rec]))
    assert await cs.history("a1") == []


async def test_history_unknown_agent_is_empty():
    cs = ChatService(FakeRegistry([]))
    assert await cs.history("nope") == []


async def test_history_swallows_transport_error():
    rec = make_agent(session_id="s1")
    cs = ChatService(FakeRegistry([rec]),
                     transport_factory=lambda r: FakeTransport(r, history_error=RuntimeError("boom")))
    assert await cs.history("a1") == []
