"""Registry: CRUD, atomic persistence, token_lookup (BR-A8)."""

import json

from caduceus.agents.registry import Registry
from caduceus.common.models import AgentKind, AgentRecord


def _rec(name, token):
    return AgentRecord(name=name, kind=AgentKind.local, token=token)


async def test_crud_and_persist(tmp_path):
    path = tmp_path / "state.json"
    reg = Registry(path)
    reg.load()

    await reg.upsert(_rec("a", "tok-a"))
    await reg.upsert(_rec("b", "tok-b"))
    assert {r.name for r in reg.list()} == {"a", "b"}
    assert reg.token_lookup("tok-a") == "a"
    assert reg.token_lookup("nope") is None

    # reload from disk -> same data
    reg2 = Registry(path)
    reg2.load()
    assert reg2.get("a").token == "tok-a"
    assert reg2.get("b").token == "tok-b"

    await reg.delete("a")
    reg3 = Registry(path)
    reg3.load()
    assert reg3.get("a") is None
    assert reg3.get("b") is not None


async def test_state_file_is_valid_json(tmp_path):
    path = tmp_path / "state.json"
    reg = Registry(path)
    reg.load()
    await reg.upsert(_rec("a", "t"))
    doc = json.loads(path.read_text())  # not truncated/partial
    assert doc["version"] == 1
    assert "a" in doc["agents"]


async def test_set_session(tmp_path):
    path = tmp_path / "state.json"
    reg = Registry(path)
    reg.load()
    await reg.upsert(_rec("a", "t"))
    await reg.set_session("a", "sess-123")
    reg2 = Registry(path)
    reg2.load()
    assert reg2.get("a").session_id == "sess-123"
