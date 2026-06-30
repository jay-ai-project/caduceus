# U2 Registry & Provisioner — Code Generation Plan

**Unit**: U2. **Workspace root**: `/mnt/f/Workspace/Caduceus`. App code → root (never `aidlc-docs/`); summaries → `aidlc-docs/construction/u2-registry-provisioner/code/`.

## Unit context
- Implements FR-A1..A6, FR-L2 (+ hermes image). Provides `Registry.token_lookup` (U1 dependency).
- Buildable/testable in isolation: real Docker/sbx are behind interfaces (`Provisioner`, `ImageBuilder`) → **FakeProvisioner** in tests; integration with real sbx/docker is Build & Test.
- Inputs: U2 functional-design, nfr-design, infrastructure-design + shared-infrastructure.

## Target files (application code)
```
caduceus/common/models.py            # AgentRecord, AgentToken, enums, HealthStatus + (de)serialize
caduceus/agents/__init__.py
caduceus/agents/names.py             # PURE: validate_name(), sandbox_name()
caduceus/agents/tokens.py            # mint_token() (secrets), entropy floor
caduceus/agents/hermes_config.py     # PURE: render agent hermes config (provider -> AI-Gateway)
caduceus/agents/registry.py          # Registry/StateStore: atomic JSON, asyncio.Lock, CRUD, token_lookup
caduceus/agents/provisioner.py       # Provisioner (Protocol) + SbxProvisioner (asyncio subprocess, timeouts)
caduceus/agents/images.py            # ImageBuilder.ensure_image (docker build, idempotent)
caduceus/agents/health.py            # HealthChecker: shallow/deep (injected transport-probe; upstream check)
caduceus/agents/service.py           # AgentService: create(saga)/register/list/remove/stop/start
images/hermes/Dockerfile             # slim hermes-agent v0.17.0 image
tests/__init__.py  tests/unit/__init__.py  tests/pbt/__init__.py   # make tests a package
tests/fakes.py                       # FakeProvisioner, FakeImageBuilder, fake transport-probe
tests/unit/test_names.py
tests/unit/test_models.py
tests/unit/test_registry.py
tests/unit/test_agent_service.py
tests/pbt/test_registry_properties.py
```

## Steps
- [x] **Step 1 — Shared models**: `common/models.py` — `AgentKind`, `Lifecycle`, `HealthLevel`, `HealthStatus`, `AgentRecord` (incl. `serve_auth`), dataclasses + `to_dict`/`from_dict`. [contract for U1/U3/U4]
- [x] **Step 2 — Pure helpers**: `agents/names.py` (validate/normalize, `sandbox_name="cad-"+name`, BR-A1/A2), `agents/tokens.py` (`secrets.token_urlsafe`, BR-A4), `agents/hermes_config.py` (render config dict/yaml-text: provider base_url=AI-Gateway, model=`default`; BR-A5).
- [x] **Step 3 — Pure-helper unit + PBT**: `tests/unit/test_names.py`, `tests/unit/test_models.py` (round-trip); `tests/pbt/test_registry_properties.py` part 1 (models round-trip P-U2-1, name invariant P-U2-2, token entropy P-U2-6).
- [x] **Step 4 — Registry**: `agents/registry.py` — load/save atomic (`os.replace`), `asyncio.Lock`, get/list/upsert/delete/set_session, `token_lookup`, file perms 600. [BR-A8]
- [x] **Step 5 — Registry tests**: `tests/unit/test_registry.py` (CRUD, atomic write, token_lookup, perms).
- [x] **Step 6 — Adapters**: `agents/provisioner.py` (Protocol + `SbxProvisioner` via `asyncio.create_subprocess_exec` w/ timeouts, argv form), `agents/images.py` (`ImageBuilder`), `agents/health.py` (HealthChecker shallow/deep). [BR-A11/A12, RESILIENCY-10]
- [x] **Step 7 — AgentService (saga)**: `agents/service.py` — create (saga + compensation), register (+ guidance), list (reconcile), remove, stop/start (remote → error per BR-A10). [FR-A1..A6]
- [x] **Step 8 — Service tests + stateful PBT**: `tests/fakes.py`; `tests/unit/test_agent_service.py` (create happy w/ FakeProvisioner, rollback on failure, provider-config invariant P-U2-3, register guidance, remove teardown, stop/start remote error); `tests/pbt/test_registry_properties.py` part 2 (RuleBasedStateMachine P-U2-4/5).
- [x] **Step 9 — hermes image**: `images/hermes/Dockerfile` (slim v0.17.0; build validated in Build & Test, marked accordingly).
- [x] **Step 10 — Summaries**: `aidlc-docs/construction/u2-registry-provisioner/code/{business-logic-summary,api-layer-summary}.md`.
- [x] **Step 11 — Sanity run**: `pytest` in the venv (unit + PBT with FakeProvisioner; no real Docker). Repository-layer = the Registry (covered).

## Traceability
- FR-A1 create (Steps 2,4,6,7) · FR-A2 register (7) · FR-A3 list (7) · FR-A4 rm (7) · FR-A5 stop/start (7) · FR-A6 names (2) · FR-L2 health (6).
- PBT P-U2-1..6 (Steps 3,5,8) incl. stateful registry (PBT-06). Resiliency: saga/timeouts/atomic (Steps 4,6,7).

## Notes
- No new runtime deps (stdlib `asyncio`/`secrets`/`json`/`os`). hermes config rendered as text (no yaml dep; values are simple, token stays in env not file).
- `FakeProvisioner` records calls so tests assert the provider-config invariant (base_url=AI-Gateway, model=default) without Docker.
- Build & Test validation items (real image/serve/keys) are tracked in U2 Infra Design §8.
