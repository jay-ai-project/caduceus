"""Provisioner — all Docker interactions for local agents (U8; was sbx-based).

`Provisioner` is the interface (Protocol) consumed by AgentService; `DockerProvisioner`
is the real implementation over the `docker` CLI. Unit tests use a FakeProvisioner; the
real impl is exercised in Build & Test integration.

U8: local agents run as **plain Docker containers** built from the **official**
`nousresearch/hermes-agent` image, running the hermes API server (`gateway run`, port
8642). caduceus reaches them over HTTP on a published host **loopback** port.

Storage split (U8-D6):
  * **HERMES_HOME (`/opt/data`)** — hermes config + memory + sessions. **Not** bind-mounted;
    it rides the image's anonymous `VOLUME /opt/data`, so it survives stop→start (restart)
    but is wiped on delete (we `docker rm -v`). Recreating an agent with the same name thus
    starts with a **fresh** config/memory.
  * **Workspace (`/opt/data/workspace`)** — the agent's cwd and artifact output. Bind-mounted
    (a nested mount inside HERMES_HOME) to a host path keyed by agent name (`<ws>/workspace`),
    so artifacts **persist** across delete+recreate (a bind mount is untouched by `rm -v`).
    Nesting it under HERMES_HOME keeps the image-default `HERMES_WRITE_SAFE_ROOT=/opt/data`
    valid — the installed hermes only honours a *single* safe-root path, so a colon-joined
    `/opt/data:/workspace` would be read as one bogus path and deny **every** write.
    The agent's cwd is pointed here via `terminal.cwd` in the rendered config.

The container is remapped to the host UID/GID (`HERMES_UID`/`HERMES_GID`) so the bind-mounted
workspace is writable both ways. The LLM config is injected with `docker cp` (no host-side
secret file; the stage2 init chowns+chmods it on start). Status is queried **live** (no
cache). Optional gVisor runtime via `--runtime runsc` (fail-fast if configured but
unavailable).
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

#: HERMES_HOME — config + memory. NOT bind-mounted (image anon volume; wiped on `rm -v`).
CONTAINER_DATA = "/opt/data"
#: The agent's cwd / artifact dir — bind-mounted to a persistent host path. Nested under
#: HERMES_HOME so the image-default single-path HERMES_WRITE_SAFE_ROOT=/opt/data covers it.
CONTAINER_WORKSPACE = "/opt/data/workspace"
#: In-container config path we `docker cp` the rendered hermes config into.
HERMES_CONFIG_PATH = f"{CONTAINER_DATA}/config.yaml"
#: The agent's identity file — read by hermes at every prompt build (U10/R9).
SOUL_PATH = f"{CONTAINER_DATA}/SOUL.md"
#: Installed skills: one directory per skill, re-scanned per prompt build (U10/R9).
SKILLS_DIR = f"{CONTAINER_DATA}/skills"
#: The API-server port hermes listens on inside the container.
CONTAINER_API_PORT = 8642
#: The dashboard port hermes' s6 dashboard service listens on inside the container (U11).
DASHBOARD_CONTAINER_PORT = 9119
#: Command passed to the official image's entrypoint to run the API server.
GATEWAY_CMD = ("gateway", "run")


class Provisioner(Protocol):
    def workspace_for(self, container: str) -> str: ...
    async def create(self, container: str, image: str, env: dict[str, str], runtime: str,
                     publish_dashboard: bool = False) -> None: ...
    async def host_port(self, container: str, port: int = CONTAINER_API_PORT) -> Optional[int]: ...
    async def write_config(self, container: str, content: str) -> None: ...
    async def stop(self, container: str) -> None: ...
    async def start(self, container: str) -> None: ...
    async def remove(self, container: str) -> None: ...
    async def status(self, container: str) -> str: ...  # running | stopped | missing
    async def statuses(self) -> dict[str, str]: ...      # live `docker ps -a`, one call
    def logs(self, container: str, follow: bool = False) -> AsyncIterator[str]: ...
    # ---- agent-config I/O (U10/R9; `docker cp` works on stopped containers too) ----
    async def read_file(self, container: str, path: str) -> Optional[str]: ...
    async def write_file(self, container: str, path: str, content: str) -> None: ...
    async def list_dir(self, container: str, path: str) -> list[str]: ...
    async def remove_path(self, container: str, path: str) -> None: ...  # running only


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
        """Host path bind-mounted at /opt/data/workspace inside the container
        (the agent's cwd; artifacts persist across delete+recreate)."""
        return str(self._workspace_root / container / "workspace")

    def _layout_env(self) -> dict[str, str]:
        """Container-layout env owned by the provisioner: run as the host UID/GID so the
        bind-mounted workspace is writable both ways. (HERMES_WRITE_SAFE_ROOT stays at the
        image default /opt/data — which already covers the nested workspace — and the cwd is
        set via `terminal.cwd` in the rendered config, not the deprecated TERMINAL_CWD env.)"""
        return {
            "HERMES_UID": str(os.getuid()),
            "HERMES_GID": str(os.getgid()),
        }

    async def _ensure_workspace(self, workspace: Path) -> None:
        """Ensure the host workspace dir exists. The container runs as our UID/GID
        (`_layout_env`), so files it writes here are owned by us and a reused workspace
        stays writable — no ownership reset needed."""
        workspace.mkdir(parents=True, exist_ok=True)

    async def create(self, container: str, image: str, env: dict[str, str], runtime: str,
                     publish_dashboard: bool = False) -> None:
        """`docker create` the agent container (created, not started) from the official
        image. Bind-mounts the persistent host workspace at /opt/data/workspace (cwd); the
        rest of HERMES_HOME (/opt/data) is left on the image's anonymous volume. Publishes
        8642 (and 9119 when the dashboard is enabled, U11) to Docker-assigned host loopback
        ports, runs `gateway run`. Fails fast if `runtime` is unavailable."""
        workspace = Path(self.workspace_for(container))
        await self._ensure_workspace(workspace)
        args = ["create", "--name", container, "--restart", "no",
                "-p", f"127.0.0.1::{CONTAINER_API_PORT}",
                "-v", f"{workspace}:{CONTAINER_WORKSPACE}", "-w", CONTAINER_WORKSPACE]
        if publish_dashboard:
            args += ["-p", f"127.0.0.1::{DASHBOARD_CONTAINER_PORT}"]
        if runtime and runtime != "runc":
            args += ["--runtime", runtime]
        for key, value in {**self._layout_env(), **env}.items():
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

    async def host_port(self, container: str, port: int = CONTAINER_API_PORT) -> Optional[int]:
        rc, out, _ = await self._run("port", container, str(port), timeout=15.0)
        if rc != 0:
            return None
        # output like "127.0.0.1:49xxx" (possibly multiple lines)
        for line in out.decode("utf-8", "replace").splitlines():
            _, _, port = line.strip().rpartition(":")
            if port.isdigit():
                return int(port)
        return None

    async def write_config(self, container: str, content: str) -> None:
        """Inject the hermes config into the (created, not-yet-started) container's
        HERMES_HOME via `docker cp` → /opt/data/config.yaml. HERMES_HOME is unmounted now,
        so the config lands in the container's anon volume (wiped on delete, kept on restart)
        and never touches the host filesystem as a secret file. The stage2 init chowns it to
        the hermes user and chmods 640 on start, so an inbound root:root 600 file is fine."""
        await self.write_file(container, HERMES_CONFIG_PATH, content)

    # ---- agent-config I/O (U10/R9) -----------------------------------
    async def write_file(self, container: str, path: str, content: str) -> None:
        """`docker cp` a file into the container (works created/stopped/running).
        The temp file never carries more than one config's content and is 600."""
        with tempfile.NamedTemporaryFile("w", suffix=".tmp", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(content)
            tmp = fh.name
        try:
            os.chmod(tmp, 0o600)
            await self._check("cp", tmp, f"{container}:{path}", timeout=30.0)
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    async def read_file(self, container: str, path: str) -> Optional[str]:
        """Read one in-container file via `docker cp <c>:<path> -` (a tar stream on
        stdout). None when the file does not exist / cp fails."""
        rc, out, _err = await self._run("cp", f"{container}:{path}", "-", timeout=30.0)
        if rc != 0:
            return None
        import io
        import tarfile

        try:
            with tarfile.open(fileobj=io.BytesIO(out)) as tf:
                for member in tf.getmembers():
                    if member.isfile():
                        f = tf.extractfile(member)
                        if f is not None:
                            return f.read().decode("utf-8", "replace")
        except tarfile.TarError:
            return None
        return None

    async def list_dir(self, container: str, path: str) -> list[str]:
        """Names of the direct children of an in-container directory (via the same
        `docker cp` tar stream). Missing directory → []."""
        rc, out, _err = await self._run("cp", f"{container}:{path}", "-", timeout=30.0)
        if rc != 0:
            return []
        import io
        import tarfile

        names: set[str] = set()
        try:
            with tarfile.open(fileobj=io.BytesIO(out)) as tf:
                for member in tf.getmembers():
                    parts = member.name.split("/")
                    # member names look like "skills/<child>[/...]" — take the child.
                    if len(parts) >= 2 and parts[1]:
                        names.add(parts[1])
        except tarfile.TarError:
            return []
        return sorted(names)

    async def remove_path(self, container: str, path: str) -> None:
        """Delete a path inside a RUNNING container (`docker exec rm -rf`); no shell,
        argv only. Used for skill removal (U10/R9)."""
        await self._check("exec", container, "rm", "-rf", "--", path, timeout=30.0)

    async def stop(self, container: str) -> None:
        await self._check("stop", container, timeout=60.0)

    async def start(self, container: str) -> None:
        await self._check("start", container, timeout=60.0)

    async def remove(self, container: str) -> None:
        # -v also drops the anon HERMES_HOME volume → config/memory are wiped on delete
        # (the persistent /workspace is a bind mount, unaffected).
        await self._check("rm", "-f", "-v", container, timeout=60.0)

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
