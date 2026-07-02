"""Test doubles for U2/U3/U4 under U8: no real Docker, no real hermes API server."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Optional

from caduceus.agents.provisioner import RuntimeUnavailable
from caduceus.common.models import (
    AgentKind,
    AgentRecord,
    HealthLevel,
    HealthStatus,
    Lifecycle,
)
from caduceus.transport.base import Transport, TransportKind, TransportState
from caduceus.transport.events import ChatEvent


class FakeProvisioner:
    """In-memory stand-in for DockerProvisioner (U8 Protocol)."""

    def __init__(self, fail_on: str | None = None, unavailable_runtimes: Optional[set[str]] = None):
        # container -> "created" | "running" | "stopped"
        self.containers: dict[str, str] = {}
        self.configs: dict[str, str] = {}
        self.env: dict[str, str] = {}
        self.runtimes: dict[str, str] = {}
        self.ports: dict[str, int] = {}
        self.calls: list[str] = []
        self.fail_on = fail_on
        self.unavailable_runtimes = unavailable_runtimes or set()
        self._next_port = 49001

    def _maybe_fail(self, method: str) -> None:
        self.calls.append(method)
        if self.fail_on == method:
            raise RuntimeError(f"fake failure in {method}")

    def workspace_for(self, container: str) -> str:
        return f"/ws/{container}"

    async def create(self, container: str, image: str, env: dict[str, str], runtime: str) -> None:
        self._maybe_fail("create")
        if runtime and runtime != "runc" and runtime in self.unavailable_runtimes:
            raise RuntimeUnavailable(f"runtime '{runtime}' not available")
        self.containers[container] = "created"
        self.env.update(env)
        self.runtimes[container] = runtime
        self.ports[container] = self._next_port
        self._next_port += 1

    async def host_port(self, container: str) -> Optional[int]:
        self.calls.append("host_port")
        return self.ports.get(container)

    async def write_config(self, container: str, content: str) -> None:
        self._maybe_fail("write_config")
        self.configs[container] = content

    async def stop(self, container: str) -> None:
        self._maybe_fail("stop")
        self.containers[container] = "stopped"

    async def start(self, container: str) -> None:
        self._maybe_fail("start")
        self.containers[container] = "running"
        # Docker reassigns the published ephemeral host port on each start (U8-D5).
        self.ports[container] = self._next_port
        self._next_port += 1

    async def remove(self, container: str) -> None:
        self.calls.append("remove")
        self.containers.pop(container, None)
        self.ports.pop(container, None)

    async def status(self, container: str) -> str:
        self.calls.append("status")
        st = self.containers.get(container)
        if st is None:
            return "missing"
        return "running" if st == "running" else "stopped"

    async def statuses(self) -> dict[str, str]:
        self.calls.append("statuses")
        if getattr(self, "statuses_raises", False):
            raise RuntimeError("docker ps failed")
        return {c: ("running" if st == "running" else "stopped")
                for c, st in self.containers.items()}

    async def logs(self, container: str, follow: bool = False) -> AsyncIterator[str]:
        yield "fake log"

    # ---- agent-config I/O (U10/R9): in-memory files keyed (container, path) ----
    async def read_file(self, container: str, path: str) -> Optional[str]:
        self.calls.append("read_file")
        if path.endswith("config.yaml"):
            return self.configs.get(container)
        return getattr(self, "files", {}).get((container, path))

    async def write_file(self, container: str, path: str, content: str) -> None:
        self._maybe_fail("write_file")
        if path.endswith("config.yaml"):
            self.configs[container] = content
            return
        if not hasattr(self, "files"):
            self.files = {}
        self.files[(container, path)] = content

    async def list_dir(self, container: str, path: str) -> list[str]:
        self.calls.append("list_dir")
        return sorted(getattr(self, "skill_dirs", {}).get(container, []))

    async def remove_path(self, container: str, path: str) -> None:
        self._maybe_fail("remove_path")
        name = path.rsplit("/", 1)[-1]
        getattr(self, "skill_dirs", {}).get(container, set()).discard(name)


class FakeImageBuilder:
    def __init__(self) -> None:
        self.built: list[str] = []

    async def image_exists(self, tag: str) -> bool:
        return True

    async def ensure_image(self, tag: str = "nousresearch/hermes-agent:v2026.6.19",
                           progress=None) -> str:
        self.built.append(tag)
        return tag


class FakeHealthChecker:
    """Reports `level` (shallow always True unless the agent name is in `unhealthy`)."""

    def __init__(self, level: HealthLevel = HealthLevel.healthy, unhealthy: Optional[set[str]] = None):
        self.level = level
        self.unhealthy = unhealthy or set()

    async def check(self, rec: AgentRecord, deep: bool = False) -> HealthStatus:
        if rec.name in self.unhealthy:
            return HealthStatus(HealthLevel.unhealthy, shallow=False, detail="unhealthy", checked_at="t")
        return HealthStatus(self.level, shallow=True, deep=(True if deep else None), checked_at="t")


# ===================================================================
# U3 — Transport & Chat test doubles (no real hermes API server)
# ===================================================================

def make_agent(
    name: str = "a1",
    kind: AgentKind = AgentKind.local,
    session_id: Optional[str] = None,
    lifecycle: Lifecycle = Lifecycle.running,
    host_port: Optional[int] = 49001,
    runtime: str = "runc",
) -> AgentRecord:
    return AgentRecord(
        name=name,
        kind=kind,
        token="tok",
        container_name=("cad-" + name) if kind == AgentKind.local else None,
        host_port=host_port if kind == AgentKind.local else None,
        runtime=runtime,
        endpoint=(f"http://127.0.0.1:{host_port}" if kind == AgentKind.local else "http://remote:8642"),
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

    async def delete(self, name: str) -> None:
        self._agents.pop(name, None)

    async def set_session(self, name: str, session_id: str) -> None:
        self.sessions_set.append((name, session_id))
        rec = self._agents.get(name)
        if rec is not None:
            rec.session_id = session_id


class FakeTransport(Transport):
    """Scripted transport (HTTP-like). `script` is a list of raw ChatEvents (pre-normalize).

    Session behavior: `open()` creates a session (`new_session_id`) when none is set,
    mirroring `HermesApiTransport` create-on-open. During a turn, a `session_id` equal
    to `reject_session` (or None) triggers a transparent recreate.
    Cooperative cancel: when `request_cancel()` is called, the next event is
    `done{cancelled}`.
    """

    kind = TransportKind.http

    def __init__(
        self,
        rec: AgentRecord,
        script: Optional[list[ChatEvent]] = None,
        *,
        new_session_id: str = "sess-new",
        reject_session: Optional[str] = None,
        fail_open: bool = False,
        health_level: HealthLevel = HealthLevel.healthy,
        history_turns=None,
        history_error: Optional[Exception] = None,
    ):
        super().__init__(rec)
        self.script = script if script is not None else [ChatEvent.token_("hi"), ChatEvent.done_()]
        self.new_session_id = new_session_id
        self.reject_session = reject_session
        self.fail_open = fail_open
        self.health_level = health_level
        self.history_turns = history_turns
        self.history_error = history_error
        self.opened = False
        self.closed = False
        self.cancel_sent = False

    async def load_history(self, session_id):  # noqa: ANN001
        if self.history_error is not None:
            raise self.history_error
        return self.history_turns or []

    async def open(self) -> None:
        if self.fail_open:
            self.state = TransportState.broken
            raise RuntimeError("connect refused")
        self.opened = True
        self.state = TransportState.open
        if not self.session_id:
            self.session_id = self.new_session_id

    async def close(self) -> None:
        self.closed = True
        self.state = TransportState.closed

    async def health(self) -> HealthStatus:
        return HealthStatus(self.health_level, shallow=self.health_level == HealthLevel.healthy)

    async def _raw_stream(self, message):  # noqa: ANN001
        if self.session_id is None or self.session_id == self.reject_session:
            self.session_id = self.new_session_id  # transparent recreate
        for ev in self.script:
            if self._cancelled:
                self.cancel_sent = True
                yield ChatEvent.done_("cancelled", code="cancelled")
                return
            yield ev


# --- uniformity property fakes: two wire formats, one transport, same output ---

class _ScriptedWireTransport(Transport):
    """Base for the uniformity fakes: decode a wire script to ChatEvents."""

    kind = TransportKind.http

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

    async def _raw_stream(self, message):  # noqa: ANN001
        self.session_id = self.session_id or "s"
        for frame in self.wire:
            ev = self._decode(frame)
            if ev is not None:
                yield ev


class WireFakeA(_ScriptedWireTransport):
    def _decode(self, frame: dict) -> Optional[ChatEvent]:
        t = frame["type"]
        if t == "delta":
            return ChatEvent.token_(frame["text"])
        if t == "end":
            return ChatEvent.done_("completed")
        if t == "error":
            return ChatEvent.error_(frame.get("message", "err"), code=frame.get("code", "upstream_error"))
        return None


class WireFakeB(_ScriptedWireTransport):
    def _decode(self, frame: dict) -> Optional[ChatEvent]:
        e = frame["event"]
        if e == "output":
            return ChatEvent.token_(frame["chunk"])
        if e == "complete":
            return ChatEvent.done_("completed")
        if e == "failed":
            return ChatEvent.error_(frame.get("reason", "err"), code=frame.get("code", "upstream_error"))
        return None


# Back-compat aliases (older tests referenced these names).
ServeLikeFake = WireFakeA
AcpLikeFake = WireFakeB


# ===================================================================
# U4 — CLI / Daemon / Config test doubles
# ===================================================================
from types import SimpleNamespace  # noqa: E402

from caduceus.common.dto import (  # noqa: E402
    AgentView,
    ConfigResult,
    ConfigSnapshot,
    GatewayConfigView,
    GatewayStatus,
)


class FakeAgentService:
    def __init__(self, agents=None):
        self._agents = {a.name: a for a in (agents or [])}
        self.removed: list[str] = []

    async def create(self, name, wait=True, progress=None, *, model=None, image=None):
        if wait and progress is not None:
            for phase in ("preparing image", "creating container", "configuring agent",
                          "starting agent", "warming up"):
                res = progress(phase)
                if hasattr(res, "__await__"):
                    await res
        rec = make_agent(name=name, lifecycle=(Lifecycle.running if wait else Lifecycle.creating))
        if model:
            rec.model_alias = model
        self._agents[name] = rec
        return rec

    async def register(self, name, endpoint, auth=None):
        rec = make_agent(name=name, kind=AgentKind.remote, lifecycle=Lifecycle.registered)
        rec.endpoint = endpoint
        self._agents[name] = rec
        return rec, "guidance: point your remote hermes at the AI-Gateway"

    async def list(self, deep=False, probe=True):
        return list(self._agents.values())

    async def remove(self, name):
        self.removed.append(name)
        self._agents.pop(name, None)

    async def stop(self, name):
        self._agents[name].lifecycle = Lifecycle.stopped
        return self._agents[name]

    async def start(self, name):
        self._agents[name].lifecycle = Lifecycle.running
        return self._agents[name]


class FakeChatService:
    def __init__(self, script=None, history=None):
        self.script = script if script is not None else [ChatEvent.token_("hi"), ChatEvent.done_()]
        self._history = history or []
        self.cancelled: list[str] = []

    async def chat_stream(self, name, message):
        for ev in self.script:
            yield ev

    def cancel(self, name):
        self.cancelled.append(name)
        return False  # nothing in flight in the fake

    async def history(self, name):
        return list(self._history)


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


def build_fake_services(agents=None, chat_script=None, config_service=None,
                        gateway_config_service=None):
    from caduceus.common.dto import AgentView, GatewayStatus
    from caduceus.common.settings import Settings
    from caduceus.config.gateway_config import GatewayConfigService
    from caduceus import __version__ as VERSION
    from caduceus.daemon.events import EventBus

    reg = FakeRegistry(agents or [])
    agent_service = FakeAgentService(agents or [])

    async def status_snapshot() -> GatewayStatus:
        return GatewayStatus(
            running=True, control_listener="127.0.0.1:9700",
            aigateway_listener="172.17.0.1:9701", upstream="healthy", uptime_s=1.0,
            agent_count=len(reg.list()), version=VERSION,
        )

    async def _dashboard_snapshot() -> dict:
        recs = await agent_service.list(deep=False, probe=False)
        return {
            "type": "snapshot",
            "status": (await status_snapshot()).to_dict(),
            "agents": [AgentView.from_record(r, r.last_health).to_dict() for r in recs],
        }

    return SimpleNamespace(
        settings=SimpleNamespace(control_bind="127.0.0.1:9700", aigateway_bind="172.17.0.1:9701"),
        registry=reg,
        agent_service=agent_service,
        chat_service=FakeChatService(chat_script),
        config_service=config_service or FakeConfigService(),
        gateway_config_service=gateway_config_service or GatewayConfigService(
            Settings(upstream_base_url="http://up:11434/v1", default_model="m"),
            config_path="/nonexistent/config.toml"),
        provisioner=FakeProvisioner(),
        event_bus=EventBus(_dashboard_snapshot),
        status_snapshot=status_snapshot,
    )


class FakeControlAPIClient:
    """Mirrors ControlAPIClient's surface for CLI tests (no HTTP)."""

    def __init__(self, *, up=True, agents=None, chat_script=None,
                 snapshot=None, result=None, raise_error=None, status=None,
                 gateway_config=None, gateway_config_applied=None):
        self.up = up
        self._agents = list(agents or [])
        self._chat = chat_script if chat_script is not None else [ChatEvent.token_("hello"), ChatEvent.done_()]
        self._snapshot = snapshot or ConfigSnapshot(skills=["s1"])
        self._result = result or ConfigResult(applied=["+skills ['s1']"], verified=True)
        self._raise = raise_error
        self._gw_config = gateway_config or GatewayConfigView(
            upstream_base_url="http://up:11434/v1", default_model="m",
            container_runtime="runc", upstream_configured=True, source="live")
        self._gw_applied = gateway_config_applied
        self.set_gateway_calls = []
        self._status = status or GatewayStatus(running=True, pid=123, control_listener="127.0.0.1:9700",
                                               aigateway_listener="172.17.0.1:9701", agent_count=len(agents or []),
                                               version="0.1.0")

    def is_daemon_up(self):
        return self.up

    def status(self):
        return self._status

    def create_agent(self, spec, wait=False):
        if self._raise:
            raise self._raise
        if wait:
            yield {"event": "progress", "phase": "creating container", "detail": ""}
            v = AgentView(name=spec.name, kind="local", lifecycle="running", health="healthy")
            yield {"event": "done", "agent": v.to_dict()}
        else:
            v = AgentView(name=spec.name, kind="local", lifecycle="creating", health="unknown")
            yield {"event": "accepted", "agent": v.to_dict()}

    def register_agent(self, spec):
        return {"agent": AgentView(name=spec.name, kind="remote", lifecycle="registered", health="unknown").to_dict(),
                "guidance": "point your remote hermes at the AI-Gateway"}

    def list_agents(self, deep=False):
        return list(self._agents)

    def remove_agent(self, name):
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

    def get_gateway_config(self):
        return self._gw_config

    def set_gateway_config(self, change):
        if self._raise:
            raise self._raise
        self.set_gateway_calls.append(change)
        if self._gw_applied is not None:
            return self._gw_applied
        return GatewayConfigView(
            upstream_base_url=change.upstream_base_url or self._gw_config.upstream_base_url,
            default_model=change.default_model or self._gw_config.default_model,
            container_runtime=change.container_runtime or self._gw_config.container_runtime,
            upstream_configured=True, source="live")

    def chat(self, name, message):
        for ev in self._chat:
            yield ev

    def logs(self, name, follow=False):
        yield "log line 1"
        yield "log line 2"
