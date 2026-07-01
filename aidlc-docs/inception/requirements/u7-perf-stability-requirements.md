# U7 — Performance & Stability — Requirements

## Intent Analysis
- **User request**: Evaluate and improve Caduceus overall performance & stability. Specifically:
  (1) `agent ls` health/status check is far too slow for what it does; (2) an agent only "boots" on
  the first chat — `create` should provision it to a chat-ready state; (3) `create` should not block
  synchronously — provision in the background so `agent ls` shows live state, and once an agent is
  `running`+`healthy`, `agent chat` starts instantly; (4) status is sometimes mis-reported, and
  stopping only the gateway shouldn't stop individual agents — a restarted daemon should reconnect
  to still-running agents.
- **Request type**: Enhancement + Bug fix + Performance/Refactoring (brownfield).
- **Scope**: Multiple components — `caduceus/agents` (service, health, provisioner), `caduceus/transport`
  (chat pool, supervisor), `caduceus/daemon` (gateway, wiring, control_api), `caduceus/cli`.
- **Complexity**: Moderate. Mostly additive + targeted refactors; the async-create path and the
  boot-time reconcile are the main new mechanisms.
- **Cycle**: U7 (follows U1–U6 + Web UI). **Extensions inherited**: Security = No; Resiliency = Yes
  (full); PBT = Yes (full).

## Confirmed Decisions (from verification questions, all = A)
- **Q1 = A** — `agent create` returns immediately; agent shows `creating` and a background task drives
  it to `running` → warmed → `healthy`, with `agent ls` reflecting live state. Add `--wait` to block.
- **Q2 = A** — Chat-ready warm-up = **full ACP protocol warm-up, no LLM spend** (`initialize` +
  `session/new`), keeping the warmed transport pooled for the first turn.
- **Q3 = A** — `agent ls` fixed via a **single batched `sbx ls` snapshot** per call, reused for both
  lifecycle reconcile and shallow health (no per-agent re-probe).
- **Q4 = A** — **Fully decouple** daemon lifecycle from sandbox lifecycle: `gateway stop` leaves
  sandboxes running; only `agent stop`/`agent rm` stop/remove them; `gateway start` reconciles from
  `sbx ls` and marks still-running sandboxes `running`/`healthy`.
- **Q5 = A** — Background provisioning failures set `lifecycle=failed` with a short error `detail`
  visible in `agent ls`; compensation cleanup still runs; recover via `agent rm` + recreate.

---

## Functional Requirements

### FR-U7-1 — Fast `agent ls` (single-snapshot projection)
- `AgentService.list(probe=True)` MUST fetch the sandbox runtime state **once** per call (one
  `sbx ls --json`) and reconcile lifecycle **and** compute shallow health for every local agent from
  that single in-memory snapshot.
- No code path in a single `list` may spawn `sbx ls` more than once. Deep health (remote transport
  probe, upstream check) MAY still run per-agent only when `deep=True`.
- Target: `agent ls` wall-time ≈ one `sbx ls` (~seconds total), independent of agent count N, versus
  today's 2×N.

### FR-U7-2 — Background (async) `create`
- `agent create <name>` MUST return promptly after the record is registered in `creating` state; it
  MUST NOT block on image/sandbox provisioning by default.
- A background task MUST run the full provisioning saga (ensure image → create sandbox → write config
  → warm-up), transitioning the persisted record `creating` → `running` → (warmed) `healthy`.
- `agent ls` MUST reflect the live in-progress state (`creating`, then `running`/`healthy`).
- An opt-in `--wait` flag MUST make the CLI block (streaming progress, as today) until the agent is
  ready or fails, preserving script-friendly behavior.

### FR-U7-3 — Chat-ready warm-up (no LLM spend)
- After the sandbox is running and configured, the background task MUST warm the agent to a
  chat-ready state by opening its pooled ACP transport (`initialize` + `session/new`) so the first
  real `agent chat` turn skips cold start.
- Warm-up MUST NOT spend an LLM completion.
- The warmed transport MUST be retained in the ChatService pool so the first user turn reuses it.
- Warm-up failure MUST NOT by itself fail an otherwise-running agent (best-effort; it can re-warm
  lazily on first chat) — but a fully failed provision follows FR-U7-6.

### FR-U7-4 — "running + healthy ⇒ chat works now" guarantee
- When `agent ls` shows an agent as `running` and `healthy`, `agent chat` MUST be able to start
  immediately without a provisioning wait.
- The chat fail-fast gate MUST remain correct for `creating` (transient retry) and `failed`
  (reject with guidance) states.

### FR-U7-5 — Decoupled gateway/agent lifecycle + reconnect on restart
- Stopping the daemon (`gateway stop`, SIGTERM) MUST NOT stop or remove any agent sandbox. Graceful
  shutdown MAY tear down pooled `hermes acp` stdio processes (they re-spawn on demand) but MUST NOT
  invoke `sbx stop`/`sbx rm`.
- On `gateway start`, the daemon MUST reconcile persisted records against the live `sbx ls` snapshot:
  a still-running sandbox ⇒ `running`; a stopped-but-present sandbox ⇒ `stopped`; a missing sandbox ⇒
  `failed` (or `stopped`, per design). Reconnected running agents MUST be immediately chat-able
  (warm lazily or on boot).
- Only explicit `agent stop` / `agent rm` may stop/remove a sandbox.

### FR-U7-6 — Correct status reporting & background-failure surfacing
- Lifecycle reconcile MUST derive from the single `sbx ls` snapshot as the single source of truth,
  eliminating the current mis-report (e.g. a present sandbox spuriously shown `failed`/`stopped`).
- A background provisioning failure MUST set `lifecycle=failed` with a concise error `detail`
  surfaced in `agent ls` (human + `--json`); compensation (sandbox cleanup) MUST still run per the
  existing saga. Recovery path: `agent rm` + recreate.

---

## Non-Functional Requirements

- **NFR-U7-Perf-1**: `agent ls` cost is O(1) in `sbx` invocations (one `sbx ls` per call), not O(N).
- **NFR-U7-Perf-2**: `agent create` returns to the shell in well under the provisioning time (no
  1800s blocking by default).
- **NFR-U7-Perf-3**: First `agent chat` after a `healthy` create incurs no ACP cold-start (warm path).
- **NFR-U7-Resil-1 (Resiliency, full)**: Background provisioning is fault-isolated — a failure never
  crashes the daemon; it transitions the one agent to `failed` and compensates. (RESILIENCY-10/-12.)
- **NFR-U7-Resil-2**: Daemon shutdown is graceful and leaves external state (sandboxes) intact
  (durability); boot reconcile is idempotent and self-healing. (RESILIENCY-06/-12.)
- **NFR-U7-Resil-3**: No LLM spend on health, warm-up, or supervision sweeps.
- **NFR-U7-PBT-1 (PBT, full)**: Property tests cover the new state machine transitions
  (`creating→running→healthy`, `→failed`), snapshot-based reconcile totality (any `sbx ls` shape →
  a valid lifecycle, never crash), and the "one `sbx ls` per list" invariant.
- **NFR-U7-Compat**: Existing CLI/Control-API/Web-UI contracts remain backward compatible; the Web UI
  `probe=false` fast path is unaffected or improved.

## Out of Scope
- No change to the AI-Gateway request/routing path (U1/U6) beyond what decoupling requires.
- No new remote-agent lifecycle capabilities (remote start/stop remains unsupported — BR-A10).
- No multi-host / clustering.

## Success Criteria
- `agent ls` completes in ≈ one `sbx ls` regardless of N; status matches reality.
- `agent create` returns immediately; `agent ls` shows `creating` → `running`/`healthy`; first chat
  on a `healthy` agent starts with no cold-start stall.
- `gateway stop` then `gateway start` leaves agents running and immediately chat-able; no spurious
  `stopped`/`failed`.
- All existing tests pass; new unit + PBT cover the async-create state machine, snapshot reconcile,
  and lifecycle decoupling.
