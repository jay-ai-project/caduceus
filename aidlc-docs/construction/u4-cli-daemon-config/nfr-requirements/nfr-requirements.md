# U4 CLI / Daemon / Config — NFR Requirements

Cross-cutting NFRs (requirements.md) + global stack are inherited from U1. This records
**U4-specific** targets/tunable defaults. **No new clarifying questions** — the stack is
locked and U4 NFRs derive from the Functional Design answers (Q1–Q6) and inherited scope.
U4 is where the project-wide cross-cutting NFRs (usability, observability, security,
maintainability) are primarily *realized* (per the unit map).

## Usability (NFR-1) — U4 owns the primary UX surface
- **U-1** Human-readable default output + `--json` for scriptable commands; consistent verbs (`agent …`, `gateway …`).
- **U-2** Actionable errors: every failure prints what happened + the next step (e.g. daemon-down → "run `caduceus gateway start`"; upstream unset → config guidance). Exit codes total: 0 / 2 (usage) / 1 (runtime).
- **U-3** First-run smoothness: interactive config bootstrap (Q3) prompts once and persists to `config.toml`.
- **U-4** Streaming chat feels live: tokens render as they arrive; Ctrl-C cancels cleanly (U3 cooperative cancel).

## Reliability / Lifecycle (RES-4/RES-5, RESILIENCY-10)
- **R-1 Single instance**: pid/lock in `~/.caduceus` prevents double-start; stale lock (dead pid) reclaimed.
- **R-2 Graceful stop**: stop Supervisor → drain in-flight → close transports → release lock; idempotent.
- **R-3 Signal handling**: SIGINT/SIGTERM → graceful `stop()`; daemonized child writes logs to `~/.caduceus/logs/daemon.log`.
- **R-4 Daemon never crashes on a single agent/op failure**: Control API handlers convert errors to JSON responses; the AI-Gateway / Supervisor degrade gracefully (inherited U1/U3).
- **R-5 Split listeners isolation**: Control API (loopback) and AI-Gateway (bridge) run independently; one listener’s load doesn’t starve the other (async).

## Security (NFR-6; baseline, Security ext OFF)
- **SEC-1 Loopback control plane**: Control API binds `127.0.0.1` only, no auth (local trust); never bind a routable iface.
- **SEC-2 Secret hygiene**: `token`/`serve_auth` never printed, logged, or projected into `AgentView`/JSON (BR-O3); logs route through the redacting logger.
- **SEC-3 Config bootstrap secrets**: `config.toml` written with restrictive perms (600) consistent with U2 state-file hygiene.

## Performance
- **P-1 CLI latency**: control-plane calls are small loopback HTTP; perceived latency dominated by the underlying op (provisioning, LLM). Show progress for long ops (create/build).
- **P-2 Status**: `gateway status` is a cheap read (no LLM, cached health where available).
- **P-3 Streaming**: chat/logs SSE pass-through (no buffering), consistent with U3/U2.

## Observability (RES-6 / RESILIENCY-05)
- **O-1** Daemon writes a structured (redacted) log file; lifecycle events (start/stop/lock/bootstrap) logged.
- **O-2** `agent logs [-f]` surfaces per-agent hermes logs (FR-L1) via the U2 Provisioner. Metrics/traces/dashboards N/A (personal tool).

## Maintainability / Testability (NFR-5, PBT)
- **M-1 Thin handlers**: CLI handlers and Control API routes are thin adapters over services (U1/U2/U3); business logic stays in the services → routes/handlers unit-testable with an in-process ASGI client + fakes.
- **M-2 Pure config reducer**: `apply_change` is pure (no I/O) → property-tested (PBT-U4-2) independent of the sandbox.
- **M-3 PBT (PBT-01/09)**: 6 U4 properties (DTO round-trip, idempotent/order-independent reducer, no-secret projection, remote read-only, reload-strategy totality, exit-code totality). Hypothesis + seed logging (PBT-08).
- **M-4 Composition seams**: provisioner/transport/clock injected so the daemon wiring and ConfigEditor are testable without real Docker/hermes; real paths in Build & Test.

## Resiliency scope realized / referenced in U4
- RESILIENCY-10 (isolation) → R-4/R-5; RESILIENCY-05 (observability) → O-1/O-2; RES-4/RES-5 supervision is U3’s, **wired** here (BR-W1/W2).

## Out of scope (v1)
- Control-plane auth / multi-user; remote config editing (FR-E2 read-only); systemd unit (direct run + `-d` only); per-agent upstream override (FR-P4 designed-for, v2); Windows-native daemonization (WSL2/Linux target).
