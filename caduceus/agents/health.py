"""HealthChecker — shallow/deep agent health (FR-L2, RESILIENCY-06).

U8: every agent (local Docker container or remote) exposes a hermes API server, so the
**shallow** signal is unified: `GET /health` reachable (probed with the agent's bearer;
never spends an LLM completion). Deep additionally checks the caduceus upstream. Probes
are injected so the checker stays decoupled and unit-testable.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from caduceus.common.models import AgentRecord, HealthLevel, HealthStatus


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class HealthProbes:
    #: shallow liveness: is the agent's hermes API server answering `/health`?
    agent_reachable: Callable[[AgentRecord], Awaitable[bool]]
    #: deep: is the caduceus AI-Gateway upstream reachable?
    upstream_reachable: Callable[[], Awaitable[bool]]


class HealthChecker:
    def __init__(self, probes: HealthProbes):
        self.p = probes

    async def check(self, rec: AgentRecord, deep: bool = False) -> HealthStatus:
        # ---- shallow: HTTP /health (no LLM spend), same for local & remote ----
        shallow = bool(rec.endpoint) and await self.p.agent_reachable(rec)
        if not shallow:
            detail = "agent api unreachable" if rec.endpoint else "no endpoint"
            return HealthStatus(HealthLevel.unhealthy, shallow=False, deep=None,
                                detail=detail, checked_at=_now())
        if not deep:
            return HealthStatus(HealthLevel.healthy, shallow=True, deep=None, checked_at=_now())

        # ---- deep (no LLM spend) ----
        upstream_ok = await self.p.upstream_reachable()
        if not upstream_ok:
            return HealthStatus(HealthLevel.degraded, shallow=True, deep=False,
                                detail="caduceus upstream unreachable", checked_at=_now())
        return HealthStatus(HealthLevel.healthy, shallow=True, deep=True, checked_at=_now())
