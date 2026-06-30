"""ConfigEditor — apply config edits to a local agent (FR-E1/E3, Q2/Q4).

The logic (reduce → write → reload → read-back verify) is here and fully
unit-testable; the actual sandbox I/O and hermes reload are **injected** callables
(`read_config`/`write_config`/`reload_agent`), wired to the U2 Provisioner in
`daemon/wiring.py` and validated in Build & Test.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Optional

from caduceus.common.dto import (
    ConfigChange,
    ConfigResult,
    ConfigSnapshot,
    ReloadStrategy,
    apply_change,
    resolve_strategy,
    snapshot_satisfies,
)
from caduceus.common.logging import get_logger
from caduceus.common.models import AgentRecord, HealthLevel, HealthStatus

log = get_logger("caduceus.config")

ReadConfig = Callable[[AgentRecord], Awaitable[ConfigSnapshot]]
WriteConfig = Callable[[AgentRecord, ConfigSnapshot], Awaitable[None]]
ReloadAgent = Callable[[AgentRecord, ReloadStrategy], Awaitable[None]]
HealthCheck = Callable[[AgentRecord, bool], Awaitable[HealthStatus]]


class ReadOnlyError(Exception):
    """Raised when a mutation is attempted on a remote (read-only) agent."""


class ConfigEditor:
    def __init__(
        self,
        read_config: ReadConfig,
        write_config: WriteConfig,
        reload_agent: ReloadAgent,
        health_check: Optional[HealthCheck] = None,
    ):
        self._read = read_config
        self._write = write_config
        self._reload = reload_agent
        self._health = health_check

    async def read(self, rec: AgentRecord) -> ConfigSnapshot:
        return await self._read(rec)

    async def apply(self, rec: AgentRecord, change: ConfigChange) -> ConfigResult:
        # soul source conflict (BR-E2): both inline and file is ambiguous.
        if change.soul is not None and change.soul_file is not None:
            return ConfigResult(detail="provide either --soul or --soul-file, not both",
                                verified=False)
        if change.is_empty():
            return ConfigResult(detail="no changes requested", verified=True, reloaded=False)

        current = await self._read(rec)
        updated = apply_change(current, change)
        await self._write(rec, updated)

        strategy = resolve_strategy(change.affected_kinds())
        await self._reload(rec, strategy)

        # read-back + health verification (Q4 / BR-E6)
        readback = await self._read(rec)
        verified = snapshot_satisfies(readback, change)
        health = HealthLevel.unknown
        if self._health is not None:
            hs = await self._health(rec, False)
            health = hs.level

        result = ConfigResult(
            applied=_describe(change),
            strategy=strategy.value,
            reloaded=True,
            verified=verified,
            health=health.value,
            detail="" if verified else "read-back did not reflect all requested changes",
        )
        log.info("config applied to %s: strategy=%s verified=%s", rec.name, strategy.value, verified)
        return result


def _describe(change: ConfigChange) -> list[str]:
    out: list[str] = []
    if change.add_skills:
        out.append(f"+skills {change.add_skills}")
    if change.remove_skills:
        out.append(f"-skills {change.remove_skills}")
    if change.enable_tools:
        out.append(f"+tools {change.enable_tools}")
    if change.disable_tools:
        out.append(f"-tools {change.disable_tools}")
    if change.soul is not None:
        out.append("soul updated")
    if change.set_core:
        out.append(f"core {sorted(change.set_core)}")
    return out
