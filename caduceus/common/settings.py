"""Caduceus runtime settings (subset introduced by U1; extended by U4).

Precedence: environment variables override file/defaults.

The upstream LLM (`upstream_base_url`) and its model (`default_model`) are
deliberately **NOT** given baked-in defaults — they are environment-specific and
**required** before the gateway can serve. The daemon validates this at startup
via `ensure_configured()`. U4 adds an interactive `caduceus gateway` setup that
prompts for them when unset and reuses them when already configured.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

#: Logical model alias: when an agent requests this, caduceus substitutes the
#: configured default model before forwarding upstream (routing.resolve_model).
SENTINEL_MODEL = "default"


class ConfigError(Exception):
    """Raised when required configuration is missing (e.g. upstream not set)."""


@dataclass
class Timeouts:
    connect: float = 10.0
    #: per-chunk idle/read timeout for streaming responses
    read: float = 120.0
    #: total timeout for unary (non-streaming) requests
    unary_total: float = 300.0


@dataclass
class Settings:
    # --- Required, environment-specific (no baked-in defaults) ---
    #: Base URL of the upstream OpenAI-compatible LLM (e.g. a local Ollama endpoint).
    upstream_base_url: str | None = None
    #: Model used when an agent requests the `default` alias.
    default_model: str | None = None

    # --- Caduceus's own network defaults (overridable) ---
    control_bind: str = "127.0.0.1:9700"
    #: Actual AI-Gateway bind; Infrastructure Design recommends the docker bridge
    #: gateway IP (e.g. 172.17.0.1). The daemon (U4) resolves the concrete
    #: bind/advertise host at startup.
    aigateway_bind: str = "0.0.0.0:9701"
    aigateway_advertise_host: str | None = None
    upstream_auth: str | None = None
    #: Docker runtime for agent containers: "runc" (default) | "runsc" (gVisor, opt-in).
    #: Availability is enforced at container-spawn time (fail-fast); see U8 BR-R2.
    container_runtime: str = "runc"
    timeouts: Timeouts = field(default_factory=Timeouts)

    #: Fields that must be configured before the gateway can serve.
    REQUIRED_FIELDS = ("upstream_base_url", "default_model")

    @classmethod
    def from_env(cls) -> "Settings":
        """Build settings from the environment. Required fields are left unset
        (None) when absent — they are NOT defaulted to any particular host/model.
        """
        return cls(
            upstream_base_url=os.getenv("CADUCEUS_UPSTREAM_BASE_URL"),
            default_model=os.getenv("CADUCEUS_DEFAULT_MODEL"),
            control_bind=os.getenv("CADUCEUS_CONTROL_BIND", "127.0.0.1:9700"),
            aigateway_bind=os.getenv("CADUCEUS_AIGATEWAY_BIND", "0.0.0.0:9701"),
            aigateway_advertise_host=os.getenv("CADUCEUS_AIGW_ADVERTISE_HOST"),
            upstream_auth=os.getenv("CADUCEUS_UPSTREAM_AUTH"),
            container_runtime=os.getenv("CADUCEUS_CONTAINER_RUNTIME", "runc"),
            timeouts=Timeouts(
                connect=float(os.getenv("CADUCEUS_CONNECT_TIMEOUT", "10")),
                read=float(os.getenv("CADUCEUS_IDLE_TIMEOUT", "120")),
                unary_total=float(os.getenv("CADUCEUS_UNARY_TIMEOUT", "300")),
            ),
        )

    @classmethod
    def from_env_and_file(cls, path: "str | os.PathLike | None" = None) -> "Settings":
        """Layered settings: env > `config.toml` > built-in default (U4, Q3).

        The file (TOML) supplies values for any key not set in the environment;
        required keys (`upstream_base_url`/`default_model`) stay unset if neither
        env nor file provides them.
        """
        import tomllib
        from pathlib import Path

        file_vals: dict = {}
        if path is not None:
            p = Path(path)
            if p.exists():
                file_vals = tomllib.loads(p.read_text(encoding="utf-8"))

        def pick(env_key: str, file_key: str, default=None):
            v = os.getenv(env_key)
            if v is not None:
                return v
            if file_key in file_vals and file_vals[file_key] is not None:
                return file_vals[file_key]
            return default

        t = file_vals.get("timeouts", {}) if isinstance(file_vals.get("timeouts"), dict) else {}
        return cls(
            upstream_base_url=pick("CADUCEUS_UPSTREAM_BASE_URL", "upstream_base_url"),
            default_model=pick("CADUCEUS_DEFAULT_MODEL", "default_model"),
            control_bind=pick("CADUCEUS_CONTROL_BIND", "control_bind", "127.0.0.1:9700"),
            aigateway_bind=pick("CADUCEUS_AIGATEWAY_BIND", "aigateway_bind", "0.0.0.0:9701"),
            aigateway_advertise_host=pick("CADUCEUS_AIGW_ADVERTISE_HOST", "aigateway_advertise_host"),
            upstream_auth=pick("CADUCEUS_UPSTREAM_AUTH", "upstream_auth"),
            container_runtime=pick("CADUCEUS_CONTAINER_RUNTIME", "container_runtime", "runc"),
            timeouts=Timeouts(
                connect=float(os.getenv("CADUCEUS_CONNECT_TIMEOUT", str(t.get("connect", 10)))),
                read=float(os.getenv("CADUCEUS_IDLE_TIMEOUT", str(t.get("read", 120)))),
                unary_total=float(os.getenv("CADUCEUS_UNARY_TIMEOUT", str(t.get("unary_total", 300)))),
            ),
        )

    def write_config_toml(self, path: "str | os.PathLike") -> None:
        """Persist the bootstrap-relevant settings to `config.toml` (perms 600)."""
        from pathlib import Path

        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(p.parent, 0o700)
        except OSError:
            pass

        def esc(s: str) -> str:
            return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'

        lines = ["# caduceus config (written by `gateway start` bootstrap)"]
        for key in ("upstream_base_url", "default_model", "control_bind",
                    "aigateway_bind", "aigateway_advertise_host", "upstream_auth",
                    "container_runtime"):
            val = getattr(self, key)
            if val is not None:
                lines.append(f"{key} = {esc(val)}")
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass

    def missing_required(self) -> list[str]:
        return [name for name in self.REQUIRED_FIELDS if not getattr(self, name)]

    def ensure_configured(self) -> None:
        """Raise ConfigError (with guidance) if required config is missing."""
        missing = self.missing_required()
        if missing:
            raise ConfigError(
                "Upstream LLM is not configured. Configure it before starting the gateway.\n"
                "  via env:  CADUCEUS_UPSTREAM_BASE_URL=<url>  CADUCEUS_DEFAULT_MODEL=<model>\n"
                "  (U4 will add an interactive `caduceus gateway` setup that prompts when unset\n"
                "   and reuses the saved values when already configured.)\n"
                f"  Missing: {', '.join(missing)}"
            )
