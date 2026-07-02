"""Composition root — construct and wire U1/U2/U3 into one set of services (BR-W1/W2).

This is the single place the units are concretely connected: U2's Provisioner/
HealthChecker/AgentService, U3's ChatService/Supervisor (with injected callables),
U1's AI-Gateway (with `token_lookup` bound to the Registry), and U4's ConfigService.

Real docker/hermes calls only happen when these services are *used* (provisioning,
chat, sweep) — construction here is side-effect-free, so wiring is importable/testable.
"""

from __future__ import annotations

import asyncio
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from caduceus.agents.health import HealthChecker, HealthProbes
from caduceus.agents.images import ImageBuilder
from caduceus.agents.provisioner import DockerProvisioner
from caduceus.agents.registry import Registry
from caduceus.agents.service import AgentService
from caduceus.common.dto import AgentView, ConfigSnapshot, GatewayStatus, ReloadStrategy
from caduceus.common.logging import get_logger
from caduceus.common.models import AgentKind, AgentRecord, HealthLevel, Lifecycle
from caduceus.common.settings import Settings
from caduceus.config.editor import ConfigEditor
from caduceus.config.service import ConfigService
from caduceus.transport.base import Transport

log = get_logger("caduceus.daemon.wiring")


@dataclass
class Services:
    settings: Settings
    registry: Registry
    provisioner: DockerProvisioner
    agent_service: AgentService
    chat_service: "object"
    config_service: ConfigService
    gateway_config_service: "object"
    supervisor: "object"
    aigateway_app: "object"
    event_bus: "object"
    advertise_host: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _endpoint_reachable(endpoint: Optional[str], timeout: float = 3.0) -> bool:
    if not endpoint:
        return False
    host, port = _host_port(endpoint)
    if port is None:
        return False
    try:
        fut = asyncio.open_connection(host, port)
        reader, writer = await asyncio.wait_for(fut, timeout=timeout)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass
        return True
    except Exception:  # noqa: BLE001
        return False


def _host_port(endpoint: str) -> tuple[str, Optional[int]]:
    e = endpoint.split("://", 1)[-1]
    e = e.split("/", 1)[0]
    if ":" in e:
        host, _, p = e.rpartition(":")
        try:
            return host or "127.0.0.1", int(p)
        except ValueError:
            return e, None
    return e, None


def build_services(settings: Settings, state_dir: "str | Path" = "~/.caduceus") -> Services:
    sd = Path(state_dir).expanduser()
    advertise = settings.aigateway_advertise_host or _detect_bridge_gateway() or "172.17.0.1"
    aigw_port = settings.aigateway_bind.rsplit(":", 1)[-1]
    aigateway_url = f"http://{advertise}:{aigw_port}/v1"

    registry = Registry(sd / "state.json")
    registry.load()

    provisioner = DockerProvisioner()
    images = ImageBuilder()

    async def _upstream_reachable() -> bool:
        return await _endpoint_reachable(settings.upstream_base_url)

    async def _agent_reachable(rec: AgentRecord) -> bool:
        # Shallow liveness for both local & remote: the hermes API server answers
        # `GET /health` (no LLM spend). Uses a throwaway transport (own HTTP client).
        t = Transport.for_agent(rec)
        try:
            hs = await t.health()
            return hs.level == HealthLevel.healthy
        except Exception:  # noqa: BLE001
            return False
        finally:
            await t.close()

    probes = HealthProbes(
        agent_reachable=_agent_reachable,
        upstream_reachable=_upstream_reachable,
    )
    health_checker = HealthChecker(probes)

    # U3 chat + supervisor (injected callables)
    from caduceus.transport.chat import ChatService
    from caduceus.transport.supervisor import Supervisor

    chat_service = ChatService(registry, health_check=health_checker.check,
                               transport_factory=Transport.for_agent)

    # AgentService tears down a pooled chat transport on stop/remove, and warms the
    # pooled transport after a successful provision so the first chat is instant (BR-P6).
    agent_service = AgentService(registry, provisioner, images, health_checker,
                                 aigateway_url=aigateway_url,
                                 runtime_provider=lambda: settings.container_runtime,
                                 transport_closer=chat_service.close_agent,
                                 warm_hook=chat_service.warm)

    # U9: event bus powering the Web UI `/api/events` push stream. The snapshot is
    # the exact data the old dashboard polls returned (`/status` + `/agents?probe=false`),
    # so switching the UI from polling to push is behaviour-preserving.
    from caduceus.daemon.control_api import VERSION
    from caduceus.daemon.events import EventBus

    async def _dashboard_snapshot() -> dict:
        recs = await agent_service.list(deep=False, probe=False)
        status = GatewayStatus(
            running=True, control_listener=settings.control_bind,
            aigateway_listener=settings.aigateway_bind,
            agent_count=len(registry.list()), version=VERSION,
        )
        return {
            "type": "snapshot",
            "status": status.to_dict(),
            "agents": [AgentView.from_record(r, r.last_health).to_dict() for r in recs],
        }

    event_bus = EventBus(_dashboard_snapshot)
    registry.set_on_change(event_bus.notify)  # broadcast on create/start/stop/remove/session

    async def _restart(rec: AgentRecord) -> None:
        # "restart" = ensure the container is running again (BR-W2/BR-O3). The hermes
        # API server boots with it; chat reconnects over HTTP.
        if rec.container_name is None:
            raise RuntimeError("cannot restart: missing container")
        await provisioner.start(rec.container_name)
        rec.lifecycle = Lifecycle.running
        rec.updated_at = _now()
        await registry.upsert(rec)

    async def _mark_failed(name: str) -> None:
        rec = registry.get(name)
        if rec is not None:
            rec.lifecycle = Lifecycle.failed
            rec.updated_at = _now()
            await registry.upsert(rec)

    supervisor = Supervisor(
        list_agents=lambda: [r for r in registry.list() if r.kind == AgentKind.local],
        health_check=health_checker.check,
        restart=_restart,
        mark_failed=_mark_failed,
        on_change=event_bus.notify,  # broadcast freshly-probed health after each sweep
    )

    # U4 config editing (sandbox I/O via provisioner; real codec → Build & Test)
    config_editor = ConfigEditor(
        read_config=_make_read_config(provisioner),
        write_config=_make_write_config(provisioner),
        reload_agent=_make_reload(provisioner, _restart),
        health_check=health_checker.check,
    )
    config_service = ConfigService(registry, config_editor)

    # U6 gateway upstream config: view + persist (config.toml) + live hot-apply.
    # Shares the exact `settings` object the AI-Gateway reads, so `apply` takes
    # effect without a restart (BR-GC5).
    from caduceus.config.gateway_config import GatewayConfigService

    gateway_config_service = GatewayConfigService(settings, config_path=sd / "config.toml")

    # U1 AI-Gateway app, token_lookup bound to the Registry (BR-W1)
    from caduceus.aigateway.app import build_aigateway_app
    from caduceus.aigateway.upstream import UpstreamClient

    aigateway_app = build_aigateway_app(settings, registry.token_lookup, UpstreamClient(settings))

    return Services(
        settings=settings, registry=registry, provisioner=provisioner,
        agent_service=agent_service, chat_service=chat_service,
        config_service=config_service, gateway_config_service=gateway_config_service,
        supervisor=supervisor, aigateway_app=aigateway_app, event_bus=event_bus,
        advertise_host=advertise,
    )


# ---- config sandbox I/O (real hermes paths/reload → Build & Test) ----
HERMES_DIR = "/root/.hermes"


def _make_read_config(provisioner):
    async def _read(rec: AgentRecord) -> ConfigSnapshot:
        # Build & Test: read skills/tools/soul/core from the sandbox hermes config.
        # Placeholder structure kept minimal until the on-disk format is confirmed.
        return ConfigSnapshot()
    return _read


def _make_write_config(provisioner):
    async def _write(rec: AgentRecord, snapshot: ConfigSnapshot) -> None:
        # Build & Test: serialize snapshot into the sandbox hermes config files.
        return None
    return _write


def _make_reload(provisioner, restart):
    async def _reload(rec: AgentRecord, strategy: ReloadStrategy) -> None:
        # Q2: hot_reload (default) signals hermes to reload; restart_serve reuses restart.
        if strategy == ReloadStrategy.restart_serve:
            await restart(rec)
        # else hot_reload: Build & Test confirms the reload signal mechanism.
        return None
    return _reload


def _detect_bridge_gateway() -> Optional[str]:
    """Best-effort docker bridge gateway IP (e.g. 172.17.0.1)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        # not the bridge per se, but a reachable host IP; the explicit setting wins.
        return None if ip.startswith("127.") else None
    except Exception:  # noqa: BLE001
        return None
