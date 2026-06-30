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
