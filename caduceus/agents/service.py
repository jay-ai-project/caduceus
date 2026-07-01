"""AgentService — agent lifecycle orchestration (FR-A1..A6).

`create` is a saga with compensation (BR-A7). Real Docker lives behind the injected
Provisioner/ImageBuilder; unit tests use fakes.

U8: local agents are Docker containers running the hermes API server. `create` reaches
**chat-ready** (container running + `/health` OK + session warmed); `list` computes state
**live per request** (parallel `/health` + one live `docker ps`), no cache (NFR-U8-P1).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone

from caduceus.agents.hermes_config import api_server_env, remote_setup_guidance, render_hermes_config
from caduceus.agents.names import container_name, validate_name
from caduceus.agents.provisioner import HERMES_CONFIG_PATH
from caduceus.agents.tokens import mint_token
from caduceus.common.errors import ProxyError, invalid_request_error, upstream_error
from caduceus.common.logging import get_logger
from caduceus.common.models import AgentKind, AgentRecord, HealthLevel, HealthStatus, Lifecycle

log = get_logger("caduceus.agents")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ProvisioningJob:
    """In-memory tracker for a background `create` in flight (BR-P4/P12).

    Not persisted — the record's `creating` lifecycle is the durable signal.
    """

    name: str
    task: "asyncio.Future"
    started_at: str


class AgentService:
    def __init__(
        self,
        registry,
        provisioner,
        image_builder,
        health_checker,
        aigateway_url: str,
        image_tag: str = "caduceus/hermes:0.17.0",
        model_alias: str = "default",
        runtime_provider=None,
        transport_closer=None,
        warm_hook=None,
        task_spawner=None,
        ready_timeout: float = 60.0,
    ):
        self.registry = registry
        self.provisioner = provisioner
        self.images = image_builder
        self.health = health_checker
        self.aigateway_url = aigateway_url
        self.image_tag = image_tag
        self.model_alias = model_alias
        # Read live so `gateway config --runtime` hot-applies to the next create (BR-R3).
        self._runtime_provider = runtime_provider or (lambda: "runc")
        # Called with the agent name on stop/remove so a pooled (reused) chat
        # transport is torn down.
        self._transport_closer = transport_closer
        # Called with the agent name after a successful provision to warm the pooled
        # transport (create session, no LLM) so the first chat is instant (BR-P6).
        self._warm_hook = warm_hook
        self._spawn = task_spawner or asyncio.ensure_future
        self._ready_timeout = ready_timeout
        self._jobs: dict[str, ProvisioningJob] = {}

    # ---- create (local, saga) ---------------------------------------
    async def create(self, name: str, wait: bool = True, progress=None) -> AgentRecord:
        """Provision a local agent (FR-U7-2). `wait=False` runs the saga in the
        background: the `creating` record is returned immediately and `agent ls`
        reflects the live `creating → running → healthy | failed` progression."""
        async def _emit(phase: str, detail: str = "") -> None:
            if progress is None:
                return
            res = progress(phase, detail)
            if hasattr(res, "__await__"):
                await res

        name = validate_name(name)
        if self.registry.get(name) is not None or name in self._jobs:
            raise invalid_request_error(f"agent '{name}' already exists")

        token = mint_token()
        cn = container_name(name)
        now = _now()
        rec = AgentRecord(
            name=name, kind=AgentKind.local, token=token,
            container_name=cn, workspace_path=self.provisioner.workspace_for(cn),
            runtime=self._runtime_provider(), model_alias=self.model_alias,
            lifecycle=Lifecycle.creating, created_at=now, updated_at=now,
        )
        await self.registry.upsert(rec)

        if wait:
            await self._provision(rec, token, _emit, background=False)
            return rec

        async def _job() -> None:
            try:
                await self._provision(rec, token, _emit, background=True)
            finally:
                self._jobs.pop(name, None)

        task = self._spawn(_job())
        self._jobs[name] = ProvisioningJob(name=name, task=task, started_at=now)
        return rec

    async def _provision(self, rec: AgentRecord, token: str, emit, background: bool) -> None:
        """The provisioning saga (BR-P5/P6). On failure: compensate, then either
        persist `failed` (background) or unregister + raise (wait)."""
        cn = rec.container_name
        created = False
        try:
            await emit("preparing image")
            tag = await self.images.ensure_image(self.image_tag, progress=emit)
            await emit("creating container")
            env = {**api_server_env(token), "OPENAI_API_KEY": token}
            await self.provisioner.create(cn, tag, env, rec.runtime)
            created = True
            # Write the hermes LLM config into the (created, not-yet-started) container so
            # the API server boots with it present.
            await emit("configuring agent")
            await self.provisioner.put_file(
                cn, HERMES_CONFIG_PATH,
                render_hermes_config(self.aigateway_url, self.model_alias, api_key=token))
            # Docker assigns the published ephemeral host port at START, not create — so
            # start first, then read it back (Build & Test, U8-D3).
            await emit("starting agent")
            await self.provisioner.start(cn)
            hp = await self.provisioner.host_port(cn)
            if not hp:
                raise upstream_error("could not determine published host port for agent")
            rec.host_port = hp
            rec.endpoint = f"http://127.0.0.1:{hp}"
            rec.lifecycle = Lifecycle.running
            rec.updated_at = _now()
            await self.registry.upsert(rec)
            # Wait for the API server to answer /health, then warm a session (no LLM)
            # so the agent is genuinely chat-ready before we report success (BR-P6).
            await emit("waiting for agent")
            await self._await_ready(rec)
            await emit("warming up")
            await self._warm(rec)
            try:
                rec.last_health = await self.health.check(rec, deep=False)
            except Exception as exc:  # noqa: BLE001 — probe error must NOT tear down a good agent
                log.warning("initial health probe for %s failed: %s", rec.name, exc)
                rec.last_health = None
            rec.updated_at = _now()
            await self.registry.upsert(rec)
        except Exception as exc:  # noqa: BLE001 — compensate, then persist-failed or re-raise
            if created:
                await self._safe_remove(cn)
            if background:
                rec.lifecycle = Lifecycle.failed
                rec.last_health = HealthStatus(
                    HealthLevel.unhealthy, shallow=False,
                    detail=f"create failed: {type(exc).__name__}: {exc}", checked_at=_now())
                rec.updated_at = _now()
                await self.registry.upsert(rec)
                log.warning("background provision of %s failed: %s", rec.name, exc)
                return
            await self.registry.delete(rec.name)
            if isinstance(exc, ProxyError):
                raise
            raise upstream_error(f"create failed: {type(exc).__name__}: {exc}") from exc

    async def _await_ready(self, rec: AgentRecord) -> None:
        """Poll `/health` until the agent answers or `ready_timeout` elapses."""
        deadline = asyncio.get_event_loop().time() + self._ready_timeout
        while True:
            try:
                hs = await self.health.check(rec, deep=False)
                if hs.shallow:
                    return
            except Exception as exc:  # noqa: BLE001 — keep polling until deadline
                log.debug("readiness probe for %s: %s", rec.name, exc)
            if asyncio.get_event_loop().time() >= deadline:
                raise upstream_error(f"agent '{rec.name}' did not become ready in "
                                     f"{self._ready_timeout:.0f}s")
            await asyncio.sleep(0.5)

    async def _warm(self, rec: AgentRecord) -> None:
        """Best-effort no-LLM warm-up via the injected hook (BR-P6/P13)."""
        if self._warm_hook is None:
            return
        try:
            res = self._warm_hook(rec.name)
            if hasattr(res, "__await__"):
                await res
        except Exception as exc:  # noqa: BLE001 — non-fatal; re-warms lazily on first chat
            log.info("warm-up for %s failed (will re-warm on first chat): %s", rec.name, exc)

    async def await_jobs(self, timeout: float = 5.0) -> None:
        """Best-effort wait for in-flight provisioning jobs at shutdown (BR-P8)."""
        tasks = [j.task for j in self._jobs.values()]
        if not tasks:
            return
        try:
            await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=timeout)
        except asyncio.TimeoutError:
            log.warning("await_jobs: %d provisioning job(s) still running at shutdown", len(tasks))

    # ---- register (remote) ------------------------------------------
    async def register(self, name: str, endpoint: str, auth: str | None = None) -> tuple[AgentRecord, str]:
        name = validate_name(name)
        if self.registry.get(name) is not None:
            raise invalid_request_error(f"agent '{name}' already exists")
        if not (endpoint or "").strip():
            raise invalid_request_error("endpoint is required to register a remote agent")

        token = mint_token()
        now = _now()
        rec = AgentRecord(
            name=name, kind=AgentKind.remote, token=token, endpoint=endpoint.strip(),
            model_alias=self.model_alias, lifecycle=Lifecycle.registered,
            created_at=now, updated_at=now,
        )
        await self.registry.upsert(rec)
        return rec, remote_setup_guidance(self.aigateway_url, token, self.model_alias)

    # ---- list (real-time, parallel, no cache — NFR-U8-P1) -----------
    async def list(self, deep: bool = False, probe: bool = True) -> list[AgentRecord]:
        """Project agent records.

        `probe=True` (CLI `agent ls`): compute state **live** every call — one live
        `docker ps -a` to reconcile local lifecycle, plus a **parallel** `/health` probe
        per agent. No cache, no cross-call snapshot (the U7 fast-`ls` sweep is gone).

        `probe=False` (Web UI dashboard poll): registry-only projection (lifecycle +
        last cached health), no docker/HTTP calls.
        """
        recs = self.registry.list()
        if not probe:
            return recs

        statuses: dict[str, str] = {}
        status_ok = True
        if any(r.kind == AgentKind.local for r in recs):
            try:
                statuses = await self.provisioner.statuses()
            except Exception as exc:  # noqa: BLE001 — never crash `agent ls` (BR-D3)
                log.warning("docker ps failed: %s", exc)
                status_ok = False

        async def _one(rec: AgentRecord) -> AgentRecord:
            if rec.kind == AgentKind.local:
                if not status_ok:
                    rec.last_health = HealthStatus(
                        HealthLevel.unknown, shallow=False,
                        detail="docker status unavailable", checked_at=_now())
                    return rec
                self._reconcile_lifecycle(rec, statuses)
            try:
                rec.last_health = await self.health.check(rec, deep=deep)
            except Exception as exc:  # noqa: BLE001 — probe error → unknown, never crash
                rec.last_health = HealthStatus(
                    HealthLevel.unknown, shallow=False,
                    detail=f"probe error: {type(exc).__name__}", checked_at=_now())
            return rec

        return list(await asyncio.gather(*(_one(r) for r in recs)))

    async def reconcile_all(self) -> None:
        """Boot-time reconcile/reconnect (BR-O2): set each local agent's lifecycle to its
        live Docker truth and refresh its endpoint. Idempotent + fault-isolated."""
        try:
            statuses = await self.provisioner.statuses()
        except Exception as exc:  # noqa: BLE001 — never block startup
            log.warning("boot reconcile: docker ps failed: %s", exc)
            return
        for rec in self.registry.list():
            if rec.kind != AgentKind.local or rec.lifecycle == Lifecycle.creating:
                continue
            before = rec.lifecycle
            self._reconcile_lifecycle(rec, statuses)
            if rec.lifecycle == Lifecycle.running:
                try:  # refresh published host port / endpoint after a daemon restart
                    hp = await self.provisioner.host_port(rec.container_name)
                    if hp:
                        rec.host_port = hp
                        rec.endpoint = f"http://127.0.0.1:{hp}"
                except Exception as exc:  # noqa: BLE001 — best-effort
                    log.debug("reconcile host_port(%s) failed: %s", rec.name, exc)
            if rec.lifecycle != before or rec.lifecycle == Lifecycle.running:
                rec.updated_at = _now()
                await self.registry.upsert(rec)

    @staticmethod
    def _reconcile_lifecycle(rec: AgentRecord, statuses: dict[str, str]) -> None:
        """Map live `docker ps` state onto lifecycle (BR-P3). `creating` is exempt
        (a provisioning job is in flight)."""
        if rec.lifecycle == Lifecycle.creating:
            return
        st = statuses.get(rec.container_name or "", "missing")
        if st == "running":
            rec.lifecycle = Lifecycle.running
        elif st == "stopped":
            rec.lifecycle = Lifecycle.stopped
        else:  # missing
            rec.lifecycle = Lifecycle.failed

    # ---- remove ------------------------------------------------------
    async def remove(self, name: str, force: bool = False) -> None:
        rec = self.registry.get(name)
        if rec is None:
            raise invalid_request_error(f"no such agent '{name}'")
        await self._close_transport(name)
        if rec.kind == AgentKind.local and rec.container_name:
            await self._safe_remove(rec.container_name)
        await self.registry.delete(name)

    # ---- stop / start (local only) ----------------------------------
    async def stop(self, name: str) -> AgentRecord:
        rec = self._require(name)
        self._reject_remote_lifecycle(rec)
        await self._close_transport(name)
        await self.provisioner.stop(rec.container_name)
        return await self._set_lifecycle(rec, Lifecycle.stopped)

    async def start(self, name: str) -> AgentRecord:
        rec = self._require(name)
        self._reject_remote_lifecycle(rec)
        await self.provisioner.start(rec.container_name)
        return await self._set_lifecycle(rec, Lifecycle.running)

    # ---- helpers -----------------------------------------------------
    def _require(self, name: str) -> AgentRecord:
        rec = self.registry.get(name)
        if rec is None:
            raise invalid_request_error(f"no such agent '{name}'")
        return rec

    @staticmethod
    def _reject_remote_lifecycle(rec: AgentRecord) -> None:
        if rec.kind == AgentKind.remote:
            raise invalid_request_error("stop/start is not supported for remote agents")

    async def _set_lifecycle(self, rec: AgentRecord, lifecycle: Lifecycle) -> AgentRecord:
        rec.lifecycle = lifecycle
        rec.updated_at = _now()
        await self.registry.upsert(rec)
        return rec

    async def _safe_remove(self, container: str) -> None:
        try:
            await self.provisioner.remove(container)
        except Exception as exc:  # noqa: BLE001 — best-effort compensation
            log.warning("compensation: failed to remove container %s: %s", container, exc)

    async def _close_transport(self, name: str) -> None:
        if self._transport_closer is None:
            return
        try:
            await self._transport_closer(name)
        except Exception as exc:  # noqa: BLE001 — best-effort
            log.debug("transport close for %s failed: %s", name, exc)
