# U7 — Business Rules (Performance & Stability)

Traceability: each rule maps to a requirement (FR-U7-*) and is covered by a test in Build & Test.

## Performance & listing
- **BR-P1** — `AgentService.list(probe=True)` performs **at most one** `sbx ls` invocation per call.
  The resulting snapshot is reused for lifecycle reconcile **and** shallow health of every local
  agent. `probe=False` performs zero `sbx` calls. *(FR-U7-1)*
- **BR-P2** — If the sandbox snapshot capture fails (`sbx ls` error/timeout ⇒ `snapshot.ok == False`),
  lifecycle MUST NOT be downgraded. Records keep their last-known lifecycle; health is set to
  `unknown` with a `detail`. No mass-flip to `failed`. *(FR-U7-6 robustness)*
- **BR-P3** — Reconcile mapping from an authoritative snapshot: `running → running`;
  `stopped(present) → stopped`; `missing → failed`. A `creating` record is exempt (job in flight).
  *(FR-U7-1/FR-U7-6)*

## Async create & warm-up
- **BR-P4** — `agent create` registers the record as `creating` and returns **before** provisioning
  completes, unless `--wait` is given. `agent ls` reflects the live `creating → running → healthy`
  progression. *(FR-U7-2)*
- **BR-P5** — The background provisioning saga is **fault-isolated**: any failure sets
  `lifecycle=failed` with a concise `last_health.detail`, runs the compensating sandbox removal, and
  never propagates to crash the daemon. *(FR-U7-2, NFR-Resil-1)*
- **BR-P6** — On successful provisioning, the agent transitions `creating → running`, then a
  **no-LLM** ACP warm-up (`initialize` + `session/new`) runs and seeds the ChatService pool. Warm-up
  failure leaves the agent `running` (lazy re-warm on first chat) and is logged, not fatal.
  *(FR-U7-3)*
- **BR-P7** — An agent shown `running` + `healthy` in `agent ls` is chat-able with **no** provisioning
  wait; the warmed pooled transport is reused on the first turn. *(FR-U7-4)*
- **BR-P12** — A `create` for a name already present in the registry **or** with a ProvisioningJob in
  flight is rejected (no duplicate/concurrent provisioning). *(FR-U7-2)*
- **BR-P13** — Warm-up, health checks, reconcile, and supervision sweeps MUST NOT spend an LLM
  completion. *(NFR-Resil-3)*

## Lifecycle decoupling & reconnect
- **BR-P8** — Daemon shutdown (`gateway stop` / SIGTERM) MUST NOT stop or remove any sandbox. It may
  only stop the Supervisor and tear down pooled `hermes acp` stdio processes (which re-spawn on
  demand). No `sbx stop` / `sbx rm` on the shutdown path. *(FR-U7-5)*
- **BR-P9** — On `gateway start`, a one-shot reconcile from a single `sbx ls` snapshot sets each local
  agent's lifecycle to its runtime truth; still-running sandboxes become `running` and are immediately
  chat-able. The reconcile is idempotent and fault-isolated. *(FR-U7-5)*
- **BR-P10** — Only explicit `agent stop` / `agent rm` may stop / remove a sandbox. *(FR-U7-5)*
- **BR-P11** — The Supervisor applies restart / back-off / circuit-breaker logic **only** to agents in
  `running` lifecycle. `creating`, `stopped`, `failed`, and remote agents are exempt (no restart), so
  supervision never fights the background provisioner or revives a deliberately-stopped agent.
  *(FR-U7-2/FR-U7-5 interplay)*

## Compatibility & invariants (preserved)
- **BR-P14** — Existing contracts remain backward compatible: `AgentRecord`/`Lifecycle` serialization
  round-trips (`from_dict(to_dict(x)) == x`); the chat fail-fast gate, session continuity (BR-C1..C4),
  and the terminal-event invariant (normalize_stream) are unchanged. The Web UI `probe=false` fast
  path is unaffected. *(NFR-U7-Compat)*
- **BR-P15** — `POST /agents` keeps its SSE contract; the non-blocking default emits an early
  `accepted`/`done` event carrying the `creating` record, while `?wait=true` streams full progress to
  a terminal `done`/`error` (current behavior). *(FR-U7-2, NFR-U7-Compat)*

## PBT coverage map
| Property | Rules | Kind |
|---|---|---|
| PBT-P1 reconcile totality | BR-P2, BR-P3 | Hypothesis (pure) |
| PBT-P2 async state machine | BR-P4, BR-P5, BR-P6 | Hypothesis (stateful ref-model) |
| PBT-P3 single-snapshot invariant | BR-P1 | Hypothesis (counting fake) |
| PBT-P4 shutdown safety | BR-P8 | stateful/unit |
