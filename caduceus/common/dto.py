"""U4 API DTOs + the pure config reducer (FR-G/E).

These are the Control API <-> CLI data shapes (dataclasses with explicit
`to_dict`/`from_dict` for stable round-trips) plus `apply_change`, a **pure**
(no-I/O) reducer over `ConfigSnapshot`, and the `ReloadStrategy` seam (Q2).
The agent `token` is never projected into `AgentView`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from caduceus.common.models import AgentRecord, HealthLevel, HealthStatus


# ---- request specs (CLI -> Control API) ---------------------------
@dataclass
class CreateSpec:
    name: str
    #: model alias for the agent (None → gateway default alias); non-sentinel models
    #: pass through the AI-Gateway to the upstream unchanged.
    model: Optional[str] = None
    #: agent image tag override for this create (None → pinned default).
    image: Optional[str] = None

    def to_dict(self) -> dict:
        return {"name": self.name, "model": self.model, "image": self.image}

    @classmethod
    def from_dict(cls, d: dict) -> "CreateSpec":
        return cls(name=d["name"], model=d.get("model"), image=d.get("image"))


@dataclass
class RegisterSpec:
    name: str
    endpoint: str
    auth: Optional[str] = None

    def to_dict(self) -> dict:
        return {"name": self.name, "endpoint": self.endpoint, "auth": self.auth}

    @classmethod
    def from_dict(cls, d: dict) -> "RegisterSpec":
        return cls(name=d["name"], endpoint=d["endpoint"], auth=d.get("auth"))


# ---- projections (Control API -> CLI) -----------------------------
@dataclass
class AgentView:
    """Secret-free projection of AgentRecord (+ health) for `agent ls`."""
    name: str
    kind: str
    lifecycle: str
    health: str
    endpoint: Optional[str] = None
    model_alias: str = "default"
    has_session: bool = False
    created_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "name": self.name, "kind": self.kind, "lifecycle": self.lifecycle,
            "health": self.health, "endpoint": self.endpoint,
            "model_alias": self.model_alias, "has_session": self.has_session,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AgentView":
        return cls(
            name=d["name"], kind=d["kind"], lifecycle=d["lifecycle"], health=d["health"],
            endpoint=d.get("endpoint"), model_alias=d.get("model_alias", "default"),
            has_session=d.get("has_session", False), created_at=d.get("created_at"),
        )

    @classmethod
    def from_record(cls, rec: AgentRecord, health: Optional[HealthStatus] = None) -> "AgentView":
        level = (health.level if health else (rec.last_health.level if rec.last_health else HealthLevel.unknown))
        return cls(
            name=rec.name, kind=rec.kind.value, lifecycle=rec.lifecycle.value,
            health=level.value, endpoint=rec.endpoint, model_alias=rec.model_alias,
            has_session=rec.session_id is not None, created_at=rec.created_at,
        )


@dataclass
class GatewayStatus:
    running: bool = False
    pid: Optional[int] = None
    uptime_s: Optional[float] = None
    control_listener: str = ""
    aigateway_listener: str = ""
    upstream: str = HealthLevel.unknown.value
    agent_count: int = 0
    version: str = ""

    def to_dict(self) -> dict:
        return {
            "running": self.running, "pid": self.pid, "uptime_s": self.uptime_s,
            "control_listener": self.control_listener, "aigateway_listener": self.aigateway_listener,
            "upstream": self.upstream, "agent_count": self.agent_count, "version": self.version,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "GatewayStatus":
        return cls(
            running=d.get("running", False), pid=d.get("pid"), uptime_s=d.get("uptime_s"),
            control_listener=d.get("control_listener", ""), aigateway_listener=d.get("aigateway_listener", ""),
            upstream=d.get("upstream", HealthLevel.unknown.value),
            agent_count=d.get("agent_count", 0), version=d.get("version", ""),
        )


# ---- gateway upstream config (U6) ---------------------------------
@dataclass
class GatewayConfigChange:
    """Edit intent for the gateway's config. `None` = leave unchanged; at least one
    field must be set (BR-GC1). Values are trimmed. `container_runtime` = U8."""
    upstream_base_url: Optional[str] = None
    default_model: Optional[str] = None
    container_runtime: Optional[str] = None

    def __post_init__(self) -> None:
        if self.upstream_base_url is not None:
            self.upstream_base_url = self.upstream_base_url.strip()
        if self.default_model is not None:
            self.default_model = self.default_model.strip()
        if self.container_runtime is not None:
            self.container_runtime = self.container_runtime.strip()

    def is_empty(self) -> bool:
        return (self.upstream_base_url is None and self.default_model is None
                and self.container_runtime is None)

    def to_dict(self) -> dict:
        return {"upstream_base_url": self.upstream_base_url, "default_model": self.default_model,
                "container_runtime": self.container_runtime}

    @classmethod
    def from_dict(cls, d: dict) -> "GatewayConfigChange":
        return cls(upstream_base_url=d.get("upstream_base_url"), default_model=d.get("default_model"),
                   container_runtime=d.get("container_runtime"))


@dataclass
class GatewayConfigView:
    """Secret-free projection of the gateway's effective config (BR-GC8)."""
    upstream_base_url: Optional[str] = None
    default_model: Optional[str] = None
    container_runtime: str = "runc"
    upstream_configured: bool = False
    source: str = "file"                      # "live" (running daemon) | "file"
    env_override: list[str] = field(default_factory=list)  # keys forced by env vars

    def to_dict(self) -> dict:
        return {
            "upstream_base_url": self.upstream_base_url, "default_model": self.default_model,
            "container_runtime": self.container_runtime,
            "upstream_configured": self.upstream_configured, "source": self.source,
            "env_override": list(self.env_override),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "GatewayConfigView":
        return cls(
            upstream_base_url=d.get("upstream_base_url"), default_model=d.get("default_model"),
            container_runtime=d.get("container_runtime", "runc"),
            upstream_configured=d.get("upstream_configured", False), source=d.get("source", "file"),
            env_override=list(d.get("env_override", [])),
        )


# ---- config edit model (FR-E) -------------------------------------
class ChangeKind(str, Enum):
    skills = "skills"
    tools = "tools"
    soul = "soul"
    core = "core"


class ReloadStrategy(str, Enum):
    hot_reload = "hot_reload"
    restart_serve = "restart_serve"


#: Q2 seam — per-kind reload strategy, confirmed against hermes 0.17.0 (U10/R9):
#: SOUL.md and the skills dir are re-read every prompt build → hot (no restart);
#: platform_toolsets and general config keys load at process start → restart.
CHANGE_KIND_STRATEGY: dict[ChangeKind, ReloadStrategy] = {
    ChangeKind.skills: ReloadStrategy.hot_reload,
    ChangeKind.tools: ReloadStrategy.restart_serve,
    ChangeKind.soul: ReloadStrategy.hot_reload,
    ChangeKind.core: ReloadStrategy.restart_serve,
}


def resolve_strategy(kinds) -> ReloadStrategy:
    """Strongest strategy among affected kinds (restart_serve > hot_reload)."""
    strongest = ReloadStrategy.hot_reload
    for k in kinds:
        if CHANGE_KIND_STRATEGY.get(k) == ReloadStrategy.restart_serve:
            return ReloadStrategy.restart_serve
    return strongest


@dataclass
class ConfigSnapshot:
    skills: list[str] = field(default_factory=list)
    tools_enabled: list[str] = field(default_factory=list)
    tools_disabled: list[str] = field(default_factory=list)
    soul: str = ""
    core: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # normalize to sorted/unique so equality and round-trips are stable
        self.skills = sorted(set(self.skills))
        self.tools_enabled = sorted(set(self.tools_enabled))
        self.tools_disabled = sorted(set(self.tools_disabled))

    def to_dict(self) -> dict:
        return {
            "skills": sorted(self.skills),
            "tools": {"enabled": sorted(self.tools_enabled), "disabled": sorted(self.tools_disabled)},
            "soul": self.soul, "core": dict(self.core),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ConfigSnapshot":
        tools = d.get("tools", {})
        return cls(
            skills=list(d.get("skills", [])),
            tools_enabled=list(tools.get("enabled", [])),
            tools_disabled=list(tools.get("disabled", [])),
            soul=d.get("soul", ""), core=dict(d.get("core", {})),
        )


@dataclass
class ConfigChange:
    add_skills: list[str] = field(default_factory=list)
    remove_skills: list[str] = field(default_factory=list)
    enable_tools: list[str] = field(default_factory=list)
    disable_tools: list[str] = field(default_factory=list)
    soul: Optional[str] = None        # resolved text (inline --soul or read from --soul-file)
    soul_file: Optional[str] = None   # path; resolved to `soul` by ConfigEditor
    set_core: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "add_skills": self.add_skills, "remove_skills": self.remove_skills,
            "enable_tools": self.enable_tools, "disable_tools": self.disable_tools,
            "soul": self.soul, "soul_file": self.soul_file, "set_core": self.set_core,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ConfigChange":
        return cls(
            add_skills=list(d.get("add_skills", [])), remove_skills=list(d.get("remove_skills", [])),
            enable_tools=list(d.get("enable_tools", [])), disable_tools=list(d.get("disable_tools", [])),
            soul=d.get("soul"), soul_file=d.get("soul_file"), set_core=dict(d.get("set_core", {})),
        )

    def affected_kinds(self) -> set[ChangeKind]:
        kinds: set[ChangeKind] = set()
        if self.add_skills or self.remove_skills:
            kinds.add(ChangeKind.skills)
        if self.enable_tools or self.disable_tools:
            kinds.add(ChangeKind.tools)
        if self.soul is not None:
            kinds.add(ChangeKind.soul)
        if self.set_core:
            kinds.add(ChangeKind.core)
        return kinds

    def is_empty(self) -> bool:
        return not self.affected_kinds()


@dataclass
class ConfigResult:
    applied: list[str] = field(default_factory=list)
    strategy: str = ReloadStrategy.hot_reload.value
    reloaded: bool = False
    verified: bool = False
    health: str = HealthLevel.unknown.value
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "applied": self.applied, "strategy": self.strategy, "reloaded": self.reloaded,
            "verified": self.verified, "health": self.health, "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ConfigResult":
        return cls(
            applied=list(d.get("applied", [])), strategy=d.get("strategy", ReloadStrategy.hot_reload.value),
            reloaded=d.get("reloaded", False), verified=d.get("verified", False),
            health=d.get("health", HealthLevel.unknown.value), detail=d.get("detail", ""),
        )


def apply_change(snapshot: ConfigSnapshot, change: ConfigChange) -> ConfigSnapshot:
    """Pure reducer: deterministic, idempotent, order-independent (set semantics).

    - skills: (existing ∪ add) − remove   (remove wins on conflict)
    - tools:  enabled' = (enabled ∪ enable) − disable; disabled' = (disabled ∪ disable) − enable
              (a tool in both enable & disable → disabled-wins)
    - soul:   replaced when `change.soul` is not None
    - core:   merged (set_core overrides)
    """
    skills = (set(snapshot.skills) | set(change.add_skills)) - set(change.remove_skills)

    # disable wins on an enable/disable conflict for the same tool
    eff_enable = set(change.enable_tools) - set(change.disable_tools)
    enabled = (set(snapshot.tools_enabled) | eff_enable) - set(change.disable_tools)
    disabled = (set(snapshot.tools_disabled) | set(change.disable_tools)) - eff_enable

    soul = change.soul if change.soul is not None else snapshot.soul
    core = dict(snapshot.core)
    core.update(change.set_core)

    return ConfigSnapshot(
        skills=sorted(skills),
        tools_enabled=sorted(enabled),
        tools_disabled=sorted(disabled),
        soul=soul,
        core=core,
    )


def snapshot_satisfies(snapshot: ConfigSnapshot, change: ConfigChange) -> bool:
    """True iff `snapshot` reflects `change` (read-back verification; Q4/BR-E6)."""
    s = set(snapshot.skills)
    if not set(change.add_skills) <= s:
        return False
    if set(change.remove_skills) & s:
        return False
    en, di = set(snapshot.tools_enabled), set(snapshot.tools_disabled)
    if not set(change.enable_tools) <= en or set(change.enable_tools) & di:
        return False
    if not set(change.disable_tools) <= di or set(change.disable_tools) & en:
        return False
    if change.soul is not None and snapshot.soul != change.soul:
        return False
    for k, v in change.set_core.items():
        if snapshot.core.get(k) != v:
            return False
    return True
