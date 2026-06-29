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
    #: Base URL of the upstream OpenAI-compatible LLM (e.g. a local llama-swap).
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
            timeouts=Timeouts(
                connect=float(os.getenv("CADUCEUS_CONNECT_TIMEOUT", "10")),
                read=float(os.getenv("CADUCEUS_IDLE_TIMEOUT", "120")),
                unary_total=float(os.getenv("CADUCEUS_UNARY_TIMEOUT", "300")),
            ),
        )

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
