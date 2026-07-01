# U7 — Business Logic Model (Performance & Stability)

Technology-agnostic logic for the six U7 FRs. Method names are indicative; final signatures land in
Code Generation. Injected collaborators keep units decoupled (as today).

---

## L1 — Fast `agent ls` via a single snapshot  (FR-U7-1, FR-U7-6)

`AgentService.list(deep=False, probe=True)`:

1. If `probe` is False → return the registry projection unchanged (Web UI fast path — untouched).
2. If `probe` is True:
   a. `snap = await provisioner.list_statuses()` — **exactly one** `sbx ls --json` (E2).
   b. For each `rec`:
      - **local**: `reconcile_lifecycle(rec, snap)` (L-helper, BR-P2/P3); then
        `rec.last_health = await health.check(rec, deep, sandbox_status=snap.get(rec.sandbox_name))`
        — the shallow branch consumes the passed status instead of re-probing `sbx`.
      - **remote**: unchanged (endpoint reachability; deep transport probe when `deep`).
   c. Return the records.

`reconcile_lifecycle(rec, snap)`:
- If `not snap.ok` → **do not change lifecycle**; set `rec.last_health = unknown("sbx status unavailable")`. (BR-P2)
- If `rec.lifecycle == creating` → leave as-is (job in flight; BR-P3).
- Else map: `running → running`; `stopped(present) → stopped`; `missing → failed`. (BR-P3)

`HealthChecker.check(rec, deep=False, sandbox_status=None)`:
- Local shallow: `shallow = (sandbox_status or await p.sandbox_status(rec.sandbox_name)) == "running"`.
  When `sandbox_status` is supplied (from L1), **no** `sbx` call is made. Rest of the method unchanged
  (deep upstream/transport only when `deep`, still no LLM spend).

**Effect**: `list` cost = 1 `sbx ls` regardless of N (was 2×N).

---

## L2 — Background (async) `create`  (FR-U7-2, FR-U7-5-fail)

`AgentService.create(name, wait=False, progress=None)`:

1. `validate_name`; reject if `registry.get(name)` exists **or** a ProvisioningJob is in flight (BR-P12).
2. Mint token; register `rec = AgentRecord(…, lifecycle=creating)` and persist **immediately**.
3. Define coroutine `_provision(rec, token, progress)` (L2a).
4. If `wait` → `await _provision(...)`, return the final rec (streams progress as today).
5. Else → schedule `_provision` on the running loop, store a `ProvisioningJob` (+ strong task ref),
   and **return the `creating` rec now**. (BR-P4)

`_provision(rec, token, progress)` — the saga (fault-isolated, BR-P5):
```
try:
    emit("preparing image");   tag = images.ensure_image(...)
    emit("creating sandbox");  provisioner.create_sandbox(sb, tag, {OPENAI_API_KEY: token})
    emit("configuring agent"); provisioner.write_file(sb, HERMES_CONFIG_PATH, render_hermes_config(...))
    rec.lifecycle = running; rec.updated_at = now; registry.upsert(rec)        # visible in `agent ls`
    emit("warming up");        await _warm(rec)                                # L3, no LLM
    rec.last_health = HealthStatus(healthy, shallow=True); registry.upsert(rec)
except Exception as exc:
    log.warning(...);  await _safe_remove(sb)                                  # compensation
    rec.lifecycle = failed
    rec.last_health = HealthStatus(unhealthy, shallow=False, detail=f"create failed: {exc}")
    rec.updated_at = now; registry.upsert(rec)                                 # cause visible in `agent ls`
finally:
    _jobs.pop(rec.name, None)
```
- `emit(phase)` pushes to the SSE queue when `wait`/attached, and always logs. Background progress is
  observable indirectly through the persisted lifecycle + `agent ls`.

---

## L3 — Chat-ready warm-up (no LLM spend)  (FR-U7-3, FR-U7-4)

`ChatService.warm(name) -> None` (new; injected into AgentService as `warm_hook`):
- Resolve `rec`; if not local or sandbox not running → no-op.
- Get-or-create the pooled `_Pooled(transport)`; `await transport.open()` → `initialize` +
  `session/new` (or `session/load` if a session exists). Persist the new `session_id` (BR-C1 reuse).
- Leave the transport **open in the pool** so the first user turn reuses it (BR-P7).
- Best-effort: any exception is caught + logged; the agent stays `running` and re-warms lazily on the
  first chat (BR-P6). No LLM completion is issued (warm-up stops at `session/new`).

`AgentService` calls `warm_hook(rec.name)` at the end of a successful `_provision`, and (optionally)
during boot reconcile for already-running agents (lazy is acceptable).

---

## L4 — Decoupled daemon shutdown  (FR-U7-5, BR-P8)

`GatewayService._serve._run()` `finally`:
- `await supervisor.stop()`
- `await chat_service.close_all()` — tears down pooled **acp stdio processes only** (`_kill`
  terminates the `sbx exec … hermes acp` client; the `sbx` container is untouched).
- **No** `provisioner.stop(...)` / `provisioner.remove(...)` anywhere on the shutdown path.
- Best-effort await of in-flight ProvisioningJobs with a short bounded timeout (so a half-created
  sandbox finishes or is compensated), then proceed. (Note: existing shutdown is already
  sandbox-safe; U7 makes this explicit + adds boot reconcile below.)

---

## L5 — Boot reconcile / reconnect  (FR-U7-5, BR-P9)

New `AgentService.reconcile_all()` (async), called once at daemon startup **inside the loop**
(in `_serve._run()` before `supervisor.start()`):
- `snap = await provisioner.list_statuses()` (one `sbx ls`).
- For each local `rec`: `reconcile_lifecycle(rec, snap)`; persist if changed.
- Running agents become/stay `running` and are immediately chat-able (warm lazily on first turn, or
  eagerly `warm(name)` — configurable; default lazy to keep boot fast).
- Idempotent and fault-isolated (a failed snapshot leaves state untouched, BR-P2).

---

## L6 — Supervisor interplay  (BR-P11)

`Supervisor._sweep` currently supervises every local agent. U7 scopes it:
- Only agents with `lifecycle == running` are eligible for health-driven restart/backoff/circuit.
- `creating` (job in flight), `stopped`, `failed` (and remote) are **skipped** — so the supervisor
  never fights the background provisioner or "restarts" a deliberately-stopped agent.
- Shallow reconcile inside the sweep may reuse `list_statuses` too (optional optimization).

---

## Data flow summary
```
CLI create ──▶ POST /agents (wait?) ──▶ AgentService.create
                                          ├─ persist creating (return now)
                                          └─ bg _provision ─▶ running ─▶ warm(no LLM) ─▶ healthy
CLI ls   ──▶ GET /agents?probe=true ──▶ AgentService.list ─▶ 1× sbx ls snapshot ─▶ reconcile+shallow
gateway start ──▶ _serve._run ──▶ reconcile_all (1× sbx ls) ─▶ supervisor.start (running-only)
gateway stop  ──▶ SIGTERM ──▶ supervisor.stop + close_all(stdio) ; sandboxes untouched
```

## PBT targets (Hypothesis)
- **PBT-P1 (reconcile totality)**: for any generated snapshot (arbitrary/malformed mapping, `ok`
  true/false) and any starting `Lifecycle`, `reconcile_lifecycle` returns a valid `Lifecycle` and
  never raises; `ok=False` never downgrades lifecycle. (BR-P2/P3)
- **PBT-P2 (async state machine)**: a reference model of `_provision` — success ⇒ creating→running→
  healthy; injected failure ⇒ creating→failed with detail + compensation called exactly once; never
  running→stopped without an explicit stop. (BR-P4/P5/P6)
- **PBT-P3 (single-snapshot invariant)**: a counting fake Provisioner asserts `list(probe=True)` over
  N agents calls `list_statuses` exactly once and per-agent `status`/`sandbox_status` zero times;
  `probe=False` calls it zero times. (BR-P1)
- **PBT-P4 (shutdown safety)** *(stateful/unit)*: across arbitrary pool/agent states, the shutdown
  path invokes neither `provisioner.stop` nor `provisioner.remove`. (BR-P8)
