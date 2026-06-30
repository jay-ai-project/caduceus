"""GatewayService — daemon lifecycle (FR-G1..G4).

`start` bootstraps config (Q3), acquires the single-instance lock, builds the two
ASGI apps, optionally daemonizes (`-d`), runs both listeners, and starts the U3
Supervisor. The uvicorn-serve loop and the `fork`/`setsid` daemonization are
isolated (`_serve`, `_daemonize`) and **validated in Build & Test**; the pure
parts (config bootstrap, `build_apps`, `status`) are unit-testable.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Optional

from caduceus.common.dto import GatewayStatus
from caduceus.common.logging import get_logger
from caduceus.common.settings import ConfigError, Settings
from caduceus.daemon.control_api import VERSION, build_control_app
from caduceus.daemon.lock import AlreadyRunning, InstanceLock
from caduceus.daemon.wiring import Services, build_services

log = get_logger("caduceus.daemon.gateway")


def build_apps(services: Services):
    """Return (control_app, aigateway_app). Pure — no serving."""
    control_app = build_control_app(services, status_provider=None)
    return control_app, services.aigateway_app


class GatewayService:
    def __init__(self, settings: Optional[Settings] = None, state_dir: "str | Path" = "~/.caduceus"):
        self.state_dir = Path(state_dir).expanduser()
        self.settings = settings or Settings.from_env_and_file(self.state_dir / "config.toml")
        self.lock = InstanceLock(self.state_dir / "caduceus.pid")
        self._started_at: Optional[float] = None

    # ---- bootstrap (Q3) ---------------------------------------------
    def bootstrap_config(self, *, interactive: bool, prompt=input) -> Settings:
        missing = self.settings.missing_required()
        if not missing:
            return self.settings
        if not interactive:
            self.settings.ensure_configured()  # raises ConfigError with guidance
        # interactive prompt + persist (foreground TTY only)
        values = {}
        if "upstream_base_url" in missing:
            values["upstream_base_url"] = prompt("Upstream LLM base URL (e.g. http://localhost:9292/v1): ").strip()
        if "default_model" in missing:
            values["default_model"] = prompt("Default model (e.g. llamacpp/gemma-4-12b): ").strip()
        for k, v in values.items():
            setattr(self.settings, k, v or None)
        self.settings.ensure_configured()
        self.settings.write_config_toml(self.state_dir / "config.toml")
        return self.settings

    # ---- lifecycle ---------------------------------------------------
    def start(self, foreground: bool = True, daemonize: bool = False) -> None:
        interactive = foreground and not daemonize and sys.stdin.isatty()
        self.bootstrap_config(interactive=interactive)

        try:
            self.lock.acquire()
        except AlreadyRunning as exc:
            raise ConfigError(str(exc)) from exc

        try:
            if daemonize:
                self._daemonize()  # Build & Test
            self._started_at = time.time()
            services = build_services(self.settings, state_dir=self.state_dir)
            control_app, aigateway_app = build_apps(services)
            services.supervisor.start()
            self._serve(control_app, aigateway_app, services)  # Build & Test (uvicorn)
        finally:
            self.lock.release()

    def stop(self) -> None:
        """Signal a running daemon to stop (graceful)."""
        pid = self.lock.read_pid()
        if pid is None or not self.lock.is_running():
            log.info("gateway not running")
            return
        try:
            os.kill(pid, 15)  # SIGTERM → graceful handler in the daemon
        except ProcessLookupError:
            pass

    def status(self) -> GatewayStatus:
        if not self.lock.is_running():
            return GatewayStatus(
                running=False, control_listener=self.settings.control_bind,
                aigateway_listener=self.settings.aigateway_bind, version=VERSION,
            )
        from caduceus.agents.registry import Registry

        reg = Registry(self.state_dir / "state.json")
        reg.load()
        return GatewayStatus(
            running=True, pid=self.lock.read_pid(),
            control_listener=self.settings.control_bind,
            aigateway_listener=self.settings.aigateway_bind,
            agent_count=len(reg.list()), version=VERSION,
        )

    # ===== Build & Test: process-level bits (not unit-tested) =========
    def _daemonize(self) -> None:  # pragma: no cover
        logs_dir = self.state_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        if os.fork() > 0:
            os._exit(0)
        os.setsid()
        if os.fork() > 0:
            os._exit(0)
        os.chdir(str(self.state_dir))
        self.lock.acquire()  # re-record the child's pid
        logf = open(logs_dir / "daemon.log", "ab", buffering=0)
        os.dup2(logf.fileno(), sys.stdout.fileno())
        os.dup2(logf.fileno(), sys.stderr.fileno())

    def _serve(self, control_app, aigateway_app, services) -> None:  # pragma: no cover
        import asyncio

        import uvicorn

        c_host, c_port = self.settings.control_bind.rsplit(":", 1)
        a_host, a_port = self.settings.aigateway_bind.rsplit(":", 1)
        c = uvicorn.Server(uvicorn.Config(control_app, host=c_host, port=int(c_port), log_level="info"))
        a = uvicorn.Server(uvicorn.Config(aigateway_app, host=a_host, port=int(a_port), log_level="info"))

        async def _run():
            try:
                await asyncio.gather(c.serve(), a.serve())
            finally:
                await services.supervisor.stop()

        asyncio.run(_run())
