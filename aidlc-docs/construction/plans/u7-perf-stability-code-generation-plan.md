# U7 — Code Generation Plan (Performance & Stability)

**Single source of truth for U7 Code Generation.** Brownfield: modify existing files in-place (no
`_new`/`_modified` copies). Application code at repo root under `caduceus/`; tests under `tests/`;
markdown summaries under `aidlc-docs/construction/u7-perf-stability/code/`.

Traceability: FR-U7-1..6, BR-P1..P15, PBT-P1..P4 (see functional-design/).

---

## Step 1 — Provisioner: single-snapshot sandbox status  *(BR-P1, FR-U7-1)*
- [x] `caduceus/agents/provisioner.py`: add `SandboxSnapshot` value object (`statuses: dict[str,str]`,
      `ok: bool`; `.get(name) -> "running"|"stopped"|"missing"`).
- [x] Add `Provisioner.list_statuses() -> SandboxSnapshot` to the Protocol and `SbxProvisioner`
      (one `sbx ls --json`; on rc≠0/parse error → `SandboxSnapshot({}, ok=False)`).
- [x] Refactor `SbxProvisioner.status()` to delegate to `list_statuses()` (keep single-agent API).

## Step 2 — HealthChecker: accept a precomputed sandbox status  *(BR-P1)*
- [x] `caduceus/agents/health.py`: `check(rec, deep=False, sandbox_status: Optional[str]=None)`.
      Local shallow uses `sandbox_status` when provided (no `p.sandbox_status` call); otherwise
      unchanged. Deep path + remote path unchanged. Still no LLM spend.

## Step 3 — AgentService: fast list + async create + reconcile  *(FR-U7-1/2/6, BR-P2..P6, P12)*
- [x] `caduceus/agents/service.py`:
  - `reconcile_lifecycle(rec, snap)` helper (BR-P2/P3: `ok=False` → no downgrade + unknown health;
    `creating` exempt; running/stopped/missing→running/stopped/failed).
  - Rewrite `list(deep, probe)`: on `probe`, capture `snap = await provisioner.list_statuses()` **once**,
    then per local rec: `reconcile_lifecycle` + `health.check(rec, deep, sandbox_status=snap.get(...))`.
  - `async reconcile_all()` (L5): one snapshot, reconcile+persist all local recs; fault-isolated.
  - Split `create(name, wait=False, progress=None, spawn=create_task)`: register `creating`, persist;
    if `wait` → `await _provision`; else schedule `_provision` as a tracked ProvisioningJob and return
    the `creating` rec. Reject duplicate name **or** in-flight job (BR-P12).
  - `_provision(rec, token, progress)` = existing saga refactored: image→sandbox→config→
    `lifecycle=running`(persist)→`warm_hook(name)`(no-LLM, best-effort)→`last_health=healthy`(persist);
    on failure → compensation + `lifecycle=failed` + `last_health.detail` (persist). Fault-isolated.
  - Accept injected `warm_hook` (optional) in `__init__`; store `_jobs`/task set; expose
    `await_jobs(timeout)` for shutdown.

## Step 4 — ChatService: no-LLM warm-up  *(FR-U7-3, BR-P6/P13)*
- [x] `caduceus/transport/chat.py`: `async warm(name)` — resolve rec (local + sandbox running);
      get-or-create pooled `_Pooled`; `await transport.open()` (initialize + session/new/load);
      persist session_id; leave open in pool. Best-effort (catch+log); never raises; no prompt sent.

## Step 5 — Supervisor: supervise only running agents  *(BR-P11)*
- [x] `caduceus/transport/supervisor.py`: in `_sweep`, skip records whose `lifecycle != running`
      (creating/stopped/failed) before health/restart logic. Remote already skipped for restart.

## Step 6 — Wiring: inject warm hook + expose reconcile  *(BR-P6/P9)*
- [x] `caduceus/daemon/wiring.py`: pass `warm_hook=chat_service.warm` into `AgentService`
      (constructed after chat_service; keep `transport_closer` too). No behavior change to health probes.

## Step 7 — GatewayService: boot reconcile + explicit sandbox-safe shutdown  *(FR-U7-5, BR-P8/P9)*
- [x] `caduceus/daemon/gateway.py` `_serve._run()`: before `supervisor.start()`, `await
      services.agent_service.reconcile_all()` (fault-isolated). In `finally`, keep
      `supervisor.stop()` + `chat_service.close_all()` (stdio only); add bounded
      `await agent_service.await_jobs(timeout=…)`; assert no `provisioner.stop/remove` on this path.

## Step 8 — Control API: non-blocking create + `wait`  *(FR-U7-2, BR-P15)*
- [x] `caduceus/daemon/control_api.py` `POST /agents`: read `wait` (query or body). `wait=true` →
      current streamed progress→done/error. Default (`false`) → kick off `agents.create(..., wait=False)`,
      emit one `accepted` (or `done`) SSE event with the `creating` `AgentView`, then close.

## Step 9 — CLI: `--wait` flag + background UX  *(FR-U7-2)*
- [x] `caduceus/cli/client.py` `create_agent(spec, wait=False)` → pass `wait` param; yield events.
- [x] `caduceus/cli/app.py` `agent create`: add `--wait/--no-wait` (default no-wait). No-wait →
      after `accepted`, print `creating '<name>' in background — check \`caduceus agent ls\``. Wait →
      stream progress as today. `agent ls`/`chat` unchanged (already reflect live state).

## Step 10 — Tests (unit + PBT) + fakes  *(PBT-P1..P4, all BRs)*
- [x] `tests/fakes.py`: `FakeProvisioner.list_statuses()` (+ `ok` toggle, snapshot-call counter);
      `FakeHealthChecker.check(rec, deep, sandbox_status=None)`; a fake `warm_hook`/warmable ChatService.
- [x] `tests/unit/test_agent_service.py`: async create returns `creating` immediately; bg saga →
      running→healthy (+warm called); failure → failed+detail+compensation; `--wait` awaits;
      `list(probe=True)` reconciles from one snapshot; `reconcile_all`; duplicate/in-flight rejected;
      `ok=False` snapshot doesn't downgrade.
- [x] `tests/unit/test_chat_service.py`: `warm()` opens+pools+persists session, no prompt; best-effort
      on failure.
- [x] `tests/unit/test_supervisor.py`: creating/stopped/failed agents skipped; running supervised.
- [x] `tests/unit/test_control_api.py`: `POST /agents` default → accepted+creating; `wait=true` → progress→done.
- [x] `tests/unit/test_cli.py`: `--wait` vs default background message.
- [x] `tests/pbt/test_u7_properties.py` (new): PBT-P1 reconcile totality; PBT-P2 async state machine
      (ref model); PBT-P3 single-snapshot invariant; PBT-P4 shutdown safety.

## Step 11 — Docs  *(traceability)*
- [x] `aidlc-docs/construction/u7-perf-stability/code/code-summary.md`: files changed + rule coverage.
- [x] `README.md`: brief note — `agent create` provisions in background (`--wait` to block);
      `gateway stop` leaves agents running; restart reconnects.

---

### Story / requirement coverage
| Step | Requirements | Rules |
|---|---|---|
| 1,2,3(list),6 | FR-U7-1, FR-U7-6 | BR-P1,P2,P3 |
| 3(create),4,8,9 | FR-U7-2, FR-U7-3, FR-U7-4 | BR-P4,P5,P6,P7,P12,P13,P15 |
| 3(reconcile),5,7 | FR-U7-5 | BR-P8,P9,P10,P11 |
| 10 | all | PBT-P1..P4 |

**Scope**: 11 steps; ~8 source files modified (`agents/{provisioner,health,service}`, `transport/{chat,supervisor}`, `daemon/{wiring,gateway,control_api}`, `cli/{client,app}`), 1 new PBT file + fakes/unit test updates, README + code-summary. No new runtime dependency.
