"""Shared domain models (the cross-unit contract).

`AgentRecord` is consumed by U1 (token_lookup), U3 (transport/chat), and U4 (CLI/daemon).
Serialization is explicit so `from_dict(to_dict(x)) == x` (PBT round-trip).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class AgentKind(str, Enum):
    local = "local"
    remote = "remote"


class Lifecycle(str, Enum):
    creating = "creating"
    running = "running"
    stopped = "stopped"
    failed = "failed"
    registered = "registered"  # remote agents


class HealthLevel(str, Enum):
    healthy = "healthy"
    degraded = "degraded"
    unhealthy = "unhealthy"
    unknown = "unknown"


@dataclass
class HealthStatus:
    level: HealthLevel = HealthLevel.unknown
    shallow: bool = False
    deep: Optional[bool] = None
    detail: str = ""
    checked_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "level": self.level.value,
            "shallow": self.shallow,
            "deep": self.deep,
            "detail": self.detail,
            "checked_at": self.checked_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "HealthStatus":
        return cls(
            level=HealthLevel(d.get("level", "unknown")),
            shallow=d.get("shallow", False),
            deep=d.get("deep"),
            detail=d.get("detail", ""),
            checked_at=d.get("checked_at"),
        )


@dataclass
class AgentRecord:
    name: str
    kind: AgentKind
    token: str  # bearer for the caduceus AI-Gateway AND the agent's API_SERVER_KEY (U8)
    #: base URL of the agent's hermes API server. Local: http://127.0.0.1:<host_port>
    #: (set after the container publishes its port); remote: the user-registered URL.
    endpoint: Optional[str] = None
    #: remote only (U10/R6): the agent's own API-server bearer, when it differs from
    #: `token` (`agent register --auth`). Transport auth uses `serve_auth or token`.
    #: SECRET — never projected into AgentView.
    serve_auth: Optional[str] = None
    #: Docker container name (`cad-<name>`) for local agents (U8; was `sandbox_name`).
    container_name: Optional[str] = None
    #: host path bind-mounted into the container (same path inside) — the agent's
    #: working dir, so files it writes there are host-visible & persist.
    workspace_path: Optional[str] = None
    #: published host loopback port mapped to the container's 8642 (U8; was `serve_port`).
    host_port: Optional[int] = None
    #: container runtime used at spawn: "runc" (default) | "runsc" (gVisor). Informational.
    runtime: str = "runc"
    model_alias: str = "default"
    session_id: Optional[str] = None
    lifecycle: Lifecycle = Lifecycle.creating
    last_health: Optional[HealthStatus] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind.value,
            "token": self.token,
            "endpoint": self.endpoint,
            "serve_auth": self.serve_auth,
            "container_name": self.container_name,
            "workspace_path": self.workspace_path,
            "host_port": self.host_port,
            "runtime": self.runtime,
            "model_alias": self.model_alias,
            "session_id": self.session_id,
            "lifecycle": self.lifecycle.value,
            "last_health": self.last_health.to_dict() if self.last_health else None,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AgentRecord":
        lh = d.get("last_health")
        return cls(
            name=d["name"],
            kind=AgentKind(d["kind"]),
            token=d["token"],
            endpoint=d.get("endpoint"),
            serve_auth=d.get("serve_auth"),
            container_name=d.get("container_name"),
            workspace_path=d.get("workspace_path"),
            host_port=d.get("host_port"),
            runtime=d.get("runtime", "runc"),
            model_alias=d.get("model_alias", "default"),
            session_id=d.get("session_id"),
            lifecycle=Lifecycle(d.get("lifecycle", "creating")),
            last_health=HealthStatus.from_dict(lh) if lh else None,
            created_at=d.get("created_at"),
            updated_at=d.get("updated_at"),
        )
