"""U4 — DTO round-trips, pure config reducer, reload strategy, projection."""

from __future__ import annotations

from caduceus.common.dto import (
    AgentView,
    ChangeKind,
    ConfigChange,
    ConfigResult,
    ConfigSnapshot,
    CreateSpec,
    GatewayStatus,
    RegisterSpec,
    ReloadStrategy,
    apply_change,
    resolve_strategy,
    snapshot_satisfies,
)
from caduceus.common.models import AgentKind, HealthLevel, HealthStatus, Lifecycle

from tests.fakes import make_agent


def test_dto_round_trips():
    for x in [
        CreateSpec("a", model="m"),
        RegisterSpec("r", "http://x", auth="t"),
        AgentView("a", "local", "running", "healthy", endpoint="e", has_session=True),
        GatewayStatus(running=True, pid=1, agent_count=2, version="0.1.0"),
        ConfigSnapshot(skills=["b", "a"], tools_enabled=["t1"], soul="s", core={"k": "v"}),
        ConfigChange(add_skills=["x"], set_core={"k": "v"}, soul="hi"),
        ConfigResult(applied=["+skills"], verified=True),
    ]:
        assert type(x).from_dict(x.to_dict()) == x


def test_agent_view_strips_secrets():
    rec = make_agent(name="a1", session_id="sess")
    rec.token = "SECRET-TOKEN"
    rec.serve_auth = "SECRET-AUTH"
    view = AgentView.from_record(rec, HealthStatus(HealthLevel.healthy, shallow=True))
    blob = str(view.to_dict())
    assert "SECRET-TOKEN" not in blob and "SECRET-AUTH" not in blob
    assert view.has_session is True and view.health == "healthy"


def test_apply_change_basic():
    snap = ConfigSnapshot(skills=["a"], tools_enabled=["t1"], tools_disabled=["t2"], core={"x": "1"})
    change = ConfigChange(add_skills=["b"], remove_skills=["a"], enable_tools=["t2"],
                          disable_tools=["t1"], soul="new", set_core={"y": "2"})
    out = apply_change(snap, change)
    assert out.skills == ["b"]
    assert out.tools_enabled == ["t2"] and out.tools_disabled == ["t1"]
    assert out.soul == "new" and out.core == {"x": "1", "y": "2"}


def test_apply_change_idempotent():
    snap = ConfigSnapshot(skills=["a"])
    change = ConfigChange(add_skills=["b"], enable_tools=["t"])
    once = apply_change(snap, change)
    twice = apply_change(once, change)
    assert once == twice


def test_apply_change_disable_wins_on_conflict():
    snap = ConfigSnapshot()
    change = ConfigChange(enable_tools=["t"], disable_tools=["t"])
    out = apply_change(snap, change)
    assert "t" in out.tools_disabled and "t" not in out.tools_enabled


def test_resolve_strategy_defaults_hot_reload():
    assert resolve_strategy({ChangeKind.skills, ChangeKind.core}) == ReloadStrategy.hot_reload


def test_resolve_strategy_seam_restart(monkeypatch):
    from caduceus.common import dto

    monkeypatch.setitem(dto.CHANGE_KIND_STRATEGY, ChangeKind.soul, ReloadStrategy.restart_serve)
    assert dto.resolve_strategy({ChangeKind.skills, ChangeKind.soul}) == ReloadStrategy.restart_serve
    assert dto.resolve_strategy({ChangeKind.skills}) == ReloadStrategy.hot_reload


def test_snapshot_satisfies():
    snap = ConfigSnapshot(skills=["b"], tools_enabled=["t2"], tools_disabled=["t1"], soul="new", core={"y": "2"})
    change = ConfigChange(add_skills=["b"], remove_skills=["a"], enable_tools=["t2"],
                          disable_tools=["t1"], soul="new", set_core={"y": "2"})
    assert snapshot_satisfies(snap, change) is True
    assert snapshot_satisfies(ConfigSnapshot(), change) is False


def test_affected_kinds():
    assert ConfigChange().is_empty()
    assert ConfigChange(add_skills=["x"]).affected_kinds() == {ChangeKind.skills}
    assert ConfigChange(soul="s").affected_kinds() == {ChangeKind.soul}
