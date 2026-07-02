"""U3 — property-based tests (PBT-U3-1..7).

Covered here with Hypothesis:
- PBT-U3-2  ChatEvent serialization round-trip
- PBT-U3-1  normalize_stream: exactly one terminal, nothing after it
- PBT-U3-3  transport uniformity: Serve-like vs Acp-like yield identical streams
- PBT-U3-6  Supervisor state-machine invariants over arbitrary health/restart sequences
(PBT-U3-4 session persistence, -5 fail-fast, -7 cooperative cancel are covered by the
unit suite in test_chat_service.py.)
"""

from __future__ import annotations

import asyncio

from hypothesis import given, settings
from hypothesis import strategies as st

from caduceus.common.models import AgentKind, HealthLevel, HealthStatus
from caduceus.transport.events import ChatEvent, ChatEventType, normalize_stream
from caduceus.transport.supervisor import CircuitState, Supervisor

from tests.fakes import AcpLikeFake, ServeLikeFake, make_agent


# ---- PBT-U3-2: ChatEvent round-trip -------------------------------
@given(
    t=st.sampled_from(list(ChatEventType)),
    data=st.text(),
    code=st.one_of(st.none(), st.text(min_size=1, max_size=20)),
)
def test_chat_event_round_trip(t, data, code):
    ev = ChatEvent(t, data, code)
    assert ChatEvent.from_dict(ev.to_dict()) == ev


# ---- PBT-U3-1: single terminal, nothing after ---------------------
_raw_event = st.one_of(
    st.builds(ChatEvent.token_, st.text(max_size=5)),
    st.builds(lambda s: ChatEvent(ChatEventType.message, s), st.text(max_size=5)),
    # U5 non-terminal additions — must NOT break the single-terminal invariant (PBT-W1)
    st.builds(ChatEvent.thinking_, st.text(max_size=5)),
    st.builds(lambda s: ChatEvent.tool_(s or "t", id=s or "id1", status="in_progress"), st.text(max_size=5)),
    st.builds(lambda s: ChatEvent.done_(s or "completed"), st.text(max_size=5)),
    st.builds(lambda s: ChatEvent.error_(s or "e", code="x"), st.text(max_size=5)),
)


# ---- PBT-W2: ChatEvent round-trip incl. populated `meta` ----------
@given(
    title=st.text(max_size=8), tid=st.text(min_size=1, max_size=8),
    status=st.sampled_from(["pending", "in_progress", "completed", "failed"]),
    inp=st.text(max_size=12), out=st.text(max_size=12),
)
def test_tool_event_round_trip_with_meta(title, tid, status, inp, out):
    ev = ChatEvent.tool_(title, id=tid, status=status, input=inp, output=out)
    assert ChatEvent.from_dict(ev.to_dict()) == ev
    assert ev.meta["id"] == tid and ev.meta["status"] == status


async def _collect(agen):
    return [ev async for ev in agen]


async def _aiter(items):
    for it in items:
        yield it


@given(raw=st.lists(_raw_event, max_size=12))
def test_normalize_single_terminal(raw):
    out = asyncio.run(_collect(normalize_stream(_aiter(raw))))
    terminals = [i for i, e in enumerate(out) if e.is_terminal()]
    assert len(terminals) == 1            # exactly one terminal
    assert terminals[0] == len(out) - 1   # and it is the last event


# ---- PBT-U3-3: transport uniformity (FR-C3/C4) --------------------
_step = st.one_of(
    st.builds(lambda s: ("token", s), st.text(min_size=1, max_size=5)),
    st.just(("end", None)),
    st.builds(lambda s: ("error", s or "err"), st.text(max_size=5)),
)


def _to_serve_wire(steps):
    out = []
    for kind, val in steps:
        if kind == "token":
            out.append({"type": "delta", "text": val})
        elif kind == "end":
            out.append({"type": "end"})
        else:
            out.append({"type": "error", "message": val, "code": "upstream_error"})
    return out


def _to_acp_wire(steps):
    out = []
    for kind, val in steps:
        if kind == "token":
            out.append({"event": "output", "chunk": val})
        elif kind == "end":
            out.append({"event": "complete"})
        else:
            out.append({"event": "failed", "reason": val, "code": "upstream_error"})
    return out


@given(steps=st.lists(_step, max_size=10))
def test_transport_uniformity(steps):
    rec = make_agent()
    serve = ServeLikeFake(rec, _to_serve_wire(steps))
    acp = AcpLikeFake(rec, _to_acp_wire(steps))
    a = asyncio.run(_collect(serve.chat_stream("hi")))
    b = asyncio.run(_collect(acp.chat_stream("hi")))
    assert a == b  # identical ChatEvent streams regardless of transport


# ---- PBT-U3-6: Supervisor state-machine invariants ----------------
class _SupHarness:
    def __init__(self, kind=AgentKind.local):
        self.rec = make_agent(kind=kind)
        self.t = 0.0
        self.healthy = True
        self.restart_ok = True
        self.restarts = 0
        self.failed = []
        self.sup = Supervisor(
            list_agents=lambda: [self.rec],
            health_check=self._health,
            restart=self._restart,
            mark_failed=self._mark,
            clock=lambda: self.t,
            fail_threshold=2,
            restart_threshold=3,
            backoff=(5.0, 15.0, 45.0, 120.0),
        )

    async def _health(self, rec, deep):
        lvl = HealthLevel.healthy if self.healthy else HealthLevel.unhealthy
        return HealthStatus(lvl, shallow=self.healthy)

    async def _restart(self, rec):
        self.restarts += 1
        if not self.restart_ok:
            raise RuntimeError("restart failed")

    async def _mark(self, name):
        self.failed.append(name)


_sup_step = st.fixed_dictionaries(
    {"healthy": st.booleans(), "restart_ok": st.booleans(), "dt": st.floats(min_value=0, max_value=300)}
)


@settings(max_examples=80)
@given(steps=st.lists(_sup_step, max_size=25), kind=st.sampled_from([AgentKind.local, AgentKind.remote]))
def test_supervisor_invariants(steps, kind):
    asyncio.run(_run_sup(steps, kind))


async def _run_sup(steps, kind):
    h = _SupHarness(kind=kind)
    for s in steps:
        h.healthy = s["healthy"]
        h.restart_ok = s["restart_ok"]
        h.t += s["dt"]
        st_before = h.sup.state_of(h.rec.name)
        circuit_before = st_before.circuit if st_before else CircuitState.closed
        restarts_before = h.restarts

        await h.sup._sweep()

        cur = h.sup.state_of(h.rec.name)
        # remote agents are never restarted (BR-A10/BR-S1)
        if kind == AgentKind.remote:
            assert h.restarts == 0
        # circuit already open at start ⇒ no restart attempted this step (BR-S5)
        if circuit_before == CircuitState.open:
            assert h.restarts == restarts_before
        # back-off index is bounded by the schedule length
        assert cur.backoff_index <= len(h.sup.backoff)
        # a healthy sweep fully resets the agent's supervision state (BR-S6)
        if s["healthy"]:
            assert cur.consecutive_health_failures == 0
            assert cur.restart_attempts == 0
            assert cur.circuit == CircuitState.closed
