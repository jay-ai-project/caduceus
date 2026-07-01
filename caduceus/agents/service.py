"""AgentService — agent lifecycle orchestration (FR-A1..A6).

`create` is a saga with compensation (BR-A7). Real Docker/sbx live behind the
injected Provisioner/ImageBuilder; unit tests use fakes.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone

from caduceus.agents.hermes_config import remote_setup_guidance, render_hermes_config
from caduceus.agents.names import sandbox_name, validate_name
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
        transport_closer=None,
        warm_hook=None,
        task_spawner=None,
    ):
        self.registry = registry
        self.provisioner = provisioner
        self.images = image_builder
        self.health = health_checker
        self.aigateway_url = aigateway_url
        self.image_tag = image_tag
        self.model_alias = model_alias
        # Called with the agent name on stop/remove so a pooled (reused) chat
        # transport is torn down — its `hermes acp` process would otherwise
        # outlive the sandbox it was bound to.
        self._transport_closer = transport_closer
        # Called with the agent name after a successful provision to warm the
        # pooled ACP transport (initialize + session/new, no LLM) so the first
        # chat is instant (BR-P6). Best-effort; failure is non-fatal.
        self._warm_hook = warm_hook
        # How a background provisioning job is scheduled (injectable for tests).
        self._spawn = task_spawner or asyncio.ensure_future
        self._jobs: dict[str, ProvisioningJob] = {}

    # ---- create (local, saga) ---------------------------------------
    async def create(self, name: str, wait: bool = True, progress=None) -> AgentRecord:
        """Provision a local agent (FR-U7-2).

        Registers the agent as `creating` and, by default (`wait=True`), runs the
        provisioning saga inline and returns the ready record (or raises on failure,
        compensating). With `wait=False` the saga runs in the **background**: the
        `creating` record is returned immediately and `agent ls` reflects the live
        `creating → running → healthy | failed` progression.

        `progress(phase, detail="")` (optional, sync or async) is called at each step.
        """
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
        sb = sandbox_name(name)
        now = _now()
        # No serve port/endpoint: local agents are driven on demand over `hermes acp`
        # (stdio) via the AcpTransport — the running sandbox is the only liveness
        # requirement (BR-A12; ACP transport, 2026-06-30).
        rec = AgentRecord(
            name=name, kind=AgentKind.local, token=token,
            sandbox_name=sb, workspace_path=self.provisioner.workspace_for(sb),
            model_alias=self.model_alias, lifecycle=Lifecycle.creating,
            created_at=now, updated_at=now,
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
        sb = rec.sandbox_name
        created = False
        try:
            await emit("preparing image")
            tag = await self.images.ensure_image(self.image_tag, progress=emit)
            await emit("creating sandbox")
            await self.provisioner.create_sandbox(sb, tag, {"OPENAI_API_KEY": token})
            created = True
            await emit("configuring agent")
            await self.provisioner.write_file(
                sb, HERMES_CONFIG_PATH, render_hermes_config(self.aigateway_url, self.model_alias, api_key=token)
            )
            rec.lifecycle = Lifecycle.running
            rec.updated_at = _now()
            await self.registry.upsert(rec)  # visible/chat-able in `agent ls`
            # Warm the pooled ACP transport (no LLM) so the first chat is instant.
            await emit("warming up")
            await self._warm(rec)
            # Best-effort first health snapshot — a probe error must NOT tear down
            # a successfully-provisioned agent (RESILIENCY; Build & Test 2026-06-30).
            try:
                rec.last_health = await self.health.check(rec, deep=False)
            except Exception as exc:  # noqa: BLE001
                log.warning("initial health probe for %s failed: %s", rec.name, exc)
                rec.last_health = None
            rec.updated_at = _now()
            await self.registry.upsert(rec)
        except Exception as exc:  # noqa: BLE001 — compensate, then persist-failed or re-raise
            if created:
                await self._safe_remove(sb)
            if background:
                rec.lifecycle = Lifecycle.failed
                rec.last_health = HealthStatus(
                    HealthLevel.unhealthy, shallow=False,
                    detail=f"create failed: {type(exc).__name__}: {exc}", checked_at=_now())
                rec.updated_at = _now()
                await self.registry.upsert(rec)
                log.warning("background provision of %s failed: %s", rec.name, exc)
                return
            # wait path: preserve the synchronous saga contract (unregister + raise)
            await self.registry.delete(rec.name)
            if isinstance(exc, ProxyError):
                raise
            raise upstream_error(f"create failed: {type(exc).__name__}: {exc}") from exc

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
            name=name, kind=AgentKind.remote, token=token, endpoint=endpoint,
            model_alias=self.model_alias, lifecycle=Lifecycle.registered,
            created_at=now, updated_at=now,
        )
        await self.registry.upsert(rec)
        return rec, remote_setup_guidance(self.aigateway_url, token, self.model_alias)

    # ---- list (reconcile + health) ----------------------------------
    async def list(self, deep: bool = False, probe: bool = True) -> list[AgentRecord]:
        """Project agent records, optionally probing external state.

        `probe=True` (CLI `agent ls`): capture the sandbox runtime **once** (a single
        `sbx ls`) and reconcile lifecycle **and** compute shallow health for every
        local agent from that one snapshot (BR-P1) — authoritative and O(1) in `sbx`
        calls, not O(N). Deep health (upstream/transport) still runs per-agent when
        `deep=True`, and never spends an LLM completion.

        `probe=False` (Web UI dashboard poll): a cheap, **instant** registry-only
        projection — no `sbx`, no handshake. Lifecycle + cached `last_health` come
        from the registry, kept fresh in the background by the Supervisor sweep and
        by UI-initiated actions that refresh after they run.
        """
        result: list[AgentRecord] = []
        recs = self.registry.list()
        # Only pay the `sbx ls` when there is at least one local agent to reconcile
        # (empty / all-remote listings stay instant).
        snap = None
        if probe and any(r.kind == AgentKind.local for r in recs):
            snap = await self.provisioner.list_statuses()
        for rec in recs:
            if probe:
                if rec.kind == AgentKind.local:
                    if not snap.ok:
                        # Non-authoritative snapshot (BR-P2): keep last-known lifecycle,
                        # mark health unknown, and do NOT re-probe (would re-spawn `sbx`).
                        rec.last_health = HealthStatus(
                            HealthLevel.unknown, shallow=False,
                            detail="sbx status unavailable", checked_at=_now())
                        result.append(rec)
                        continue
                    self._reconcile_lifecycle(rec, snap)
                    rec.last_health = await self.health.check(
                        rec, deep=deep, sandbox_status=snap.get(rec.sandbox_name))
                else:
                    rec.last_health = await self.health.check(rec, deep=deep)
            result.append(rec)
        return result

    async def reconcile_all(self) -> None:
        """Boot-time reconcile/reconnect (BR-P9): set each local agent's lifecycle to
        its runtime truth from one `sbx ls`. Idempotent + fault-isolated."""
        try:
            snap = await self.provisioner.list_statuses()
        except Exception as exc:  # noqa: BLE001 — never block startup
            log.warning("boot reconcile: list_statuses failed: %s", exc)
            return
        if not snap.ok:
            log.info("boot reconcile: sandbox status unavailable; keeping last-known state")
            return
        for rec in self.registry.list():
            if rec.kind != AgentKind.local or rec.lifecycle == Lifecycle.creating:
                continue
            before = rec.lifecycle
            self._reconcile_lifecycle(rec, snap)
            if rec.lifecycle != before:
                rec.updated_at = _now()
                await self.registry.upsert(rec)

    @staticmethod
    def _reconcile_lifecycle(rec: AgentRecord, snap) -> None:
        """Map an authoritative snapshot onto lifecycle (BR-P3). `creating` is exempt
        (a provisioning job is in flight); caller guarantees `snap.ok`."""
        if rec.lifecycle == Lifecycle.creating:
            return
        st = snap.get(rec.sandbox_name)
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
        if rec.kind == AgentKind.local and rec.sandbox_name:
            await self._safe_remove(rec.sandbox_name)
        await self.registry.delete(name)

    # ---- stop / start (local only) ----------------------------------
    async def stop(self, name: str) -> AgentRecord:
        rec = self._require(name)
        self._reject_remote_lifecycle(rec)
        await self._close_transport(name)
        await self.provisioner.stop(rec.sandbox_name)
        return await self._set_lifecycle(rec, Lifecycle.stopped)

    async def start(self, name: str) -> AgentRecord:
        rec = self._require(name)
        self._reject_remote_lifecycle(rec)
        await self.provisioner.start(rec.sandbox_name)
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

    async def _safe_remove(self, sandbox: str) -> None:
        try:
            await self.provisioner.remove(sandbox)
        except Exception as exc:  # noqa: BLE001 — best-effort compensation
            log.warning("compensation: failed to remove sandbox %s: %s", sandbox, exc)

    async def _close_transport(self, name: str) -> None:
        if self._transport_closer is None:
            return
        try:
            await self._transport_closer(name)
        except Exception as exc:  # noqa: BLE001 — best-effort
            log.debug("transport close for %s failed: %s", name, exc)
