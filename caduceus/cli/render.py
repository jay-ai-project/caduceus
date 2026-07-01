"""Output rendering + exit codes (Q6/BR-O1/O2).

Human-readable by default; `--json` for scriptable output. Errors go to stderr
with a non-zero exit code.
"""

from __future__ import annotations

import json
import sys

# Exit codes (total mapping; PBT-U4-6)
EXIT_OK = 0
EXIT_RUNTIME = 1   # runtime / upstream / daemon failure
EXIT_USAGE = 2     # usage / validation error


def emit(text: str = "") -> None:
    print(text)


def emit_json(obj) -> None:
    print(json.dumps(obj, indent=2, sort_keys=True))


def error(message: str) -> None:
    print(message, file=sys.stderr)


def progress(phase: str, detail: str = "") -> None:
    """Live status line during long operations → stderr, so `--json` stdout stays clean."""
    line = f"  → {phase}" + (f" ({detail})" if detail else "") + " …"
    print(line, file=sys.stderr, flush=True)


def render_agents(views, as_json: bool) -> None:
    if as_json:
        emit_json([v.to_dict() for v in views])
        return
    if not views:
        emit("No agents. Create one with `caduceus agent create <name>`.")
        return
    rows = [("NAME", "KIND", "LIFECYCLE", "HEALTH", "SESSION", "ENDPOINT")]
    for v in views:
        rows.append((v.name, v.kind, v.lifecycle, v.health,
                     "yes" if v.has_session else "-", v.endpoint or "-"))
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    for r in rows:
        emit("  ".join(c.ljust(widths[i]) for i, c in enumerate(r)))


def render_status(gs, as_json: bool) -> None:
    if as_json:
        emit_json(gs.to_dict())
        return
    if not gs.running:
        emit("caduceus daemon: NOT running. Start it with `caduceus gateway start`.")
        return
    emit(f"caduceus daemon: running (pid {gs.pid})")
    emit(f"  control API : {gs.control_listener}")
    emit(f"  AI-Gateway  : {gs.aigateway_listener}")
    emit(f"  upstream    : {gs.upstream}")
    emit(f"  agents      : {gs.agent_count}")
    emit(f"  version     : {gs.version}")


def _gateway_env_warnings(view, change=None) -> None:
    """Warn (stderr) when an env var shadows config.toml on restart (BR-GC7)."""
    from caduceus.config.gateway_config import ENV_KEYS

    touched = None
    if change is not None:
        touched = set()
        if change.upstream_base_url is not None:
            touched.add("upstream_base_url")
        if change.default_model is not None:
            touched.add("default_model")
        if change.container_runtime is not None:
            touched.add("container_runtime")
    for key in view.env_override:
        if touched is None or key in touched:
            error(f"warning: ${ENV_KEYS.get(key, key)} is set and overrides config.toml on (re)start")


def render_gateway_config(view, as_json: bool) -> None:
    if as_json:
        emit_json(view.to_dict())
        return
    emit(f"upstream_base_url : {view.upstream_base_url or '(not set)'}")
    emit(f"default_model     : {view.default_model or '(not set)'}")
    emit(f"container_runtime : {view.container_runtime}")
    emit(f"configured        : {'yes' if view.upstream_configured else 'no'}")
    emit(f"source            : {view.source}")
    _gateway_env_warnings(view)


def render_gateway_config_applied(view, change, *, live: bool, as_json: bool) -> None:
    if as_json:
        emit_json(view.to_dict())
        return
    changed = []
    if change.upstream_base_url is not None:
        changed.append(f"upstream_base_url={view.upstream_base_url}")
    if change.default_model is not None:
        changed.append(f"default_model={view.default_model}")
    if change.container_runtime is not None:
        changed.append(f"container_runtime={view.container_runtime}")
    where = ("applied live (no restart)" if live
             else "persisted to config.toml — effective on next `gateway start`")
    emit(f"updated {', '.join(changed)} — {where}")
    _gateway_env_warnings(view, change)


def render_doctor(report, as_json: bool) -> None:
    if as_json:
        emit_json(report.to_dict())
        return
    for c in report.checks:
        mark = "ok " if c.ok else ("FAIL" if c.required else "warn")
        emit(f"  [{mark}] {c.name}: {c.detail}")
        if c.hint and not c.ok:
            for line in c.hint.splitlines():
                error(f"        {line}")
    emit("")
    emit("doctor: OK" if report.ok else "doctor: problems found (see above)")


def render_config(snapshot, as_json: bool) -> None:
    if as_json:
        emit_json(snapshot.to_dict())
        return
    emit(f"skills : {', '.join(snapshot.skills) or '-'}")
    emit(f"tools  : enabled={', '.join(snapshot.tools_enabled) or '-'} "
         f"disabled={', '.join(snapshot.tools_disabled) or '-'}")
    emit(f"core   : {snapshot.core or '-'}")
    emit(f"soul   : {(snapshot.soul[:60] + '…') if len(snapshot.soul) > 60 else snapshot.soul or '-'}")


def render_config_result(result, as_json: bool) -> None:
    if as_json:
        emit_json(result.to_dict())
        return
    status = "verified" if result.verified else "NOT verified"
    emit(f"config applied ({result.strategy}, {status}): {', '.join(result.applied) or 'no-op'}")
    if result.detail:
        emit(f"  {result.detail}")
