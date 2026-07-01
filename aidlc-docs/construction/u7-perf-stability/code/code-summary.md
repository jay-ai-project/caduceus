# U7 — Code Generation Summary (Performance & Stability)

All 11 plan steps executed. Brownfield in-place modifications; no new runtime dependency.
**225 unit + PBT tests pass** (was 208; +17).

## Source changes

| File | Change | Rules |
|---|---|---|
| `caduceus/agents/provisioner.py` | New `SandboxSnapshot` (statuses + `ok`); `list_statuses()` (one `sbx ls`); `_parse_sbx_ls`; `status()` delegates to snapshot. | BR-P1, BR-P2 |
| `caduceus/agents/health.py` | `check(rec, deep, sandbox_status=None)` — reuses a batched status, no re-probe. | BR-P1 |
| `caduceus/agents/service.py` | `ProvisioningJob`; `create(name, wait=True, progress)` splits into register-`creating` + `_provision` saga (inline or background); `_warm` (no-LLM hook); `await_jobs`; `list` single-snapshot reconcile+shallow; `reconcile_all()`; `_reconcile_lifecycle`. | BR-P1..P6, P9, P12, P13 |
| `caduceus/transport/chat.py` | `warm(name)` — pre-open pooled ACP (initialize+session/new, no prompt), best-effort. | BR-P6, P13 |
| `caduceus/transport/supervisor.py` | `_sweep` supervises only `running` agents (skip creating/stopped/failed). | BR-P11 |
| `caduceus/daemon/wiring.py` | Inject `warm_hook=chat_service.warm` into `AgentService`. | BR-P6 |
| `caduceus/daemon/gateway.py` | `_serve._run()` boot `reconcile_all()`; sandbox-safe shutdown (stdio-only, `await_jobs`, no `sbx stop/rm`). | BR-P8, P9 |
| `caduceus/daemon/control_api.py` | `POST /agents?wait=` — default background `accepted` event; `wait=true` streams progress→done. | BR-P15 |
| `caduceus/cli/client.py` | `create_agent(spec, wait=False)` passes `wait` param. | BR-P4/P15 |
| `caduceus/cli/app.py` | `agent create --wait/--no-wait`; background UX message. | BR-P4 |
| `README.md` | Background create (+`--wait`); gateway stop leaves agents running / reconnect on start. | — |

## Tests

- `tests/fakes.py`: `FakeProvisioner.list_statuses()` (+`snapshot_ok` toggle, call marker);
  `FakeHealthChecker.check(..., sandbox_status=None)`; `FakeAgentService.create(wait, progress)`;
  `FakeControlAPIClient.create_agent(wait)` (accepted vs progress→done).
- `tests/unit/test_agent_service.py`: single-snapshot list; non-authoritative snapshot keeps lifecycle;
  background create returns `creating` then ready; background failure → failed+detail+compensation;
  duplicate/in-flight rejected; warm hook called; `reconcile_all` reconnects.
- `tests/unit/test_chat_service.py`: warm opens+pools (no prompt); warm failure swallowed; remote no-op.
- `tests/unit/test_supervisor.py`: creating/stopped/failed agents not supervised.
- `tests/unit/test_control_api.py`: default background `accepted`; `wait=true` progress→done.
- `tests/unit/test_cli.py`: default background message; `--wait` progress; `--wait --json` clean stdout.
- `tests/pbt/test_u7_properties.py` (new): PBT-P1 reconcile totality; PBT-P2 async state machine;
  PBT-P3 single-`sbx ls` invariant; PBT-P4 shutdown never stops sandboxes.

## Notes / deferred to Build & Test
- Real `sbx ls --json` parsing shape reused from the prior (Finding H) implementation.
- Live verification of: `agent ls` wall-time (1× `sbx ls`), background create progression in
  `agent ls`, warm first-chat latency, and `gateway stop`→`start` reconnect (agents stay running).
