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
from pathlib import Path
from typing import Protocol

from caduceus.common.errors import upstream_error
from caduceus.common.logging import get_logger

log = get_logger("caduceus.provisioner")

# In-sandbox hermes config path (HERMES_HOME); validated in Build & Test.
HERMES_CONFIG_PATH = "/root/.hermes/config.yaml"


class Provisioner(Protocol):
    async def create_sandbox(self, sandbox: str, image: str, env: dict[str, str]) -> None: ...
    async def write_file(self, sandbox: str, path: str, content: str) -> None: ...
    async def stop(self, sandbox: str) -> None: ...
    async def start(self, sandbox: str) -> None: ...
    async def remove(self, sandbox: str) -> None: ...
    async def status(self, sandbox: str) -> str: ...  # running | stopped | missing
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

    async def create_sandbox(self, sandbox: str, image: str, env: dict[str, str]) -> None:
        workspace = self._workspace_root / sandbox / "workspace"
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

    async def status(self, sandbox: str) -> str:
        import json as _json
        rc, out, _ = await self._run("ls", "--json", timeout=15.0)
        if rc != 0:
            return "missing"
        try:
            data = _json.loads(out or "{}")
        except (ValueError, TypeError):
            return "missing"
        # `sbx ls --json` → {"sandboxes": [{"name","status",...}]} (Build & Test, Finding H)
        items = data.get("sandboxes", []) if isinstance(data, dict) else data
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("name") == sandbox or item.get("Name") == sandbox:
                state = (item.get("status") or item.get("State") or "").lower()
                return "running" if "run" in state else "stopped"
        return "missing"

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
