"""U4 — ConfigService / ConfigEditor: apply + verify, remote read-only."""

from __future__ import annotations

import pytest

from caduceus.common.dto import ConfigChange, ConfigSnapshot, ReloadStrategy, apply_change
from caduceus.common.models import AgentKind, HealthLevel, HealthStatus
from caduceus.config.editor import ConfigEditor, ReadOnlyError
from caduceus.config.service import ConfigService

from tests.fakes import FakeRegistry, make_agent


class FakeSandboxConfig:
    """In-memory stand-in for the sandbox hermes config (read/write/reload)."""

    def __init__(self, snapshot=None, verify=True):
        self.snap = snapshot or ConfigSnapshot()
        self.reloads: list[ReloadStrategy] = []
        self.verify = verify

    async def read(self, rec):
        return self.snap

    async def write(self, rec, snapshot):
        # honor verify flag: if False, simulate a write that doesn't take
        self.snap = snapshot if self.verify else self.snap

    async def reload(self, rec, strategy):
        self.reloads.append(strategy)

    async def health(self, rec, deep):
        return HealthStatus(HealthLevel.healthy, shallow=True)


def _editor(fsc):
    return ConfigEditor(fsc.read, fsc.write, fsc.reload, fsc.health)


async def test_apply_happy_path_verified():
    fsc = FakeSandboxConfig(ConfigSnapshot(skills=["a"]))
    editor = _editor(fsc)
    reg = FakeRegistry([make_agent(name="a1")])
    svc = ConfigService(reg, editor)

    result = await svc.set_config("a1", ConfigChange(add_skills=["b"], enable_tools=["t"]))
    assert result.verified is True
    assert result.reloaded is True
    assert result.strategy == ReloadStrategy.hot_reload.value
    assert fsc.reloads == [ReloadStrategy.hot_reload]
    assert "b" in fsc.snap.skills


async def test_apply_not_verified_when_write_noop():
    fsc = FakeSandboxConfig(ConfigSnapshot(skills=["a"]), verify=False)
    svc = ConfigService(FakeRegistry([make_agent(name="a1")]), _editor(fsc))
    result = await svc.set_config("a1", ConfigChange(add_skills=["b"]))
    assert result.verified is False
    assert result.detail


async def test_remote_set_is_read_only():
    svc = ConfigService(FakeRegistry([make_agent(name="r1", kind=AgentKind.remote)]),
                        _editor(FakeSandboxConfig()))
    with pytest.raises(ReadOnlyError):
        await svc.set_config("r1", ConfigChange(add_skills=["b"]))


async def test_remote_get_is_read_only():
    svc = ConfigService(FakeRegistry([make_agent(name="r1", kind=AgentKind.remote)]),
                        _editor(FakeSandboxConfig()))
    with pytest.raises(ReadOnlyError):
        await svc.get_config("r1")


async def test_get_local_returns_snapshot():
    fsc = FakeSandboxConfig(ConfigSnapshot(skills=["a", "b"]))
    svc = ConfigService(FakeRegistry([make_agent(name="a1")]), _editor(fsc))
    snap = await svc.get_config("a1")
    assert snap.skills == ["a", "b"]


async def test_soul_conflict_rejected():
    editor = _editor(FakeSandboxConfig())
    rec = make_agent(name="a1")
    result = await editor.apply(rec, ConfigChange(soul="inline", soul_file="/path"))
    assert result.verified is False and "not both" in result.detail


async def test_empty_change_is_noop():
    editor = _editor(FakeSandboxConfig())
    result = await editor.apply(make_agent(name="a1"), ConfigChange())
    assert result.reloaded is False and result.verified is True
