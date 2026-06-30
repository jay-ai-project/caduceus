# U6 — `caduceus gateway config` · Requirements

## Intent Analysis
- **User request**: Add a `caduceus gateway config` command to view the current gateway
  settings and change `upstream_base_url` and `default_model`.
- **Request type**: New Feature (CLI capability over existing settings/config plumbing).
- **Scope estimate**: Single–to–few components — `cli/app.py`, `common/settings.py`,
  daemon Control API (`daemon/control_api.py`, `daemon/wiring.py`), `cli/client.py`,
  and the AI-Gateway upstream/routing seam (`aigateway/upstream.py`, `aigateway/routing.py`).
- **Complexity**: Simple–Moderate (the live hot-apply path is the only non-trivial part).
- **Requirements depth**: Standard.

## Confirmed Decisions (verification answers)
- **Q1 = A** — When the daemon is running: **hot-apply live** (update the running gateway's
  upstream/model immediately) **and** persist to `config.toml`. No restart required.
- **Q2 = A** — Interface: `caduceus gateway config` with `--get` / `--json` to view, and
  dedicated `--upstream-url <url>` / `--model <model>` flags to set.
- **Q3 = A** — Editable keys limited to `upstream_base_url` and `default_model`.
- **Q4 = A** — Works whether or not the daemon is running: daemon **down** → edit
  `config.toml` directly; daemon **up** → apply live (Q1) and persist.
- **Q5 = A** — Light validation only: non-empty values + basic URL shape check
  (scheme + host); no network calls.
- **Q6 = A** — Extensions inherited: Security = No, Resiliency = Yes (full),
  Property-Based Testing = Yes (full).

## Functional Requirements
- **FR-1 — View**: `caduceus gateway config --get` prints the current effective
  `upstream_base_url` and `default_model` (and whether each is set). `--json` emits a
  machine-readable object. Values are read from the same layered source the daemon uses
  (`env > config.toml > default`); when the daemon is running, the values reported are the
  daemon's live effective values.
- **FR-2 — Set**: `--upstream-url <url>` and/or `--model <model>` change the respective
  setting. At least one must be provided for a set operation; otherwise an explanatory
  usage error (mirrors `agent config`'s empty-change behaviour, exit code 2).
- **FR-3 — Persist**: Every successful set writes the new value(s) to
  `~/.caduceus/config.toml` (preserving other keys, file perms `600`), so the change
  survives restarts.
- **FR-4 — Live apply (daemon up)**: When the daemon is running, a set takes effect on the
  running AI-Gateway **without restart** — subsequent agent LLM calls use the new upstream
  base URL and the new `default` model alias resolution.
- **FR-5 — Offline apply (daemon down)**: When the daemon is not running, a set updates
  `config.toml` directly and reports success; it will be picked up on next `gateway start`.
- **FR-6 — Validation**: Before persisting/applying, validate that provided values are
  non-empty and that `--upstream-url` is a syntactically plausible URL (has a scheme such as
  `http`/`https` and a host). Invalid input → usage error (exit 2), nothing written.
- **FR-7 — Output & exit codes**: Human-readable by default, `--json` for scripts; success
  exit 0, usage errors exit 2, runtime/daemon errors exit 1 — consistent with existing CLI
  conventions (`cli/render.py`).
- **FR-8 — Confirmation feedback**: On set, report which keys changed and their new values,
  and whether the change was applied live or persisted-only (restart pending).

## Non-Functional Requirements
- **NFR-1 (Resiliency — inherited, full)**: A set is **atomic** w.r.t. `config.toml` (write
  via temp file + replace) so a crash mid-write cannot corrupt config. If live-apply fails
  while the daemon is up, the command reports a clear error and leaves a consistent state
  (either both persisted+applied, or neither — define precedence in design).
- **NFR-2 (Testability / PBT — inherited, full)**: Pure pieces (URL validation, config.toml
  read-modify-write round-trip, change computation) are unit- and property-tested
  (round-trip / idempotence properties). Process/daemon HTTP paths validated in Build & Test.
- **NFR-3 (Security — extension off)**: No new auth surface; the Control API stays loopback
  (`127.0.0.1`) as today. `config.toml` keeps `600` perms.
- **NFR-4 (Consistency)**: Command shape, flags, output, and exit codes follow the existing
  `gateway` / `agent config` patterns for a uniform CLI.

## Out of Scope
- Editing keys other than `upstream_base_url` / `default_model` (binds, advertise host,
  `upstream_auth`, timeouts) — deferred.
- Network probing / model-existence checks before applying (Q5 = A chose light validation).
- Per-agent upstream overrides (already a separate, existing concern).

## Key Requirements Summary
A new `caduceus gateway config` command: `--get`/`--json` to view, `--upstream-url` /
`--model` to set. Sets are validated (light), persisted atomically to `config.toml`, and —
when the daemon is running — **hot-applied to the live gateway without a restart**; when it
is down, the file edit alone suffices. Behaviour, output, and exit codes mirror the existing
CLI. Resiliency + PBT extensions apply (atomic write, property tests); Security extension off.
