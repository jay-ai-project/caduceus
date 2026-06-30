"""Composition root — construct and wire U1/U2/U3 into one set of services (BR-W1/W2).

This is the single place the units are concretely connected: U2's Provisioner/
HealthChecker/AgentService, U3's ChatService/Supervisor (with injected callables),
U1's AI-Gateway (with `token_lookup` bound to the Registry), and U4's ConfigService.

Real sbx/docker/hermes calls only happen when these services are *used* (provisioning,
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
from caduceus.agents.provisioner import SbxProvisioner
from caduceus.agents.registry import Registry
from caduceus.agents.service import AgentService
from caduceus.common.dto import ConfigSnapshot, ReloadStrategy
from caduceus.common.logging import get_logger
from caduceus.common.models import AgentKind, AgentRecord, Lifecycle
from caduceus.common.settings import Settings
from caduceus.config.editor import ConfigEditor
from caduceus.config.service import ConfigService
from caduceus.transport.base import Transport

log = get_logger("caduceus.daemon.wiring")


@dataclass
class Services:
    settings: Settings
    registry: Registry
    provisioner: SbxProvisioner
    agent_service: AgentService
    chat_service: "object"
    config_service: ConfigService
    supervisor: "object"
    aigateway_app: "object"
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

    provisioner = SbxProvisioner(aigateway_url=aigateway_url)
    images = ImageBuilder(context_dir=_repo_images_dir())

    async def _upstream_reachable() -> bool:
        return await _endpoint_reachable(settings.upstream_base_url)

    async def _transport_healthy(rec: AgentRecord) -> Optional[bool]:
        # Local agents are driven over `hermes acp` (stdio) — there is no
        # persistent agent process to probe; spawning a throwaway `hermes acp`
        # every deep-health sweep (30s) just re-runs hermes' provider/model
        # probing (a burst of upstream 404s) for no signal. The running sandbox
        # (shallow check) is the liveness signal; real ACP failures surface on
        # chat (the pooled transport is evicted + respawned). Skip → None.
        if rec.kind == AgentKind.local:
            return None
        # Remote agents have a persistent `hermes serve` endpoint worth probing.
        t = Transport.for_agent(rec)
        try:
            hs = await t.health()
            return hs.level.value == "healthy"
        except Exception:  # noqa: BLE001
            return False
        finally:
            await t.close()

    probes = HealthProbes(
        sandbox_status=provisioner.status,
        endpoint_reachable=_endpoint_reachable,
        upstream_reachable=_upstream_reachable,
        transport_healthy=_transport_healthy,
    )
    health_checker = HealthChecker(probes)

    # U3 chat + supervisor (injected callables)
    from caduceus.transport.chat import ChatService
    from caduceus.transport.supervisor import Supervisor

    chat_service = ChatService(registry, health_check=health_checker.check,
                               transport_factory=Transport.for_agent)

    # AgentService tears down a pooled chat transport on stop/remove (the agent's
    # `hermes acp` process must not outlive its sandbox).
    agent_service = AgentService(registry, provisioner, images, health_checker,
                                 aigateway_url=aigateway_url,
                                 transport_closer=chat_service.close_agent)

    async def _restart(rec: AgentRecord) -> None:
        # ACP transport: there is no serve process/port — "restart" means ensure
        # the sandbox is running again (BR-W2). Chat re-spawns `hermes acp` on demand.
        if rec.sandbox_name is None:
            raise RuntimeError("cannot restart: missing sandbox")
        await provisioner.start(rec.sandbox_name)
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
    )

    # U4 config editing (sandbox I/O via provisioner; real codec → Build & Test)
    config_editor = ConfigEditor(
        read_config=_make_read_config(provisioner),
        write_config=_make_write_config(provisioner),
        reload_agent=_make_reload(provisioner, _restart),
        health_check=health_checker.check,
    )
    config_service = ConfigService(registry, config_editor)

    # U1 AI-Gateway app, token_lookup bound to the Registry (BR-W1)
    from caduceus.aigateway.app import build_aigateway_app
    from caduceus.aigateway.upstream import UpstreamClient

    aigateway_app = build_aigateway_app(settings, registry.token_lookup, UpstreamClient(settings))

    return Services(
        settings=settings, registry=registry, provisioner=provisioner,
        agent_service=agent_service, chat_service=chat_service,
        config_service=config_service, supervisor=supervisor,
        aigateway_app=aigateway_app, advertise_host=advertise,
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


def _repo_images_dir() -> str:
    # images/hermes lives at the repo root next to the package.
    return str(Path(__file__).resolve().parents[2] / "images" / "hermes")


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
