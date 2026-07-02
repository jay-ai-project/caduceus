"""`caduceus doctor` — environment readiness checks (U8, FR-U8-11, BR-O1).

CLI-local (works whether or not the daemon is running). Reports Docker availability,
the hermes image, the configured container runtime (and gVisor/`runsc` availability),
and daemon reachability. It **never installs** anything — when gVisor is desired but
missing it prints install guidance only (Q3/Q4).
"""

from __future__ import annotations

import json
import shutil
import subprocess  # noqa: S404 — invoking the local docker CLI, no shell
from dataclasses import dataclass, field

from caduceus.agents.images import DEFAULT_TAG

GVISOR_INSTALL_HINT = (
    "gVisor (runsc) is not registered with Docker. To use runtime=runsc:\n"
    "  1. Install gVisor: https://gvisor.dev/docs/user_guide/install/\n"
    "  2. Register the runtime with Docker (e.g. `runsc install`) and restart dockerd.\n"
    "  Or set runtime back to runc: `caduceus gateway config --runtime runc`."
)


@dataclass
class Check:
    name: str
    ok: bool
    required: bool = True
    detail: str = ""
    hint: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "ok": self.ok, "required": self.required,
                "detail": self.detail, "hint": self.hint}


@dataclass
class DoctorReport:
    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks if c.required)

    def to_dict(self) -> dict:
        return {"ok": self.ok, "checks": [c.to_dict() for c in self.checks]}


def _docker(*args: str, timeout: float = 15.0) -> tuple[int, str]:
    try:
        p = subprocess.run(["docker", *args], capture_output=True, text=True,  # noqa: S607
                           timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except FileNotFoundError:
        return 127, "docker CLI not found on PATH"
    except Exception as exc:  # noqa: BLE001
        return 1, str(exc)


def _docker_runtimes() -> set[str]:
    rc, out = _docker("info", "--format", "{{json .Runtimes}}")
    if rc != 0:
        return set()
    try:
        return set(json.loads(out.strip()).keys())
    except (ValueError, AttributeError):
        return set()


def _tcp_reachable(url: str, timeout: float = 3.0) -> bool:
    """Plain TCP dial to the URL's host:port — reachability only, no HTTP."""
    import socket
    from urllib.parse import urlparse

    p = urlparse(url)
    host = p.hostname or ""
    port = p.port or (443 if p.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def run_doctor(container_runtime: str = "runc", image_tag: str = DEFAULT_TAG,
               daemon_up: bool | None = None,
               upstream_url: "str | None" = None,
               check_upstream: bool = False) -> DoctorReport:
    checks: list[Check] = []

    # 0. upstream LLM reachability (U10/R17) — the most common "why doesn't chat
    # work" cause. Only when the caller opts in (the CLI always does).
    if check_upstream:
        if not upstream_url:
            checks.append(Check(
                "upstream LLM", ok=False, detail="not configured",
                hint="Set it: `caduceus gateway config --upstream-url <url> --model <model>`."))
        else:
            reachable = _tcp_reachable(upstream_url)
            checks.append(Check(
                "upstream LLM", ok=reachable,
                detail=(f"{upstream_url} reachable" if reachable
                        else f"{upstream_url} NOT reachable"),
                hint="" if reachable else
                "Is the LLM server (e.g. Ollama) running? Chat will fail until it is."))

    # 1. docker CLI + server
    if shutil.which("docker") is None:
        checks.append(Check("docker", ok=False, detail="docker CLI not on PATH",
                            hint="Install Docker Engine: https://docs.docker.com/engine/install/"))
        return DoctorReport(checks)  # the remaining checks all need docker
    rc, out = _docker("version", "--format", "{{.Server.Version}}")
    server_ok = rc == 0 and out.strip() != ""
    checks.append(Check("docker", ok=server_ok,
                        detail=(f"server {out.strip()}" if server_ok else "docker server unreachable"),
                        hint="" if server_ok else "Is the Docker daemon running?"))
    if not server_ok:
        return DoctorReport(checks)

    # 2. hermes image (non-fatal: pulled on first `agent create`)
    rc, _ = _docker("image", "inspect", image_tag)
    checks.append(Check("hermes image", ok=rc == 0, required=False,
                        detail=(image_tag if rc == 0 else f"{image_tag} not pulled yet"),
                        hint="" if rc == 0 else "Pulled automatically on first `caduceus agent create` (~3.8 GB)."))

    # 3. container runtime availability (fail-fast intent, BR-R2)
    runtimes = _docker_runtimes()
    if container_runtime == "runc":
        checks.append(Check("container runtime", ok=True, detail="runc (default)"))
    else:
        avail = container_runtime in runtimes
        checks.append(Check(
            f"container runtime ({container_runtime})", ok=avail,
            detail=(f"{container_runtime} registered with Docker" if avail
                    else f"{container_runtime} NOT available; agent create will fail"),
            hint="" if avail else GVISOR_INSTALL_HINT))

    # 4. gVisor availability (informational)
    checks.append(Check("gVisor (runsc)", ok="runsc" in runtimes, required=False,
                        detail=("available" if "runsc" in runtimes else "not installed"),
                        hint="" if "runsc" in runtimes else
                        "Optional stronger isolation; see https://gvisor.dev/docs/user_guide/install/"))

    # 5. daemon reachability (informational)
    if daemon_up is not None:
        checks.append(Check("caduceus daemon", ok=daemon_up, required=False,
                            detail=("running" if daemon_up else "not running"),
                            hint="" if daemon_up else "Start with `caduceus gateway start`."))
    return DoctorReport(checks)
