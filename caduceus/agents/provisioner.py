"""Provisioner — all Docker interactions for local agents (U8; was sbx-based).

`Provisioner` is the interface (Protocol) consumed by AgentService; `DockerProvisioner`
is the real implementation over the `docker` CLI. Unit tests use a FakeProvisioner; the
real impl is exercised in Build & Test integration.

U8: local agents run as **plain Docker containers** running the hermes API server
(`hermes gateway run`, port 8642). caduceus reaches them over HTTP on a published host
**loopback** port. The container is created (port allocated), the hermes LLM config is
copied in, then the container is started so the API server boots with config present.
Status is queried **live** (no cache). Optional gVisor runtime via `--runtime runsc`
(fail-fast if configured but unavailable).
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Optional, Protocol

from caduceus.common.errors import upstream_error
from caduceus.common.logging import get_logger

log = get_logger("caduceus.provisioner")

#: In-container hermes config path (HERMES_HOME); dir exists in the image.
HERMES_CONFIG_PATH = "/root/.hermes/config.yaml"
#: The API-server port hermes listens on inside the container.
CONTAINER_API_PORT = 8642


class Provisioner(Protocol):
    def workspace_for(self, container: str) -> str: ...
    async def create(self, container: str, image: str, env: dict[str, str], runtime: str) -> None: ...
    async def host_port(self, container: str) -> Optional[int]: ...
    async def put_file(self, container: str, path: str, content: str) -> None: ...
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
        """Host path bind-mounted into the container (same path inside)."""
        return str(self._workspace_root / container / "workspace")

    async def create(self, container: str, image: str, env: dict[str, str], runtime: str) -> None:
        """`docker create` the agent container (created, not started). Publishes 8642 to
        a Docker-assigned host loopback port. Fails fast if `runtime` is unavailable."""
        workspace = Path(self.workspace_for(container))
        workspace.mkdir(parents=True, exist_ok=True)
        args = ["create", "--name", container, "--restart", "no",
                "-p", f"127.0.0.1::{CONTAINER_API_PORT}",
                "-v", f"{workspace}:{workspace}", "-w", str(workspace)]
        if runtime and runtime != "runc":
            args += ["--runtime", runtime]
        for key, value in env.items():
            args += ["-e", f"{key}={value}"]
        args.append(image)
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

    async def put_file(self, container: str, path: str, content: str) -> None:
        """Copy a file into the container via `docker cp` (works while created or running).
        The config carries the agent's bearer token → written 600."""
        tmp = tempfile.mktemp()  # noqa: S306 — local, short-lived
        try:
            Path(tmp).write_text(content, encoding="utf-8")
            os.chmod(tmp, 0o600)
            await self._check("cp", tmp, f"{container}:{path}", timeout=30.0)
        finally:
            try:
                os.remove(tmp)
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
