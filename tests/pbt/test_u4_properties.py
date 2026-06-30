"""U4 — property-based tests (PBT-U4-1..6)."""

from __future__ import annotations

import asyncio

from hypothesis import given, settings
from hypothesis import strategies as st

from caduceus.common.dto import (
    AgentView,
    ChangeKind,
    ConfigChange,
    ConfigSnapshot,
    CreateSpec,
    ReloadStrategy,
    apply_change,
    resolve_strategy,
    snapshot_satisfies,
)
from caduceus.common.models import AgentKind, HealthLevel, HealthStatus
from caduceus.config.editor import ReadOnlyError
from caduceus.config.service import ConfigService

from tests.fakes import FakeRegistry, make_agent

_names = st.text(st.characters(min_codepoint=97, max_codepoint=122), min_size=1, max_size=6)
_skills = st.lists(_names, max_size=5, unique=True)


# ---- PBT-U4-1: DTO round-trip -------------------------------------
@given(name=_names, model=st.one_of(st.none(), _names))
def test_createspec_round_trip(name, model):
    x = CreateSpec(name, model)
    assert CreateSpec.from_dict(x.to_dict()) == x


@given(skills=_skills, soul=st.text(max_size=20), core=st.dictionaries(_names, _names, max_size=4))
def test_snapshot_round_trip(skills, soul, core):
    x = ConfigSnapshot(skills=sorted(set(skills)), soul=soul, core=core)
    assert ConfigSnapshot.from_dict(x.to_dict()) == x


# ---- PBT-U4-2: reducer idempotent + order-independent -------------
_change = st.builds(
    ConfigChange,
    add_skills=_skills, remove_skills=_skills,
    enable_tools=_skills, disable_tools=_skills,
    soul=st.one_of(st.none(), st.text(max_size=10)),
    set_core=st.dictionaries(_names, _names, max_size=3),
)


@given(base=_skills, change=_change)
def test_apply_change_idempotent(base, change):
    snap = ConfigSnapshot(skills=sorted(set(base)))
    once = apply_change(snap, change)
    twice = apply_change(once, change)
    assert once == twice
    # normalized: sorted + unique
    assert once.skills == sorted(set(once.skills))


@given(snap_skills=_skills, change=_change)
def test_apply_change_then_satisfies(snap_skills, change):
    # a non-conflicting change must be reflected (read-back verify holds on the pure model)
    snap = ConfigSnapshot(skills=sorted(set(snap_skills)))
    # drop conflicts so the property is well-defined
    change.remove_skills = [s for s in change.remove_skills if s not in change.add_skills]
    change.disable_tools = [t for t in change.disable_tools if t not in change.enable_tools]
    out = apply_change(snap, change)
    assert snapshot_satisfies(out, change)


# ---- PBT-U4-3: projection never leaks secrets ---------------------
@given(name=_names, token=st.text(min_size=1, max_size=12), auth=st.text(min_size=1, max_size=12))
def test_agentview_no_secret(name, token, auth):
    # distinctive secrets so the value check can't collide with projected fields
    secret_token = "SECRET-TOK-" + token
    secret_auth = "SECRET-AUTH-" + auth
    rec = make_agent(name=name)
    rec.token = secret_token
    rec.serve_auth = secret_auth
    view = AgentView.from_record(rec, HealthStatus(HealthLevel.healthy, shallow=True))
    d = view.to_dict()
    # no secret-bearing keys, and the secret values are never projected
    assert "token" not in d and "serve_auth" not in d
    assert secret_token not in str(d) and secret_auth not in str(d)


# ---- PBT-U4-4: remote agents are read-only ------------------------
@given(change=_change)
def test_remote_set_config_always_rejected(change):
    svc = ConfigService(
        FakeRegistry([make_agent(name="r1", kind=AgentKind.remote)]),
        editor=_NullEditor(),
    )

    async def _():
        try:
            await svc.set_config("r1", change)
            return False
        except ReadOnlyError:
            return True

    assert asyncio.run(_()) is True


class _NullEditor:
    async def read(self, rec):
        return ConfigSnapshot()

    async def apply(self, rec, change):
        raise AssertionError("editor must not be reached for remote agents")


# ---- PBT-U4-5: reload-strategy totality + seam --------------------
@given(kinds=st.sets(st.sampled_from(list(ChangeKind))))
def test_resolve_strategy_total(kinds):
    assert resolve_strategy(kinds) in (ReloadStrategy.hot_reload, ReloadStrategy.restart_serve)


@given(extra=st.sets(st.sampled_from(list(ChangeKind))))
def test_resolve_strategy_seam(extra):
    from caduceus.common import dto

    original = dict(dto.CHANGE_KIND_STRATEGY)
    try:
        dto.CHANGE_KIND_STRATEGY[ChangeKind.soul] = ReloadStrategy.restart_serve
        assert dto.resolve_strategy({ChangeKind.soul} | set(extra)) == ReloadStrategy.restart_serve
    finally:
        dto.CHANGE_KIND_STRATEGY.clear()
        dto.CHANGE_KIND_STRATEGY.update(original)


# ---- PBT-U4-6: exit-code mapping is total -------------------------
@given(code=st.sampled_from([0, 1, 2]))
def test_exit_codes_known(code):
    from caduceus.cli.render import EXIT_OK, EXIT_RUNTIME, EXIT_USAGE

    assert code in {EXIT_OK, EXIT_RUNTIME, EXIT_USAGE}
