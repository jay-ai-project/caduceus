# U7 — Domain Entities (Performance & Stability)

Technology-agnostic entities/value-objects for U7. Reuses the existing shared contract
(`AgentRecord`, `Lifecycle`, `HealthStatus`) — **no breaking model changes**; failure detail is
carried in the existing `AgentRecord.last_health.detail`.

## E1 — Lifecycle (existing enum, U7 transition semantics)
`creating | running | stopped | failed | registered(remote)`.

U7 makes the async transitions first-class:

```
            create()                 provision ok           warm-up (no LLM)
   (none) ─────────────▶ creating ───────────────▶ running ───────────────▶ running+healthy
                            │                          ▲                          │
              provision fail│                          │ boot/agent start         │ agent stop
                            ▼                          │                          ▼
                         failed  ◀─ reconcile(missing) │                       stopped
                                                        └── reconcile(sbx=running)
```

- **healthy** is NOT a lifecycle value — it is `last_health.level == healthy` while `lifecycle == running`.
  "running + healthy" (the user's chat-ready signal) = both conditions.
- `creating` is a *transient, in-progress* state owned by the background provisioning job (E3).

## E2 — SandboxSnapshot  (new value object)
A single point-in-time projection of the sandbox runtime, captured by **one** `sbx ls --json`.

- Shape: `Mapping[sandbox_name → RuntimeStatus]` where `RuntimeStatus ∈ {running, stopped}`.
- A sandbox absent from the snapshot ⇒ `missing` (only meaningful when the snapshot capture
  **succeeded**; see `ok` flag).
- Carries an `ok: bool` — `False` when the underlying `sbx ls` errored/timed out. When `ok == False`
  the snapshot is **non-authoritative**: callers MUST NOT downgrade lifecycle from it (BR-P2).
- Produced by `Provisioner.list_statuses() -> SandboxSnapshot`; consumed by lifecycle reconcile
  (L1/L5) and shallow health (L1). Replaces per-agent `status()` calls inside a single `list`.

## E3 — ProvisioningJob  (new, in-memory only)
Tracks a background `create` in flight; never persisted (the persisted `creating` lifecycle is the
durable signal).

- Fields: `name`, `task` (the scheduled async job), `started_at`.
- Owned by `AgentService` in a `_jobs: dict[name → ProvisioningJob]` (+ a task set so the loop keeps
  a strong reference).
- Purpose: (a) prevent duplicate concurrent create for the same name; (b) allow best-effort
  await/observe on daemon shutdown; (c) let `--wait` / SSE attach to progress.
- Terminal: on success or failure the job is removed; the record's lifecycle (`running`/`failed`)
  is the lasting result.

## E4 — WarmupState  (implicit, on the ChatService pool)
The existing `_Pooled` transport entry, but now possibly **created ahead of the first user turn** by
the warm-up step. A warmed entry has an open ACP process with `initialize` + `session/new` already
done and `session_id` persisted. First user turn reuses it (BR-P7). No new type — warm-up just
pre-populates `ChatService._pool`.

## E5 — HealthStatus (existing) — detail carries failure/reconcile cause
- Provisioning failure ⇒ `HealthStatus(level=unhealthy, shallow=False, detail="create failed: …")`
  stored on the failed record so `agent ls` shows the cause.
- Non-authoritative snapshot ⇒ `HealthStatus(level=unknown, detail="sbx status unavailable")` without
  changing lifecycle.

## Relationships
- `AgentService` — orchestrates E1 transitions, owns E3 jobs, consumes E2 snapshots, triggers E4
  warm-up (via an injected ChatService warm hook), writes E5 onto records.
- `Provisioner` — produces E2 (`list_statuses`) and single `status`.
- `ChatService` — owns E4 (`warm(name)` + pool); exposes `close_agent`/`close_all` (stdio only).
- `Supervisor` — reads E1 to decide who to supervise (only `running`); reads E5/E2 for health.
- `GatewayService` — shutdown leaves sandboxes intact; boot runs the one-shot reconcile (L5) over E2.
