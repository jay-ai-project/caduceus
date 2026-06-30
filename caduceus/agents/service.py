"""AgentService — agent lifecycle orchestration (FR-A1..A6).

`create` is a saga with compensation (BR-A7). Real Docker/sbx live behind the
injected Provisioner/ImageBuilder; unit tests use fakes.
"""

from __future__ import annotations

from datetime import datetime, timezone

from caduceus.agents.hermes_config import remote_setup_guidance, render_hermes_config
from caduceus.agents.names import sandbox_name, validate_name
from caduceus.agents.provisioner import HERMES_CONFIG_PATH
from caduceus.agents.tokens import mint_token
from caduceus.common.errors import ProxyError, invalid_request_error, upstream_error
from caduceus.common.logging import get_logger
from caduceus.common.models import AgentKind, AgentRecord, Lifecycle

log = get_logger("caduceus.agents")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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

    # ---- create (local, saga) ---------------------------------------
    async def create(self, name: str) -> AgentRecord:
        name = validate_name(name)
        if self.registry.get(name) is not None:
            raise invalid_request_error(f"agent '{name}' already exists")

        token = mint_token()
        sb = sandbox_name(name)
        tag = await self.images.ensure_image(self.image_tag)

        created = False
        try:
            await self.provisioner.create_sandbox(sb, tag, {"OPENAI_API_KEY": token})
            created = True
            await self.provisioner.write_file(
                sb, HERMES_CONFIG_PATH, render_hermes_config(self.aigateway_url, self.model_alias, api_key=token)
            )
            # No serve port/endpoint: local agents are driven on demand over
            # `hermes acp` (stdio) via the AcpTransport — the running sandbox is
            # the only liveness requirement (BR-A12; ACP transport, 2026-06-30).
            now = _now()
            rec = AgentRecord(
                name=name, kind=AgentKind.local, token=token,
                sandbox_name=sb, workspace_path=self.provisioner.workspace_for(sb),
                model_alias=self.model_alias, lifecycle=Lifecycle.running,
                created_at=now, updated_at=now,
            )
            await self.registry.upsert(rec)
            # Best-effort first health snapshot — a probe error must NOT tear down
            # a successfully-provisioned agent (RESILIENCY; Build & Test 2026-06-30).
            try:
                rec.last_health = await self.health.check(rec, deep=False)
            except Exception as exc:  # noqa: BLE001
                log.warning("initial health probe for %s failed: %s", name, exc)
                rec.last_health = None
            rec.updated_at = _now()
            await self.registry.upsert(rec)
            return rec
        except Exception as exc:  # noqa: BLE001 — compensate then re-raise
            if created:
                await self._safe_remove(sb)
            if isinstance(exc, ProxyError):
                raise
            raise upstream_error(f"create failed: {type(exc).__name__}: {exc}") from exc

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
    async def list(self, deep: bool = False) -> list[AgentRecord]:
        result: list[AgentRecord] = []
        for rec in self.registry.list():
            if rec.kind == AgentKind.local and rec.sandbox_name:
                status = await self.provisioner.status(rec.sandbox_name)
                if status == "missing":
                    rec.lifecycle = Lifecycle.failed
                elif status == "stopped":
                    rec.lifecycle = Lifecycle.stopped
                elif status == "running" and rec.lifecycle == Lifecycle.stopped:
                    rec.lifecycle = Lifecycle.running
            rec.last_health = await self.health.check(rec, deep=deep)
            result.append(rec)
        return result

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
