# U4 CLI / Daemon / Config — Business Rules

IDs: `BR-G*` (gateway/daemon), `BR-E*` (config edit), `BR-L*` (logs), `BR-O*` (output/CLI).
Each rule is technology-agnostic and traces to a requirement.

## Daemon / gateway (FR-G1..G4)
- **BR-G1** — caduceus runs as a long-lived daemon hosting three planes: Control API (loopback), AI-Gateway (bridge iface), registry/supervisor (FR-G1/G3).
- **BR-G2 (Q1)** — `gateway start` runs **foreground by default**; `-d/--daemon` detaches a background child (new session; stdout/stderr → `~/.caduceus/logs/daemon.log`) and returns the pid.
- **BR-G3** — **Single instance per host**: a pid/lock file in `~/.caduceus` prevents a second daemon; a stale lock (dead pid) is reclaimed. Starting when already running → clear error.
- **BR-G4 (FR-G4)** — the Control API binds **loopback only** (`127.0.0.1:9700`), no auth (local trust); the AI-Gateway binds the bridge iface with per-agent bearer auth (unchanged from U1). The CLI is the only Control API client.
- **BR-G5** — `stop` is **graceful and idempotent**: stop the Supervisor, drain in-flight requests, close transports, release the lock; stopping when not running is a no-op with a clear message.
- **BR-G6 (Q3)** — if required Settings (`upstream_base_url`/`default_model`) are missing: foreground+TTY → prompt and persist to `~/.caduceus/config.toml`; non-interactive/daemonized → fail with `ConfigError` guidance. Precedence stays env > file > default.
- **BR-G7** — `status` never mutates state and works whether the daemon is up or down (reports `running=false` when down).

## Config edit (FR-E1..E3)
- **BR-E1** — `agent config` edits apply to **local** agents only (skills/soul/tools/core). Remote agents are **read-only** in v1 → `set_config` raises a clear "not supported" error (FR-E2).
- **BR-E2 (Q5)** — soul may be supplied via `--soul-file <path>` (file contents) **or** inline `--soul "<text>"`; supplying **both** is rejected as ambiguous. skills via `--add-skill`/`--remove-skill`, tools via `--enable-tool`/`--disable-tool`, core via `--set key=value`. `--get`/`--json` returns the current `ConfigSnapshot`.
- **BR-E3** — config edits are computed by a **pure reducer** `apply_change(snapshot, change)` that is idempotent and order-independent (adding an existing skill is a no-op; enabling a tool removes it from `disabled` and vice-versa).
- **BR-E4 (Q2)** — changes take effect via **hot-reload by default** (apply files + signal hermes to reload, **no** serve restart). Affected change kinds resolve a `ReloadStrategy` via `CHANGE_KIND_STRATEGY` (v1: all → `hot_reload`).
- **BR-E5 (Q2 seam)** — `CHANGE_KIND_STRATEGY` is the **single seam** for later forcing specific kinds to `restart_serve`; flipping a kind there makes its edits reuse the U3/U2 serve-restart path with no other code change. The effective strategy for a multi-kind edit is the strongest among affected kinds.
- **BR-E6 (Q4)** — after applying, caduceus **reads back** the in-sandbox config to confirm intended values and runs a shallow health check post-reload; `ConfigResult.verified` reflects this (AC-6). Failure → `verified=false` + actionable detail, no silent success.

## Logs (FR-L1)
- **BR-L1** — `agent logs [-f]` streams the agent's hermes logs from the sandbox (local). Remote-agent logs are unavailable in v1 with a clear message. Streaming is SSE; `-f` follows.

## Output / CLI conventions (Q6)
- **BR-O1** — Default output is **human-readable** (tables/sentences); `--json` emits machine-readable JSON for scriptable commands (`agent ls`, `gateway status`, `agent config --get`).
- **BR-O2** — Errors go to **stderr** with **non-zero exit codes**: `0` success, `2` usage/validation error, `1` runtime/upstream/daemon failure. Mapping is total (every outcome maps).
- **BR-O3 (secret hygiene)** — `token`/`serve_auth` are **never** printed or included in any output/JSON (`AgentView` omits them); logs route through the redacting logger (inherited NFR-6/SEC).
- **BR-O4** — `chat` streams tokens as they arrive (no full-response buffering, consistent with U3 BR-C6); Ctrl-C triggers cooperative cancel (U3 BR-C10) and exits cleanly.

## Composition / wiring
- **BR-W1** — U4 is the **only** place U1/U2/U3 are concretely wired: it injects U3's callables (`list_agents`/`health_check`/`restart`/`mark_failed`) and binds U1's `token_lookup` to `Registry.token_lookup`. Units below remain decoupled (no cross-unit imports beyond declared interfaces).
- **BR-W2** — `restart(rec)` (for the Supervisor) is implemented here as U2 `Provisioner.start_serve` re-launch + port re-publish + `Registry.upsert`.

---

## Traceability
- FR-G1 → BR-G1 · FR-G2 → BR-G2/G5/G7 · FR-G3 → BR-G1/W1 · FR-G4 → BR-G4.
- FR-E1 → BR-E1/E2 · FR-E2 → BR-E1 · FR-E3 → BR-E4/E5/E6.
- FR-L1 → BR-L1. Output/UX → BR-O1..O4. AC-1 (gateway up) → BR-G2/G7; AC-6 (config verified) → BR-E6.
- Inherited: U1 split-listener/loopback (BR-G4), U2 BR-A10 remote no-stop/start (BR-E1), U3 BR-C6/C10 (BR-O4), NFR-6/SEC redaction (BR-O3).
