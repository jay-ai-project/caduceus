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

    async def check(self, rec: AgentRecord, deep: bool = False) -> HealthStatus:
        # ---- shallow ----
        if rec.kind == AgentKind.local:
            running = rec.sandbox_name is not None and (await self.p.sandbox_status(rec.sandbox_name)) == "running"
            shallow = running and bool(rec.endpoint) and await self.p.endpoint_reachable(rec.endpoint)
        else:
            shallow = bool(rec.endpoint) and await self.p.endpoint_reachable(rec.endpoint)

        if not shallow:
            return HealthStatus(HealthLevel.unhealthy, shallow=False, deep=None,
                                detail="endpoint unreachable", checked_at=_now())
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
