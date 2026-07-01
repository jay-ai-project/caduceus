"""HealthChecker — shallow/deep agent health (FR-L2, RESILIENCY-06).

Probes are injected (assembled by U4 from the Provisioner, a socket reachability
check, the U1 upstream check, and the U3 transport health probe) so U2 stays
decoupled and fully unit-testable. Deep checks never spend an LLM completion.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from caduceus.common.models import AgentRecord, AgentKind, HealthLevel, HealthStatus


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class HealthProbes:
    sandbox_status: Callable[[str], Awaitable[str]]          # -> running|stopped|missing
    endpoint_reachable: Callable[[str], Awaitable[bool]]
    upstream_reachable: Callable[[], Awaitable[bool]]
    transport_healthy: Optional[Callable[[AgentRecord], Awaitable[Optional[bool]]]] = None


class HealthChecker:
    def __init__(self, probes: HealthProbes):
        self.p = probes

    async def check(self, rec: AgentRecord, deep: bool = False,
                    sandbox_status: Optional[str] = None) -> HealthStatus:
        # ---- shallow ----
        # Local agents have no network endpoint (driven over `hermes acp` stdio);
        # a running sandbox is the shallow-liveness signal. Remote agents are
        # reachability-probed on their registered endpoint. `sandbox_status`, when
        # supplied by a batched caller (AgentService.list, one `sbx ls`), avoids a
        # redundant per-agent probe (BR-P1).
        if rec.kind == AgentKind.local:
            if sandbox_status is None and rec.sandbox_name is not None:
                sandbox_status = await self.p.sandbox_status(rec.sandbox_name)
            shallow = rec.sandbox_name is not None and sandbox_status == "running"
            unreachable_detail = "sandbox not running"
        else:
            shallow = bool(rec.endpoint) and await self.p.endpoint_reachable(rec.endpoint)
            unreachable_detail = "endpoint unreachable"

        if not shallow:
            return HealthStatus(HealthLevel.unhealthy, shallow=False, deep=None,
                                detail=unreachable_detail, checked_at=_now())
        if not deep:
            return HealthStatus(HealthLevel.healthy, shallow=True, deep=None, checked_at=_now())

        # ---- deep (no LLM spend) ----
        upstream_ok = await self.p.upstream_reachable()
        transport = None
        if self.p.transport_healthy is not None:
            transport = await self.p.transport_healthy(rec)

        if not upstream_ok:
            return HealthStatus(HealthLevel.degraded, shallow=True, deep=False,
                                detail="caduceus upstream unreachable", checked_at=_now())
        if transport is False:
            return HealthStatus(HealthLevel.unhealthy, shallow=True, deep=False,
                                detail="hermes transport unhealthy", checked_at=_now())
        return HealthStatus(HealthLevel.healthy, shallow=True, deep=True, checked_at=_now())
