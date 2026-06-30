# Units of Work — Caduceus

## Decomposition decisions
| # | Decision | Choice |
|---|---|---|
| Q1 | Code organization | **Single Python package (monorepo), module per unit** |
| Q2 | Granularity | **4 units (U1–U4)** |
| Q3 | Construction loop | **Full per-unit loop** — each unit runs Functional Design → NFR Requirements → NFR Design → Infrastructure Design → Code Generation; Build & Test once after all units |

**Note on per-unit loop (Q3=B)**: each design stage runs per unit with **adaptive depth**. Cross-cutting decisions (tech stack, logging, resiliency patterns, packaging) are established in **U1** and **inherited** by later units — for U2–U4 those stages reference U1 and add only unit-specific detail. Where a stage is genuinely not applicable to a unit, it is presented as "N/A with rationale" (an explicit, quick gate) rather than skipped silently.

---

## Code organization (greenfield)

```
caduceus/                       # repo root (workspace root)
  pyproject.toml                # single package, pipx-installable; entry point: caduceus
  README.md
  caduceus/                     # the Python package
    __init__.py
    __main__.py                 # `python -m caduceus`
    cli/                        # U4: typer app, command handlers, output rendering
    daemon/                     # U4: composition root, lifecycle, ControlAPI (FastAPI) routes
    aigateway/                  # U1: AIGateway routes, AIGatewayService, UpstreamClient
    agents/                     # U2: AgentService, Registry/StateStore, Provisioner, ImageBuilder, HealthChecker
    transport/                  # U3: Transport (abstract), ServeTransport, ChatService, Supervisor
    config/                     # U4: ConfigService, ConfigEditor
    common/                     # shared: Settings/Config, Logging, models, errors, typing
  images/
    hermes/Dockerfile           # U2: hermes-preinstalled image
  tests/
    unit/                       # example-based unit tests (pytest)
    integration/                # Docker/sbx/hermes integration tests
    pbt/                        # property-based tests (Hypothesis)
```

- One deployable: the `caduceus` package provides both the CLI and the daemon (`caduceus gateway start`).
- Units are **logical modules**, not separate distributions.

---

## Units

### U1 — AI-Gateway
- **Responsibility**: OpenAI-compatible LLM proxy that agents call; forwards to upstream (default Ollama), streaming pass-through; route resolution (default model now, per-agent override v2).
- **Modules/components**: `aigateway/` → AIGateway (FastAPI), AIGatewayService, UpstreamClient.
- **Owns**: FR-P1..P6.
- **Public interface (to other units)**: AI-Gateway base URL (for U2 to configure agents); `AIGatewayService` mounted by U4 daemon.
- **Buildable independently**: yes (test with a stub upstream; no agents required).

### U2 — Agent Registry & Provisioner
- **Responsibility**: agent lifecycle for local (sbx) + remote agents; durable registry; hermes image; health.
- **Modules/components**: `agents/` → AgentService, Registry/StateStore, Provisioner, ImageBuilder, HealthChecker; `images/hermes/Dockerfile`.
- **Owns**: FR-A1..A6, FR-L2; produces the hermes image.
- **Depends on**: U1 (agents are configured with the AI-Gateway URL — can use a placeholder/injected URL during isolated build).
- **Public interface**: `AgentService`, `Registry`, `AgentRecord` model, `HealthChecker`.

### U3 — Transport & Chat
- **Responsibility**: common streaming Transport to hermes (serve-first), chat orchestration with session continuity, resiliency supervisor.
- **Modules/components**: `transport/` → Transport (abstract) + ServeTransport, ChatService, Supervisor.
- **Owns**: FR-C1..C4, RES-4/RES-5.
- **Depends on**: U2 (needs provisioned/registered agents + Registry).
- **Public interface**: `Transport`, `ChatService`, `Supervisor`.

### U4 — CLI / Daemon / Config
- **Responsibility**: user surface + composition root; daemon lifecycle hosting Control API + AI-Gateway; config editing; logs.
- **Modules/components**: `cli/`, `daemon/`, `config/`, plus `common/` (Settings, Logging, models, errors).
- **Owns**: FR-G1..G4, FR-E1..E3, FR-L1.
- **Depends on**: U1, U2, U3 (wires them together).
- **Public interface**: `caduceus` CLI; the daemon process.

---

## Construction sequence (per-unit loop, Q3=B)

Order: **U1 → U2 → U3 → U4**, then **Build & Test**.

For each unit:
1. Functional Design (data models, logic, **PBT-01 property identification**)
2. NFR Requirements (tech stack confirm, **PBT-09 Hypothesis**, deferred resiliency questions handled at U-appropriate point)
3. NFR Design (resiliency patterns: timeouts/circuit-break/graceful degradation/supervision; logging)
4. Infrastructure Design (image/networking/packaging — heaviest for U2 & U1; lighter/N/A for U3/U4)
5. Code Generation (Planning + Generation)

Then once: **Build and Test** (unit + integration with Docker/sbx/hermes + PBT with seed logging).

---

## Validation — every FR assigned
- FR-G* → U4 · FR-P* → U1 · FR-A* → U2 · FR-C* → U3 · FR-E* → U4 · FR-L1 → U4 · FR-L2 → U2.
- NFR-1..7 → cross-cutting, primarily realized in U4 (`common/`) + per-unit. RES-* → U3 (supervisor/timeouts) + U2 (health/state) + U1 (upstream timeouts).
- No orphan FRs; no FR split across units without a defined interface.
