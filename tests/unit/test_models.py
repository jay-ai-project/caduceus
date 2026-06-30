"""AgentRecord serialization round-trip (example-based anchor for P-U2-1)."""

from caduceus.common.models import (
    AgentKind,
    AgentRecord,
    HealthLevel,
    HealthStatus,
    Lifecycle,
)


def test_roundtrip_minimal():
    r = AgentRecord(name="a", kind=AgentKind.local, token="t")
    assert AgentRecord.from_dict(r.to_dict()) == r


def test_roundtrip_full():
    r = AgentRecord(
        name="a", kind=AgentKind.remote, token="t", endpoint="http://x",
        sandbox_name="cad-a", serve_port=40000, serve_auth="s",
        model_alias="default", session_id="sess", lifecycle=Lifecycle.running,
        last_health=HealthStatus(HealthLevel.healthy, True, True, "ok", "t"),
        created_at="c", updated_at="u",
    )
    assert AgentRecord.from_dict(r.to_dict()) == r
