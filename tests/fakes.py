"""Test doubles for U2 (no real Docker/sbx) and U3 (no real hermes serve)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Optional

from caduceus.common.models import (
    AgentKind,
    AgentRecord,
    HealthLevel,
    HealthStatus,
    Lifecycle,
)
from caduceus.transport.base import Transport, TransportKind, TransportState
from caduceus.transport.events import ChatEvent, ChatEventType


class FakeProvisioner:
    def __init__(self, fail_on: str | None = None):
        self.sandboxes: dict[str, str] = {}
        self.files: dict[tuple[str, str], str] = {}
        self.env: dict[str, str] = {}
        self.calls: list[str] = []
        self.fail_on = fail_on

    def _maybe_fail(self, method: str) -> None:
        self.calls.append(method)
        if self.fail_on == method:
            raise RuntimeError(f"fake failure in {method}")

    async def create_sandbox(self, sandbox: str, image: str, env: dict[str, str]) -> None:
        self._maybe_fail("create_sandbox")
        self.sandboxes[sandbox] = "running"
        self.env.update(env)

    async def write_file(self, sandbox: str, path: str, content: str) -> None:
        self._maybe_fail("write_file")
        self.files[(sandbox, path)] = content

    async def start_serve(self, sandbox: str, serve_auth: str) -> int:
        self._maybe_fail("start_serve")
        return 40000

    async def stop(self, sandbox: str) -> None:
        self._maybe_fail("stop")
        self.sandboxes[sandbox] = "stopped"

    async def start(self, sandbox: str) -> None:
        self._maybe_fail("start")
        self.sandboxes[sandbox] = "running"

    async def remove(self, sandbox: str) -> None:
        self.sandboxes.pop(sandbox, None)

    async def status(self, sandbox: str) -> str:
        return self.sandboxes.get(sandbox, "missing")

    async def logs(self, sandbox: str, follow: bool = False) -> AsyncIterator[str]:
        yield "fake log"


class FakeImageBuilder:
    def __init__(self) -> None:
        self.built: list[str] = []

    async def image_exists(self, tag: str) -> bool:
        return True

    async def ensure_image(self, tag: str = "caduceus/hermes:0.17.0", hermes_version: str = "0.17.0") -> str:
        self.built.append(tag)
        return tag


class FakeHealthChecker:
    def __init__(self, level: HealthLevel = HealthLevel.healthy):
        self.level = level

    async def check(self, rec: AgentRecord, deep: bool = False) -> HealthStatus:
        return HealthStatus(self.level, shallow=True, deep=(True if deep else None), checked_at="t")


# ===================================================================
# U3 — Transport & Chat test doubles (no real hermes serve)
# ===================================================================

def make_agent(
    name: str = "a1",
    kind: AgentKind = AgentKind.local,
    session_id: Optional[str] = None,
    lifecycle: Lifecycle = Lifecycle.running,
    serve_port: Optional[int] = 40000,
) -> AgentRecord:
    return AgentRecord(
        name=name,
        kind=kind,
        token="tok",
        serve_auth="serve-secret",
        sandbox_name=("cad-" + name) if kind == AgentKind.local else None,
        serve_port=serve_port if kind == AgentKind.local else None,
        endpoint=(f"http://127.0.0.1:{serve_port}" if kind == AgentKind.local else "http://remote:9119"),
        session_id=session_id,
        lifecycle=lifecycle,
    )


class FakeRegistry:
    """In-memory stand-in for U2 Registry (sync reads, async mutators)."""

    def __init__(self, agents: Optional[list[AgentRecord]] = None):
        self._agents: dict[str, AgentRecord] = {a.name: a for a in (agents or [])}
        self.sessions_set: list[tuple[str, str]] = []

    def get(self, name: str) -> Optional[AgentRecord]:
        return self._agents.get(name)

    def list(self) -> list[AgentRecord]:
        return list(self._agents.values())

    async def upsert(self, rec: AgentRecord) -> None:
        self._agents[rec.name] = rec

    async def set_session(self, name: str, session_id: str) -> None:
        self.sessions_set.append((name, session_id))
        rec = self._agents.get(name)
        if rec is not None:
            rec.session_id = session_id


class FakeTransport(Transport):
    """Scripted transport. `script` is a list of raw ChatEvents (pre-normalize).

    Session behavior: returns the requested `session_id`, unless it equals
    `reject_session` (or is None) in which case it simulates create/recreate by
    setting `session_id = new_session_id` (Q1 transparent recreate).
    Cooperative cancel: when `request_cancel()` is called, the next emitted event
    is `done{cancelled}` (Q6).
    """

    kind = TransportKind.serve

    def __init__(
        self,
        rec: AgentRecord,
        script: Optional[list[ChatEvent]] = None,
        *,
        new_session_id: str = "sess-new",
        reject_session: Optional[str] = None,
        fail_open: bool = False,
        health_level: HealthLevel = HealthLevel.healthy,
    ):
        super().__init__(rec)
        self.script = script if script is not None else [ChatEvent.token_("hi"), ChatEvent.done_()]
        self.new_session_id = new_session_id
        self.reject_session = reject_session
        self.fail_open = fail_open
        self.health_level = health_level
        self.opened = False
        self.closed = False
        self.cancel_sent = False

    async def open(self) -> None:
        if self.fail_open:
            self.state = TransportState.broken
            raise RuntimeError("connect refused")
        self.opened = True
        self.state = TransportState.open

    async def close(self) -> None:
        self.closed = True
        self.state = TransportState.closed

    async def health(self) -> HealthStatus:
        return HealthStatus(self.health_level, shallow=self.health_level == HealthLevel.healthy)

    async def _raw_stream(self, session_id, message):  # noqa: ANN001
        if session_id is None or session_id == self.reject_session:
            self.session_id = self.new_session_id
        else:
            self.session_id = session_id
        for ev in self.script:
            if self._cancelled:
                self.cancel_sent = True
                yield ChatEvent.done_("cancelled", code="cancelled")
                return
            yield ev


# --- uniformity property fakes: two transports, two wire formats, same output ---

class _ScriptedWireTransport(Transport):
    """Base for the uniformity fakes: decode a wire script to ChatEvents."""

    def __init__(self, rec: AgentRecord, wire: list[dict]):
        super().__init__(rec)
        self.wire = wire

    async def open(self) -> None:
        self.state = TransportState.open

    async def close(self) -> None:
        self.state = TransportState.closed

    async def health(self) -> HealthStatus:
        return HealthStatus(HealthLevel.healthy, shallow=True)

    def _decode(self, frame: dict) -> Optional[ChatEvent]:  # overridden
        raise NotImplementedError

    async def _raw_stream(self, session_id, message):  # noqa: ANN001
        self.session_id = session_id or "s"
        for frame in self.wire:
            ev = self._decode(frame)
            if ev is not None:
                yield ev


class ServeLikeFake(_ScriptedWireTransport):
    kind = TransportKind.serve

    def _decode(self, frame: dict) -> Optional[ChatEvent]:
        t = frame["type"]
        if t == "delta":
            return ChatEvent.token_(frame["text"])
        if t == "end":
            return ChatEvent.done_("completed")
        if t == "error":
            return ChatEvent.error_(frame.get("message", "err"), code=frame.get("code", "upstream_error"))
        return None


class AcpLikeFake(_ScriptedWireTransport):
    kind = TransportKind.acp

    def _decode(self, frame: dict) -> Optional[ChatEvent]:
        e = frame["event"]
        if e == "output":
            return ChatEvent.token_(frame["chunk"])
        if e == "complete":
            return ChatEvent.done_("completed")
        if e == "failed":
            return ChatEvent.error_(frame.get("reason", "err"), code=frame.get("code", "upstream_error"))
        return None
