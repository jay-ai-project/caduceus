"""Test doubles for U2 (no real Docker/sbx)."""

from __future__ import annotations

from collections.abc import AsyncIterator

from caduceus.common.models import AgentRecord, HealthLevel, HealthStatus


class FakeProvisioner:
    def __init__(self, fail_on: str | None = None):
        self.sandboxes: dict[str, str] = {}
        self.files: dict[tuple[str, str], str] = {}
        self.env: dict[str, str] = {}
        self.calls: list[str] = []
        self.fail_on = fail_on

    def _maybe_fail(self, method: str) -> None:
        self.calls.append(method)
        if self.fail_on == method:
            raise RuntimeError(f"fake failure in {method}")

    async def create_sandbox(self, sandbox: str, image: str, env: dict[str, str]) -> None:
        self._maybe_fail("create_sandbox")
        self.sandboxes[sandbox] = "running"
        self.env.update(env)

    async def write_file(self, sandbox: str, path: str, content: str) -> None:
        self._maybe_fail("write_file")
        self.files[(sandbox, path)] = content

    async def start_serve(self, sandbox: str, serve_auth: str) -> int:
        self._maybe_fail("start_serve")
        return 40000

    async def stop(self, sandbox: str) -> None:
        self._maybe_fail("stop")
        self.sandboxes[sandbox] = "stopped"

    async def start(self, sandbox: str) -> None:
        self._maybe_fail("start")
        self.sandboxes[sandbox] = "running"

    async def remove(self, sandbox: str) -> None:
        self.sandboxes.pop(sandbox, None)

    async def status(self, sandbox: str) -> str:
        return self.sandboxes.get(sandbox, "missing")

    async def logs(self, sandbox: str, follow: bool = False) -> AsyncIterator[str]:
        yield "fake log"


class FakeImageBuilder:
    def __init__(self) -> None:
        self.built: list[str] = []

    async def image_exists(self, tag: str) -> bool:
        return True

    async def ensure_image(self, tag: str = "caduceus/hermes:0.17.0", hermes_version: str = "0.17.0") -> str:
        self.built.append(tag)
        return tag


class FakeHealthChecker:
    def __init__(self, level: HealthLevel = HealthLevel.healthy):
        self.level = level

    async def check(self, rec: AgentRecord, deep: bool = False) -> HealthStatus:
        return HealthStatus(self.level, shallow=True, deep=(True if deep else None), checked_at="t")
