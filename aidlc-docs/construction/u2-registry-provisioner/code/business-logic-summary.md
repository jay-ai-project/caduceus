# U2 — Business Logic Summary (code)

## Created (application code at workspace root)
| File | Purpose |
|---|---|
| `caduceus/common/models.py` | `AgentRecord` (+`serve_auth`), `AgentKind`/`Lifecycle`/`HealthLevel`, `HealthStatus`; explicit `to_dict`/`from_dict` (round-trip) |
| `caduceus/agents/names.py` | **PURE** `validate_name` (BR-A1), `sandbox_name="cad-"+name` (BR-A2) |
| `caduceus/agents/tokens.py` | `mint_token` (secrets, BR-A4) |
| `caduceus/agents/hermes_config.py` | **PURE** `render_hermes_config` (provider→AI-Gateway, BR-A5), `remote_setup_guidance` (Q2=A) |
| `caduceus/agents/registry.py` | Registry/StateStore — atomic JSON, `asyncio.Lock`, CRUD, **`token_lookup`** (U1 dependency), perms 600 (BR-A8) |
| `caduceus/agents/service.py` | `AgentService` — create **saga + compensation** (BR-A7), register, list (reconcile), remove, stop/start (remote→error, BR-A10) |

## Tests
- Unit: `test_names.py`, `test_models.py`, `test_registry.py`, `test_agent_service.py` (create happy/duplicate/rollback, provider-config invariant, register guidance, remove teardown, remote stop/start rejected, local stop/start).
- PBT (`tests/pbt/test_registry_properties.py`): P-U2-1 round-trip, P-U2-2 name invariant, P-U2-6 token entropy, **P-U2-5 stateful sequence driving the REAL AgentService+Registry vs a reference model** (uniqueness, valid transitions, persisted==in-memory, remote start/stop blocked — PBT-06).

## PBT outcome
- Stateful property (P-U2-5) exercises the real service over random create/register/stop/start/remove sequences — passed.
- PBT flagged a mis-specified token property (asserted a 32-char floor for 16-byte tokens); tightened to the actual usage (≥32 bytes) + `len ≥ nbytes`. No production bug.

## Requirement traceability
- FR-A1 create · FR-A2 register · FR-A3 list · FR-A4 remove · FR-A5 stop/start · FR-A6 names · FR-L2 health.
- Resiliency: saga/compensation, atomic state — RESILIENCY-10/12.
