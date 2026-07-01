"""Property-based tests for U2 (Hypothesis): P-U2-1/2/4/5/6.

- P-U2-1 round-trip, P-U2-2 name invariant, P-U2-6 token entropy: pure.
- P-U2-4/5 stateful: a random command sequence drives the REAL AgentService +
  Registry (with fakes) and is checked against a reference model after each step
  (uniqueness, valid transitions, persisted == in-memory, remote start/stop blocked).
"""

from __future__ import annotations

import asyncio
import os
import tempfile

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from caduceus.agents.names import CONTAINER_PREFIX, container_name, validate_name
from caduceus.agents.registry import Registry
from caduceus.agents.service import AgentService
from caduceus.agents.tokens import MIN_TOKEN_LEN, mint_token
from caduceus.common.errors import ProxyError
from caduceus.common.models import AgentKind, AgentRecord, Lifecycle
from tests.fakes import FakeHealthChecker, FakeImageBuilder, FakeProvisioner

AIGW = "http://172.17.0.1:9701/v1"

_ascii_name = st.from_regex(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,19}\Z")


# ---- pure properties --------------------------------------------------
@given(_ascii_name)
def test_p_u2_2_container_invariant(name):
    v = validate_name(name)
    assert container_name(v) == CONTAINER_PREFIX + v


@given(st.integers(min_value=32, max_value=64))  # we only ever mint with >= 32 bytes (default)
def test_p_u2_6_token_entropy(nbytes):
    t = mint_token(nbytes)
    assert len(t) >= MIN_TOKEN_LEN
    assert len(t) >= nbytes  # urlsafe base64 expands input
    assert t == t.strip()
    assert mint_token(nbytes) != t  # overwhelmingly unique


@given(
    st.builds(
        AgentRecord,
        name=st.text(max_size=20),
        kind=st.sampled_from(list(AgentKind)),
        token=st.text(min_size=1, max_size=40),
        lifecycle=st.sampled_from(list(Lifecycle)),
    )
)
def test_p_u2_1_record_roundtrip(rec):
    assert AgentRecord.from_dict(rec.to_dict()) == rec


# ---- stateful: real AgentService vs reference model -------------------
_ops = st.lists(
    st.tuples(
        st.sampled_from(["create", "register", "stop", "start", "remove"]),
        _ascii_name,
        st.sampled_from(list(AgentKind)),  # only used to vary; kind decided by op
    ),
    max_size=20,
)


@settings(max_examples=50, deadline=None)
@given(_ops)
def test_p_u2_5_stateful_sequence(seq):
    asyncio.run(_run_sequence(seq))


async def _run_sequence(seq):
    with tempfile.TemporaryDirectory() as d:  # /tmp = fast FS
        reg = Registry(os.path.join(d, "state.json"))
        reg.load()
        svc = AgentService(reg, FakeProvisioner(), FakeImageBuilder(), FakeHealthChecker(), AIGW)
        ref: dict[str, str] = {}  # name -> "local" | "remote"  (reference model)

        for op, raw, _kind in seq:
            v = validate_name(raw)  # always valid by construction

            if op == "create":
                if v in ref:
                    with pytest.raises(ProxyError):
                        await svc.create(v)
                else:
                    rec = await svc.create(v)
                    assert rec.lifecycle == Lifecycle.running
                    ref[v] = "local"
            elif op == "register":
                if v in ref:
                    with pytest.raises(ProxyError):
                        await svc.register(v, "http://r")
                else:
                    rec, _ = await svc.register(v, "http://r")
                    assert rec.lifecycle == Lifecycle.registered
                    ref[v] = "remote"
            elif op in ("stop", "start"):
                call = svc.stop if op == "stop" else svc.start
                if v not in ref or ref[v] == "remote":
                    with pytest.raises(ProxyError):  # missing or remote (BR-A10)
                        await call(v)
                else:
                    rec = await call(v)
                    assert rec.lifecycle == (Lifecycle.stopped if op == "stop" else Lifecycle.running)
            elif op == "remove":
                if v in ref:
                    await svc.remove(v)
                    ref.pop(v)
                else:
                    with pytest.raises(ProxyError):
                        await svc.remove(v)

            # invariants after every step
            assert {r.name for r in reg.list()} == set(ref)            # uniqueness + membership
            reloaded = Registry(os.path.join(d, "state.json"))
            reloaded.load()
            assert {r.name for r in reloaded.list()} == set(ref)        # persisted == in-memory
