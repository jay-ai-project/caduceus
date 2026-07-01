"""Provisioner — all Docker interactions for local agents (U8; was sbx-based).

`Provisioner` is the interface (Protocol) consumed by AgentService; `DockerProvisioner`
is the real implementation over the `docker` CLI. Unit tests use a FakeProvisioner; the
real impl is exercised in Build & Test integration.

U8: local agents run as **plain Docker containers** built from the **official**
`nousresearch/hermes-agent` image, running the hermes API server (`gateway run`, port
8642). caduceus reaches them over HTTP on a published host **loopback** port. The
official image keeps all state under **`/opt/data`** (HERMES_HOME) and its init chowns
that dir to its internal `hermes` user, so caduceus writes the LLM config into the
host-mounted workspace (`<ws>/config.yaml`) before start, resetting ownership first when a
prior run left the dir chowned. Status is queried **live** (no cache). Optional gVisor
runtime via `--runtime runsc` (fail-fast if configured but unavailable).
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Optional, Protocol

from caduceus.common.errors import upstream_error
from caduceus.common.logging import get_logger

log = get_logger("caduceus.provisioner")

#: The agent's host workspace is bind-mounted here — the official image's HERMES_HOME.
CONTAINER_DATA = "/opt/data"
#: hermes config path relative to the workspace (== /opt/data/config.yaml in-container).
HERMES_CONFIG_REL = "config.yaml"
#: The API-server port hermes listens on inside the container.
CONTAINER_API_PORT = 8642
#: Command passed to the official image's entrypoint to run the API server.
GATEWAY_CMD = ("gateway", "run")


class Provisioner(Protocol):
    def workspace_for(self, container: str) -> str: ...
    async def create(self, container: str, image: str, env: dict[str, str], runtime: str) -> None: ...
    async def host_port(self, container: str) -> Optional[int]: ...
    async def write_config(self, container: str, content: str) -> None: ...
    async def stop(self, container: str) -> None: ...
    async def start(self, container: str) -> None: ...
    async def remove(self, container: str) -> None: ...
    async def status(self, container: str) -> str: ...  # running | stopped | missing
    async def statuses(self) -> dict[str, str]: ...      # live `docker ps -a`, one call
    def logs(self, container: str, follow: bool = False) -> AsyncIterator[str]: ...


class RuntimeUnavailable(Exception):
    """Configured container runtime (e.g. runsc) is not registered with Docker (BR-R2)."""


class DockerProvisioner:
    """Real provisioner over the `docker` CLI."""

    def __init__(self, docker_bin: str = "docker", default_timeout: float = 30.0,
                 workspace_root: str = "~/.caduceus/agents"):
        self._docker = docker_bin
        self._timeout = default_timeout
        self._workspace_root = Path(workspace_root).expanduser()

    async def _run(self, *args: str, timeout: float | None = None,
                   stdin: bytes | None = None) -> tuple[int, bytes, bytes]:
        proc = await asyncio.create_subprocess_exec(
            self._docker, *args,
            stdin=asyncio.subprocess.PIPE if stdin is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(input=stdin),
                                              timeout=timeout or self._timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise upstream_error(f"docker {args[0]} timed out", status=504)
        return proc.returncode, out, err

    async def _check(self, *args: str, timeout: float | None = None,
                     stdin: bytes | None = None) -> bytes:
        rc, out, err = await self._run(*args, timeout=timeout, stdin=stdin)
        if rc != 0:
            raise upstream_error(f"docker {args[0]} failed (rc={rc}): "
                                 f"{err.decode('utf-8', 'replace')[:300]}")
        return out

    def workspace_for(self, container: str) -> str:
        """Host path bind-mounted at /opt/data (HERMES_HOME) inside the container."""
        return str(self._workspace_root / container / "workspace")

    async def _ensure_workspace(self, workspace: Path, image: str) -> None:
        """Ensure the host workspace exists and is writable by us. The official image's
        init chowns /opt/data to its internal user (UID 10000), so a workspace left over
        from a prior run is not writable — reset ownership via a one-shot root helper
        (chown) so caduceus can (re)write the config before start."""
        if workspace.exists() and not os.access(workspace, os.W_OK):
            log.info("resetting ownership of reused workspace %s", workspace)
            await self._check(
                "run", "--rm", "--entrypoint", "chown",
                "-v", f"{workspace}:{CONTAINER_DATA}", image,
                "-R", f"{os.getuid()}:{os.getgid()}", CONTAINER_DATA, timeout=60.0)
        else:
            workspace.mkdir(parents=True, exist_ok=True)

    async def create(self, container: str, image: str, env: dict[str, str], runtime: str) -> None:
        """`docker create` the agent container (created, not started) from the official
        image. Bind-mounts the host workspace at /opt/data, publishes 8642 to a
        Docker-assigned host loopback port, runs `gateway run`. Fails fast if `runtime`
        is unavailable."""
        workspace = Path(self.workspace_for(container))
        await self._ensure_workspace(workspace, image)
        args = ["create", "--name", container, "--restart", "no",
                "-p", f"127.0.0.1::{CONTAINER_API_PORT}",
                "-v", f"{workspace}:{CONTAINER_DATA}", "-w", CONTAINER_DATA]
        if runtime and runtime != "runc":
            args += ["--runtime", runtime]
        for key, value in env.items():
            args += ["-e", f"{key}={value}"]
        args.append(image)
        args += list(GATEWAY_CMD)
        rc, _out, err = await self._run(*args, timeout=120.0)
        if rc != 0:
            msg = err.decode("utf-8", "replace")
            if runtime and runtime != "runc" and ("runtime" in msg.lower() or runtime in msg):
                raise RuntimeUnavailable(
                    f"container runtime '{runtime}' is not available to Docker. "
                    f"Install gVisor and register the '{runtime}' runtime, or set "
                    f"`caduceus gateway config --runtime runc`. (docker: {msg.strip()[:200]})"
                )
            raise upstream_error(f"docker create failed (rc={rc}): {msg[:300]}")

    async def host_port(self, container: str) -> Optional[int]:
        rc, out, _ = await self._run("port", container, str(CONTAINER_API_PORT), timeout=15.0)
        if rc != 0:
            return None
        # output like "127.0.0.1:49xxx" (possibly multiple lines)
        for line in out.decode("utf-8", "replace").splitlines():
            _, _, port = line.strip().rpartition(":")
            if port.isdigit():
                return int(port)
        return None

    async def write_config(self, container: str, content: str) -> None:
        """Write the hermes config into the agent's HERMES_HOME on the **host** side of the
        bind mount (`<workspace>/config.yaml`), so it is present at /opt/data/config.yaml
        when the container starts. Carries the bearer token → 600. (Host-side write, not
        `docker cp`: a mount over /opt/data would shadow a pre-start cp. Workspace ownership
        is reset in `_ensure_workspace`/create so this write always succeeds.)"""
        cfg = Path(self.workspace_for(container)) / HERMES_CONFIG_REL
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(content, encoding="utf-8")
        try:
            os.chmod(cfg, 0o600)
        except OSError:
            pass

    async def stop(self, container: str) -> None:
        await self._check("stop", container, timeout=60.0)

    async def start(self, container: str) -> None:
        await self._check("start", container, timeout=60.0)

    async def remove(self, container: str) -> None:
        await self._check("rm", "-f", container, timeout=60.0)

    async def status(self, container: str) -> str:
        rc, out, _ = await self._run("inspect", "-f", "{{.State.Status}}", container, timeout=15.0)
        if rc != 0:
            return "missing"
        st = out.decode("utf-8", "replace").strip().lower()
        return "running" if st == "running" else "stopped"

    async def statuses(self) -> dict[str, str]:
        """One live `docker ps -a` → {name: running|stopped} for `cad-*` containers.
        Real-time per call (no cache). Raises on docker failure (caller decides policy)."""
        out = await self._check(
            "ps", "-a", "--filter", "name=cad-",
            "--format", "{{.Names}}\t{{.State}}", timeout=15.0)
        result: dict[str, str] = {}
        for line in out.decode("utf-8", "replace").splitlines():
            if "\t" not in line:
                continue
            name, _, state = line.partition("\t")
            name = name.strip()
            if name:
                result[name] = "running" if state.strip().lower() == "running" else "stopped"
        return result

    async def logs(self, container: str, follow: bool = False) -> AsyncIterator[str]:
        args = ["logs"] + (["-f"] if follow else []) + [container]
        proc = await asyncio.create_subprocess_exec(
            self._docker, *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        assert proc.stdout is not None
        async for line in proc.stdout:
            yield line.decode("utf-8", "replace").rstrip("\n")
