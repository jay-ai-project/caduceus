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

    def workspace_for(self, sandbox: str) -> str:
        return f"/ws/{sandbox}"

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


# ===================================================================
# U4 — CLI / Daemon / Config test doubles
# ===================================================================
from types import SimpleNamespace  # noqa: E402

from caduceus.common.dto import (  # noqa: E402
    AgentView,
    ConfigResult,
    ConfigSnapshot,
    GatewayStatus,
)


class FakeAgentService:
    def __init__(self, agents=None):
        self._agents = {a.name: a for a in (agents or [])}
        self.removed: list[str] = []

    async def create(self, name):
        rec = make_agent(name=name, lifecycle=Lifecycle.running)
        self._agents[name] = rec
        return rec

    async def register(self, name, endpoint, auth=None):
        rec = make_agent(name=name, kind=AgentKind.remote, lifecycle=Lifecycle.registered)
        rec.endpoint = endpoint
        self._agents[name] = rec
        return rec, "guidance: point your remote hermes at the AI-Gateway"

    async def list(self, deep=False):
        return list(self._agents.values())

    async def remove(self, name, force=False):
        self.removed.append(name)
        self._agents.pop(name, None)

    async def stop(self, name):
        self._agents[name].lifecycle = Lifecycle.stopped
        return self._agents[name]

    async def start(self, name):
        self._agents[name].lifecycle = Lifecycle.running
        return self._agents[name]


class FakeChatService:
    def __init__(self, script=None):
        self.script = script if script is not None else [ChatEvent.token_("hi"), ChatEvent.done_()]

    async def chat_stream(self, name, message):
        for ev in self.script:
            yield ev


class FakeConfigService:
    def __init__(self, snapshot=None, result=None, raise_on_set=None):
        self.snapshot = snapshot or ConfigSnapshot(skills=["s1"])
        self.result = result or ConfigResult(applied=["+skills ['s1']"], verified=True, reloaded=True)
        self.raise_on_set = raise_on_set

    async def get_config(self, name):
        return self.snapshot

    async def set_config(self, name, change):
        if self.raise_on_set is not None:
            raise self.raise_on_set
        return self.result


def build_fake_services(agents=None, chat_script=None, config_service=None):
    reg = FakeRegistry(agents or [])
    return SimpleNamespace(
        settings=SimpleNamespace(control_bind="127.0.0.1:9700", aigateway_bind="172.17.0.1:9701"),
        registry=reg,
        agent_service=FakeAgentService(agents or []),
        chat_service=FakeChatService(chat_script),
        config_service=config_service or FakeConfigService(),
        provisioner=FakeProvisioner(),
    )


class FakeControlAPIClient:
    """Mirrors ControlAPIClient's surface for CLI tests (no HTTP)."""

    def __init__(self, *, up=True, agents=None, chat_script=None,
                 snapshot=None, result=None, raise_error=None, status=None):
        self.up = up
        self._agents = list(agents or [])
        self._chat = chat_script if chat_script is not None else [ChatEvent.token_("hello"), ChatEvent.done_()]
        self._snapshot = snapshot or ConfigSnapshot(skills=["s1"])
        self._result = result or ConfigResult(applied=["+skills ['s1']"], verified=True)
        self._raise = raise_error
        self._status = status or GatewayStatus(running=True, pid=123, control_listener="127.0.0.1:9700",
                                               aigateway_listener="172.17.0.1:9701", agent_count=len(agents or []),
                                               version="0.1.0")

    def is_daemon_up(self):
        return self.up

    def status(self):
        return self._status

    def create_agent(self, spec):
        v = AgentView(name=spec.name, kind="local", lifecycle="running", health="healthy")
        return v

    def register_agent(self, spec):
        return {"agent": AgentView(name=spec.name, kind="remote", lifecycle="registered", health="unknown").to_dict(),
                "guidance": "point your remote hermes at the AI-Gateway"}

    def list_agents(self, deep=False):
        return list(self._agents)

    def remove_agent(self, name, force=False):
        if self._raise:
            raise self._raise

    def stop_agent(self, name):
        return AgentView(name=name, kind="local", lifecycle="stopped", health="unknown")

    def start_agent(self, name):
        return AgentView(name=name, kind="local", lifecycle="running", health="healthy")

    def get_config(self, name):
        return self._snapshot

    def set_config(self, name, change):
        if self._raise:
            raise self._raise
        return self._result

    def chat(self, name, message):
        for ev in self._chat:
            yield ev

    def logs(self, name, follow=False):
        yield "log line 1"
        yield "log line 2"
