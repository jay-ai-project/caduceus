# Application Design (Consolidated) — Caduceus

Consolidated view of the Application Design artifacts. See companions:
- [components.md](components.md) — components, responsibilities, interfaces
- [component-methods.md](component-methods.md) — method signatures + I/O
- [services.md](services.md) — services + orchestration sequences
- [component-dependency.md](component-dependency.md) — dependency matrix, communication, data flow

---

## 1. Design decisions (from Application Design questions)
| # | Decision | Choice |
|---|---|---|
| Q1 | CLI ↔ daemon control channel | **Loopback HTTP (FastAPI)** |
| Q2 | State store | **Single JSON file + atomic writes** (`~/.caduceus/state.json`) |
| Q3 | AI-Gateway exposure | **Split listeners** — Control API 127.0.0.1; AI-Gateway on host-gateway iface |
| Q4 | Session ownership | **hermes owns session**; caduceus stores per-agent session id only |

Carried from earlier gates: Python (typer/FastAPI/httpx/websockets); serve-first single Transport impl; authored hermes Dockerfile; local config-edit scope; default LLM via caduceus + `llamacpp/gemma-4-12b`; one persistent session per agent.

## 2. Architecture summary
One **daemon** hosts three planes: **Control API** (loopback, for the CLI), **AI-Gateway** (OpenAI-compatible proxy reachable by sandboxes), and the **registry/supervisor**. A thin **CLI** is the only client of the Control API. Managed agents run hermes inside `sbx` sandboxes built from an authored image; their hermes is configured so its LLM **provider base_url points back at the caduceus AI-Gateway**, which forwards to the upstream llama-swap. Caduceus talks to each agent through a common **Transport** (serve-first; ACP later) enabling uniform streaming chat for local and remote agents.

## 3. Components (19) and units
- **U1 AI-Gateway**: AIGateway, AIGatewayService, UpstreamClient
- **U2 Registry & Provisioner**: Registry/StateStore, Provisioner, ImageBuilder, HealthChecker, AgentService
- **U3 Transport & Chat**: Transport/ServeTransport, ChatService, Supervisor
- **U4 CLI / Daemon / Config**: CLI, ControlAPIClient, Daemon/GatewayService, ControlAPI, ConfigService, ConfigEditor, Config, Logging

(Full responsibilities/interfaces in components.md; signatures in component-methods.md.)

## 4. Key flows
- **create** (local): ensure image → create sandbox → configure hermes provider→AI-Gateway → start `hermes serve` + publish port → register → verify health (rollback on failure).
- **chat**: CLI→ControlAPI(SSE)→ChatService→Transport→hermes; hermes calls AI-Gateway→upstream; tokens stream back; session id persisted on first turn (resume thereafter).
- **ai-gateway**: agent hermes → AI-Gateway `/v1/chat/completions` → AIGatewayService route (default upstream+model; per-agent override v2) → upstream, streamed back.
- **config** (local): ConfigService→ConfigEditor→Provisioner exec/cp (skills/tools/soul/core) → restart serve if needed; remote = read-only.

## 5. Resiliency applicability (RESILIENCY @ Application Design)
| Rule | Status | Where |
|---|---|---|
| RESILIENCY-01 criticality | ✅ Compliant | components.md criticality table; external deps listed |
| RESILIENCY-06 health checks | ✅ Compliant | HealthChecker (shallow+deep), `/healthz`, `/status` |
| RESILIENCY-10 dependency isolation | ✅ Compliant | explicit timeouts on Provisioner/Transport/UpstreamClient; Supervisor circuit-break + graceful degradation |
| RESILIENCY-05 observability | ✅ Direction set | Logging component (structured); metrics/traces/dashboards N/A (personal tool) |
| RESILIENCY-12 state durability | ✅ Compliant | Registry atomic JSON writes |
| RESILIENCY-03/04/14/15 | ⏭️ Deferred | NFR Design |
| RESILIENCY-07/08/09/11/13 | ➖ N/A | single-host local tool |
No blocking resiliency findings.

## 6. PBT applicability (PBT @ Application Design)
- PBT-01 (property identification) is a **Functional Design** activity; candidate property-bearing components are flagged in component-methods.md (Registry round-trip + state machine, AIGatewayService mapping/route, name validation, provider-rewrite invariant). PBT-09 framework (Hypothesis) recorded for NFR Requirements. No blocking PBT findings at this stage.

## 7. Open items → resolved in Construction
- Exact `hermes serve` wire protocol + auth (spike in U3 / Infrastructure Design).
- `host.docker.internal` reachability on this WSL2/Docker host (validate in Infrastructure Design).
- hermes provider config mechanism to point at AI-Gateway (validate in U2 / Infrastructure Design).
