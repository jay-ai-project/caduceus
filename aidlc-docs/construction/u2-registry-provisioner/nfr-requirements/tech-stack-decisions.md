# U2 Registry & Provisioner — Tech Stack Decisions

Inherits the global stack (Python 3.11+, pytest + Hypothesis). U2 adds **no new third-party runtime dependencies** — it orchestrates external CLIs with the standard library.

| Concern | Choice | Rationale |
|---|---|---|
| sbx/docker invocation | stdlib `asyncio.create_subprocess_exec` (+ explicit timeouts) | async, no shell injection (argv form), cancellable |
| Token generation | stdlib `secrets.token_urlsafe(32)` | CSPRNG |
| State store | stdlib `json` + atomic `os.replace`; in-process `asyncio.Lock` | simple, human-inspectable (App Design Q2), durable (RESILIENCY-12) |
| File perms | stdlib `os.chmod` (state dir 700, token/state 600) | secret hygiene |
| Models | dataclasses (in `caduceus/common/models.py`) | shared AgentRecord contract |
| Image build | `docker build` via subprocess (Dockerfile in `images/hermes/`) | reproducible (Units Q4=A) |

## Testing (PBT-09 already satisfied globally)
- Unit: `pytest` with **mocked** Provisioner/ImageBuilder/transport-health (no real Docker).
- Property: **Hypothesis** — registry serialization round-trip + `RuleBasedStateMachine` for the registry lifecycle (PBT-06).
- Integration (Build & Test): real `sbx`/`docker` — create→ls→stop→start→rm + RESILIENCY-14 fault injection.

## New dependencies
- Runtime: **none** beyond U1's set (uses stdlib).
- Dev: none beyond existing (`pytest`, `hypothesis`, `pytest-asyncio`/`anyio`).

## Notes for Code Generation
- Define `AgentRecord` + `AgentToken` as dataclasses in `caduceus/common/models.py` (shared contract; consumed by U1 token_lookup, U3, U4).
- `Provisioner` is an interface (Protocol/ABC) with a real `SbxProvisioner` impl + a `FakeProvisioner` for tests.
- The exact hermes provider-config mechanism + `sbx` command lines are finalized in U2 Infrastructure Design.
