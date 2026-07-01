"""Provisioner — all sbx/docker interactions for local agents (BR-A12).

`Provisioner` is the interface (Protocol) consumed by AgentService; `SbxProvisioner`
is the real implementation over the `sbx` CLI. Unit tests use a FakeProvisioner;
the real impl is exercised in Build & Test integration.

Implementation note: exact `sbx` sub-commands and the in-sandbox hermes config
path were validated in Build & Test (2026-06-30). Local agents are driven over
`hermes acp` (stdio) by the AcpTransport, so the provisioner only manages sandbox
lifecycle + config I/O — there is no `hermes serve` start / port publishing.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from caduceus.common.errors import upstream_error
from caduceus.common.logging import get_logger

log = get_logger("caduceus.provisioner")

# In-sandbox hermes config path (HERMES_HOME); validated in Build & Test.
HERMES_CONFIG_PATH = "/root/.hermes/config.yaml"


@dataclass
class SandboxSnapshot:
    """A single point-in-time projection of the sandbox runtime (one `sbx ls`).

    `ok=False` means the underlying `sbx ls` errored/timed out — the snapshot is
    **non-authoritative** and callers MUST NOT downgrade lifecycle from it (BR-P2).
    A sandbox absent from an *authoritative* snapshot is `missing`.
    """

    statuses: dict[str, str] = field(default_factory=dict)  # name -> "running"|"stopped"
    ok: bool = True

    def get(self, sandbox: str | None) -> str:
        if not sandbox:
            return "missing"
        return self.statuses.get(sandbox, "missing")


def _parse_sbx_ls(out: bytes) -> dict[str, str]:
    """Parse `sbx ls --json` → {name: "running"|"stopped"} (Build & Test, Finding H)."""
    import json as _json

    try:
        data = _json.loads(out or "{}")
    except (ValueError, TypeError):
        return {}
    items = data.get("sandboxes", []) if isinstance(data, dict) else data
    result: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("Name")
        if not name:
            continue
        state = (item.get("status") or item.get("State") or "").lower()
        result[name] = "running" if "run" in state else "stopped"
    return result


class Provisioner(Protocol):
    def workspace_for(self, sandbox: str) -> str: ...
    async def create_sandbox(self, sandbox: str, image: str, env: dict[str, str]) -> None: ...
    async def write_file(self, sandbox: str, path: str, content: str) -> None: ...
    async def stop(self, sandbox: str) -> None: ...
    async def start(self, sandbox: str) -> None: ...
    async def remove(self, sandbox: str) -> None: ...
    async def status(self, sandbox: str) -> str: ...  # running | stopped | missing
    async def list_statuses(self) -> SandboxSnapshot: ...  # one `sbx ls` for all sandboxes
    def logs(self, sandbox: str, follow: bool = False) -> AsyncIterator[str]: ...


class SbxProvisioner:
    """Real provisioner over the `sbx` CLI."""

    def __init__(self, sbx_bin: str = "sbx", aigateway_url: str = "", default_timeout: float = 30.0,
                 workspace_root: str = "~/.caduceus/agents"):
        self._sbx = sbx_bin
        self._aigateway_url = aigateway_url
        self._timeout = default_timeout
        # `sbx create shell` requires a host workspace PATH (mounted in-sandbox).
        # caduceus agents don't share the host repo, so each gets a dedicated dir.
        self._workspace_root = Path(workspace_root).expanduser()

    async def _run(self, *args: str, timeout: float | None = None, stdin: bytes | None = None) -> tuple[int, bytes, bytes]:
        proc = await asyncio.create_subprocess_exec(
            self._sbx, *args,
            stdin=asyncio.subprocess.PIPE if stdin is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(input=stdin), timeout=timeout or self._timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise upstream_error(f"sbx {args[0]} timed out", status=504)
        return proc.returncode, out, err

    async def _check(self, *args: str, timeout: float | None = None, stdin: bytes | None = None) -> bytes:
        rc, out, err = await self._run(*args, timeout=timeout, stdin=stdin)
        if rc != 0:
            raise upstream_error(f"sbx {args[0]} failed (rc={rc}): {err.decode('utf-8', 'replace')[:300]}")
        return out

    def workspace_for(self, sandbox: str) -> str:
        """Host path bind-mounted into the sandbox (mounted at the same path inside)."""
        return str(self._workspace_root / sandbox / "workspace")

    async def create_sandbox(self, sandbox: str, image: str, env: dict[str, str]) -> None:
        workspace = Path(self.workspace_for(sandbox))
        workspace.mkdir(parents=True, exist_ok=True)
        await self._check("create", "shell", str(workspace), "-t", image, "--name", sandbox, "-q", timeout=300.0)
        # Apply env inside the sandbox (kept out of argv where possible via the agent config/env file).
        for key, value in env.items():
            await self._check(
                "exec", sandbox, "sh", "-lc",
                f'mkdir -p "$(dirname ~/.caduceus_env)"; printf "export %s=%s\\n" {_sh(key)} {_sh(value)} >> ~/.caduceus_env',
            )

    async def write_file(self, sandbox: str, path: str, content: str) -> None:
        # Write via stdin to avoid putting content on the command line; the
        # config carries the agent's bearer token, so restrict perms to 600.
        await self._check(
            "exec", "-i", sandbox, "sh", "-lc",
            f'mkdir -p "$(dirname {_sh(path)})" && cat > {_sh(path)} && chmod 600 {_sh(path)}',
            stdin=content.encode("utf-8"),
        )

    async def stop(self, sandbox: str) -> None:
        await self._check("stop", sandbox, timeout=60.0)

    async def start(self, sandbox: str) -> None:
        # sbx has no `start` verb; `sbx exec` transparently starts a stopped
        # sandbox (Build & Test, Finding J). A no-op command suffices.
        await self._check("exec", sandbox, "sh", "-lc", "true", timeout=60.0)

    async def remove(self, sandbox: str) -> None:
        await self._check("rm", "-f", sandbox, timeout=60.0)

    async def list_statuses(self) -> SandboxSnapshot:
        """One `sbx ls --json` → snapshot of every sandbox (BR-P1). Any error
        (non-zero rc, timeout, or other failure) → `ok=False` (non-authoritative;
        callers must not downgrade lifecycle, BR-P2) — never raises to `agent ls`."""
        try:
            rc, out, _ = await self._run("ls", "--json", timeout=15.0)
        except Exception as exc:  # noqa: BLE001 — timeout/spawn error → non-authoritative
            log.warning("sbx ls failed: %s", exc)
            return SandboxSnapshot({}, ok=False)
        if rc != 0:
            return SandboxSnapshot({}, ok=False)
        return SandboxSnapshot(_parse_sbx_ls(out), ok=True)

    async def status(self, sandbox: str) -> str:
        snap = await self.list_statuses()
        return snap.get(sandbox) if snap.ok else "missing"

    async def logs(self, sandbox: str, follow: bool = False) -> AsyncIterator[str]:
        args = ["exec", sandbox, "sh", "-lc", "hermes logs" + (" -f" if follow else "")]
        proc = await asyncio.create_subprocess_exec(
            self._sbx, *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        assert proc.stdout is not None
        async for line in proc.stdout:
            yield line.decode("utf-8", "replace").rstrip("\n")


def _sh(value: str) -> str:
    """Single-quote a value for safe embedding in `sh -lc`."""
    return "'" + str(value).replace("'", "'\\''") + "'"
