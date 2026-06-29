# U2 Registry & Provisioner — Logical Components

Internal decomposition of the `agents/` module + shared models. Pure (unit/property-testable) vs I/O.

| Component | Kind | Responsibility | Pure? |
|---|---|---|---|
| **models** (`common/models.py`) | data | `AgentRecord`, `AgentToken`, enums, (de)serialization | **yes** |
| **NameValidator** | logic | validate/normalize name; compute `sandbox_name="cad-"+name` | **yes** |
| **TokenMinter** | logic | `secrets.token_urlsafe`; uniqueness check vs registry | mostly (CSPRNG) |
| **Registry / StateStore** | I/O | load/save `state.json` (atomic), CRUD, `asyncio.Lock`, `token_lookup` | no |
| **Provisioner** (Protocol) | iface | create/exec/cp/ports/start/stop/remove/logs/status | n/a |
| **SbxProvisioner** | I/O | real impl over `sbx`/`docker` subprocess (timeouts, argv form) | no |
| **FakeProvisioner** | test | in-memory impl for unit tests | n/a |
| **ImageBuilder** | I/O | `ensure_image` (docker build, idempotent) | no |
| **HealthChecker** | I/O | shallow/deep checks (uses injected transport probe + upstream check) | no |
| **AgentService** | orchestration | create (saga) / register / list / remove / stop / start | no (coordinates) |

## Wiring (create saga)
```
AgentService.create
  NameValidator.validate -> sandbox_name
  ImageBuilder.ensure_image
  TokenMinter.mint
  [saga] SbxProvisioner.create_sandbox
         SbxProvisioner.configure_hermes(base_url=AIGW, api_key=token, model=default)
         SbxProvisioner.start_serve -> port
  Registry.upsert(record)            # atomic
  HealthChecker.check(shallow)
  on failure -> compensate (rm sandbox, drop token, no persist)
```

## Cross-unit contracts
- `Registry.token_lookup(token) -> agent_id` is exactly U1's `token_lookup` dependency → wired by U4 daemon (Registry injected into the AI-Gateway).
- `AgentRecord` (in `common/models.py`) is consumed by U3 (transport/chat) and U4 (CLI/daemon).
- `HealthChecker` deep-probe calls into U3's transport health (injected interface) → U2 stays decoupled from transport internals.

## Testability mapping (PBT-01)
- P-U2-1 round-trip → **models** serialization.
- P-U2-2 name/sandbox invariant → **NameValidator**.
- P-U2-3 provider invariant → **AgentService.create** (asserts configure args) via **FakeProvisioner** capture.
- P-U2-4 idempotence + P-U2-5 stateful registry → **AgentService + Registry + FakeProvisioner** under a Hypothesis `RuleBasedStateMachine`.
- P-U2-6 token entropy/uniqueness → **TokenMinter**.

## No external infra middleware
- No queue/cache/DB; the only durable store is `state.json`. (Matches local-tool scope.)
