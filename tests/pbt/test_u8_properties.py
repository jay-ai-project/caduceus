"""Property-based tests for U8 (HTTP/SSE + Docker): PBT-U8-1..5.

- PBT-U8-1  SSE→ChatEvent mapping totality + terminal invariant.
- PBT-U8-2  container-runtime validation totality.
- PBT-U8-3  DockerProvisioner (fake) state machine vs a reference model.
- PBT-U8-4  real-time `list` determinism (pure function of live status + health).
- PBT-U8-5  cooperative cancel yields exactly one terminal `done{cancelled}`.
"""

from __future__ import annotations

import asyncio
import os
import tempfile

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from caduceus.agents.registry import Registry
from caduceus.agents.service import AgentService
from caduceus.common.models import AgentKind, Lifecycle
from caduceus.config.gateway_config import VALID_RUNTIMES, validate_runtime
from caduceus.transport.events import ChatEvent, ChatEventType, normalize_stream
from caduceus.transport.hermes_api import _map_event
from tests.fakes import (
    FakeHealthChecker,
    FakeImageBuilder,
    FakeProvisioner,
    FakeTransport,
    make_agent,
)

AIGW = "http://172.17.0.1:9701/v1"

_EVENT_NAMES = st.sampled_from([
    "run.started", "message.started", "assistant.delta", "tool.progress",
    "tool.started", "tool.completed", "tool.failed", "assistant.completed",
    "run.completed", "done", "error", "bogus.event",
])
_DATA = st.dictionaries(
    st.sampled_from(["delta", "tool_name", "args", "preview", "message", "run_id"]),
    st.one_of(st.text(max_size=8), st.none(), st.integers()),
    max_size=3,
)


async def _collect(agen):
    return [ev async for ev in agen]


async def _aiter(items):
    for it in items:
        yield it


# ---- PBT-U8-1: mapping totality + terminal invariant ------------------
@given(events=st.lists(st.tuples(_EVENT_NAMES, _DATA), max_size=15))
def test_pbt_u8_1_mapping_totality_and_terminal(events):
    # _map_event never raises for any (name, data)
    mapped = [ev for (n, d) in events if (ev := _map_event(n, d)) is not None]
    # feed the mapped events through normalize_stream → exactly one terminal, last
    out = asyncio.run(_collect(normalize_stream(_aiter(mapped))))
    terminals = [i for i, e in enumerate(out) if e.is_terminal()]
    assert len(terminals) == 1
    assert terminals[0] == len(out) - 1


# ---- PBT-U8-2: runtime validation totality ----------------------------
@given(s=st.text(max_size=12))
def test_pbt_u8_2_runtime_validation_total(s):
    if s in VALID_RUNTIMES:
        validate_runtime(s)  # no raise
    else:
        with pytest.raises(ValueError):
            validate_runtime(s)


# ---- PBT-U8-3: DockerProvisioner (fake) state machine -----------------
_prov_ops = st.lists(
    st.tuples(st.sampled_from(["create", "start", "stop", "remove"]),
              st.sampled_from(["cad-a", "cad-b"])),
    max_size=25,
)


@settings(max_examples=60, deadline=None)
@given(ops=_prov_ops)
def test_pbt_u8_3_provisioner_state_machine(ops):
    async def _run():
        prov = FakeProvisioner()
        present: set[str] = set()      # reference: containers that exist
        running: set[str] = set()      # reference: containers that are running

        for op, name in ops:
            if op == "create":
                if name in present:
                    continue  # skip (create is not idempotent in reality; keep model simple)
                await prov.create(name, "img", {}, "runc")
                present.add(name)      # created (not running)
            elif op == "start":
                if name in present:
                    await prov.start(name)
                    running.add(name)
            elif op == "stop":
                if name in present:
                    await prov.stop(name)
                    running.discard(name)
            elif op == "remove":
                await prov.remove(name)  # idempotent / safe even if absent
                present.discard(name)
                running.discard(name)

            # invariant: live status never contradicts the reference model
            for c in ("cad-a", "cad-b"):
                st_ = await prov.status(c)
                if c not in present:
                    assert st_ == "missing"
                elif c in running:
                    assert st_ == "running"
                else:
                    assert st_ == "stopped"

    asyncio.run(_run())


# ---- PBT-U8-4: real-time list determinism -----------------------------
@settings(max_examples=25, deadline=None)
@given(n=st.integers(min_value=0, max_value=4))
def test_pbt_u8_4_list_is_pure_function_of_live_state(n):
    async def _run():
        reg = Registry(os.path.join(tempfile.mkdtemp(), "state.json")); reg.load()
        prov = FakeProvisioner()
        svc = AgentService(reg, prov, FakeImageBuilder(), FakeHealthChecker(), AIGW,
                           ready_timeout=2.0)
        for i in range(n):
            await svc.create(f"a{i}")
        # Poison any stale cached health; the live list must ignore it (no cache).
        for rec in reg.list():
            rec.last_health = None
        a = await svc.list(probe=True)
        b = await svc.list(probe=True)
        # deterministic given identical live inputs
        assert [(r.name, r.lifecycle, r.last_health.level) for r in a] == \
               [(r.name, r.lifecycle, r.last_health.level) for r in b]
        # every agent got a fresh health verdict (not the poisoned None)
        assert all(r.last_health is not None for r in a)

    asyncio.run(_run())


# ---- PBT-U8-5: cooperative cancel → exactly one terminal --------------
@settings(max_examples=40, deadline=None)
@given(k=st.integers(min_value=0, max_value=6))
def test_pbt_u8_5_cancel_single_terminal(k):
    async def _run():
        script = [ChatEvent.token_(str(i)) for i in range(k)] + [ChatEvent.done_()]
        t = FakeTransport(make_agent(), script=script)
        await t.open()
        t.request_cancel()  # cancel before/at stream start
        out = [ev async for ev in t.chat_stream("hi")]
        terminals = [e for e in out if e.is_terminal()]
        assert len(terminals) == 1
        assert out[-1].type == ChatEventType.done

    asyncio.run(_run())
