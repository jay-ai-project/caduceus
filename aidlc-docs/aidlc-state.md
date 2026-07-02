# AI-DLC State Tracking

## Project Information
- **Project Name**: Caduceus
- **Project Type**: Greenfield
- **Start Date**: 2026-06-29T12:19:17Z
- **Current Stage**: INCEPTION - Requirements Analysis
- **Requirements Depth**: Comprehensive (multi-component system)
- **Complexity / Scope**: Complex / System-wide (gateway daemon + AI-proxy + agent registry + transport abstraction + CLI)

## Target Architecture (working hypothesis — pending Requirements approval)
- **caduceus daemon (gateway hub)**: hosts (a) AI-Gateway = OpenAI-compatible LLM proxy that agents route through (forwards to host Ollama by default, per-agent override later), (b) agent chat/control hub, (c) agent registry + state.
- **caduceus CLI**: thin client to the daemon (`agent create|register|ls|chat|config|rm`, `gateway start|stop|status`).
- **Agents (two kinds)**: (1) *managed/local* — provisioned via `sbx` + hermes pre-installed image; (2) *registered/remote* — existing hermes endpoint registered by URL.
- **Transport abstraction**: common streaming interface; remote via `hermes serve` (JSON-RPC/WS), local optimization via `hermes acp` (stdio over `sbx exec -i`).
- **LLM routing**: agent `hermes` `custom_providers.base_url` → caduceus AI-Gateway (`host.docker.internal:<port>/v1`) → Ollama (`localhost:11434/v1`, model `your-model`).

## Workspace State
- **Existing Code**: No
- **Programming Languages**: None (greenfield)
- **Build System**: None
- **Project Structure**: Empty (only AI-DLC rules + workspace config)
- **Reverse Engineering Needed**: No
- **Workspace Root**: /mnt/f/Workspace/Caduceus

## Tooling Discovered (host environment)
- **hermes**: /home/beom/.local/bin/hermes — AI agent CLI (chat, serve, proxy, gateway, sessions, config, status, ...)
- **sbx**: /usr/bin/sbx — Docker Sandboxes (create, run, exec, ls, ports, template, secret, ...)
- **Docker**: Server 29.4.0 on Ubuntu 24.04 (WSL2)
- **Host LLM endpoint**: http://localhost:11434/v1 (Ollama), model `your-model`

## Code Location Rules
- **Application Code**: Workspace root (NEVER in aidlc-docs/)
- **Documentation**: aidlc-docs/ only
- **Structure patterns**: See code-generation.md Critical Rules

## Extension Configuration
| Extension | Enabled | Mode | Decided At |
|---|---|---|---|
| Security Baseline | No | — | Requirements Analysis (Q7=B) |
| Resiliency Baseline | Yes | Full (blocking) | Requirements Analysis (Q8=A) |
| Property-Based Testing | Yes | Full (all rules blocking) | Requirements Analysis (Q9=A) |

## Confirmed Requirements Decisions (Round 2 answers)
- **Q1 Topology = A**: caduceus daemon (gateway hub) + thin CLI client.
- **Q2 Transport = A**: serve-first unified (`hermes serve` JSON-RPC/WS for local+remote); Transport abstraction in place; local ACP optimization deferred.
- **Q3 Stack = A**: Python (`typer` + `FastAPI` + `httpx`/`websockets`). → PBT framework = Hypothesis.
- **Q4 Image = A**: author a Dockerfile; caduceus builds/tags it for `sbx create shell -t <image>`.
- **Q5 Config-edit scope = A**: local sbx agents fully editable (skills/soul/tools/config); remote read/observe first.
- **Q6 Command scope = B (Standard)**: core + `agent stop/start`, `agent config`, `agent logs`.
- Assumptions locked: LLM via caduceus by default + default model (per-agent override later); one persistent session per agent (auto-resume); local provisioning via sbx + hermes image.

## Execution Plan Summary
- **Stages to Execute**: Application Design, Units Generation, (per-unit) Functional Design, NFR Requirements, NFR Design, Infrastructure Design, Code Generation, Build and Test.
- **Stages to Skip**: Reverse Engineering (greenfield), User Stories (single persona; requirements clear).
- **Candidate units**: U1 AI-Gateway · U2 Agent Registry & Provisioner · U3 Transport & Chat · U4 CLI/Daemon/Config (to confirm in Units Generation).
- **Risk**: Medium · **Rollback**: Easy · **Testing**: Moderate-Complex.

## Stage Progress
### 🔵 INCEPTION PHASE
- [x] Workspace Detection
- [x] Reverse Engineering (SKIPPED — greenfield)
- [x] Requirements Analysis (complete, approved)
- [ ] User Stories — SKIP (single persona; requirements already comprehensive)
- [x] Workflow Planning (complete, approved)
- [x] Application Design (complete — awaiting approval gate)
  - Decisions: Q1=HTTP loopback, Q2=JSON state, Q3=split listeners, Q4=hermes-owned session
  - Artifacts: components.md, component-methods.md, services.md, component-dependency.md, application-design.md
  - 19 components mapped to 4 units (U1 AI-Gateway, U2 Registry/Provisioner, U3 Transport/Chat, U4 CLI/Daemon/Config)
- [x] Units Generation (complete — awaiting approval gate)
  - Decisions: Q1=single Python package, Q2=4 units, Q3=**full per-unit loop**
  - Artifacts: unit-of-work.md, unit-of-work-dependency.md, unit-of-work-story-map.md
  - Build order: U1 → U2 → U3 → U4 → Build & Test

## Resiliency Scope (decided)
- Operational context: **Personal local tool** (R1=A). RTO/RPO/DR: **N/A** cross-region (R2=A).
- Applicable now: RESILIENCY-01 (criticality), -02 (captured N/A), -05 (logging only), -06 (health checks), -10 (timeouts/graceful degradation), -12 (state durability), + process supervision.
- Resolved at U1 NFR Design (project-wide): RESILIENCY-03 = **N/A exempt** (personal tool); RESILIENCY-04 = **GH Actions CI (pytest+Hypothesis, seed-logged) + reinstall-previous rollback + direct install**; RESILIENCY-14 = **lightweight fault-injection integration tests**; RESILIENCY-15 = **lightweight log-based triage + restart procedures**.
- N/A (cloud/HA): RESILIENCY-07, -08, -09, -11, -13.

### 🟢 CONSTRUCTION PHASE (FULL per-unit loop, Q3=B; order U1→U2→U3→U4)
Per unit (each stage is a gate): Functional Design → NFR Requirements → NFR Design → Infrastructure Design → Code Generation. Cross-cutting decisions set in U1, inherited (adaptive depth) by U2–U4. Build & Test once after all units.
- [x] **U1 AI-Gateway** ✅ COMPLETE: [x] FD · [x] NFR-Req · [x] NFR-Design · [x] Infra · [x] CodeGen
  - Spike (WSL2/Docker): bridge gw `172.17.0.1` reachable from containers unconditionally; `host.docker.internal` needs `--add-host` (no Docker Desktop). Decision: AI-Gateway bind bridge IP:9701, Control API 127.0.0.1:9700, advertise = bridge gw IP.
  - shared-infrastructure.md created (ports/binds/paths/packaging — shared by all units)
  - **Code**: `caduceus/{common,aigateway}/*` + `pyproject.toml` + `tests/{unit,pbt}` + README. **26/26 tests pass** (venv). PBT caught & fixed a real bug (redact regex ASCII-only → non-ASCII token leak).
- [x] **U2 Registry & Provisioner** ✅ COMPLETE: [x] FD · [x] NFR-Req · [x] NFR-Design · [x] Infra · [x] CodeGen
  - Spike: hermes-agent v0.17.0 (NousResearch git project, official Dockerfile); custom_providers list; bearer via OpenAI-SDK key. Image pinned 0.17.0; agent→AIGW via `172.17.0.1:9701` + OPENAI_API_KEY=token.
  - Infra: **slim image (Q1=A)**; provisioning sequence; `AgentRecord.serve_auth`; Build-time validation items flagged.
  - **Code**: `caduceus/common/models.py` + `caduceus/agents/{names,tokens,hermes_config,registry,provisioner,images,health,service}.py` + `images/hermes/Dockerfile` + tests (unit + stateful PBT). **55/55 tests pass** (U1 31 + U2 24). Stateful PBT drives real AgentService vs reference model.
  - FD decisions: name→`cad-<name>` (Q1=A); remote = token+guidance, read-only config (Q2=A); **remote start/stop not possible (user-confirmed, BR-A10)**. Stateful registry PBT planned.
- [x] **U3 Transport & Chat** ✅ COMPLETE: [x] FD · [x] NFR-Req · [x] NFR-Design · [x] Infra (LIGHT) · [x] CodeGen
  - FD decisions: Q1=A transparent session recreate; **Q2=B no per-agent serialization (delegate to hermes serve, no turn-lock)**; Q3=A standard Supervisor defaults (30s sweep, 2 fails→restart, exp backoff 5/15/45s cap ~120s, 3 restart-fails→circuit open→failed, reset on manual start); Q4=A fail-fast on unhealthy/circuit-open; Q5=A protocol-handshake-only health (no LLM spend); Q6=A cooperative cancel.
  - Design artifacts: domain-entities.md, business-logic-model.md (7 PBT-01 props incl. stateful Supervisor PBT), business-rules.md (BR-C1..C16, BR-S1..S7); nfr-requirements + nfr-design + infrastructure-design (LIGHT). Supervision = local-only (inherits U2 BR-A10).
  - **Code**: `caduceus/transport/{events,base,serve,chat,supervisor}.py` + `pyproject.toml` (+websockets>=12) + tests (extended fakes, unit ×3, pbt). **81/81 tests pass** (U1 31 + U2 24 + U3 26) in `.venv`. ServeTransport `_WIRE_*` real impl unit-untested by design (protocol → Build & Test). New venv created this session (`.venv`).
- [x] **U4 CLI / Daemon / Config** ✅ COMPLETE: [x] FD · [x] NFR-Req · [x] NFR-Design · [x] Infra · [x] CodeGen
  - FD: Q1 foreground+`-d`; Q2 hot-reload + `CHANGE_KIND_STRATEGY` seam; Q3 bootstrap+config.toml; Q4 read-back verify; Q5 `--soul`/`--soul-file`; Q6 human/`--json`+exit codes.
  - **Code**: `caduceus/common/dto.py` + `caduceus/common/settings.py`(extended) + `caduceus/config/{editor,service}.py` + `caduceus/daemon/{lock,wiring,control_api,gateway}.py` + `caduceus/cli/{client,render,app}.py` + `caduceus/__main__.py` + pyproject(+typer, console script `caduceus`). **132/132 tests pass** (U1 31 + U2 24 + U3 26 + U4 51). Console script verified. Daemon serve/fork + real ControlAPIClient/sandbox-config-codec unit-untested by design → Build & Test.
  - FD decisions: Q1=foreground default + `-d` daemonize (single-instance pid/lock); **Q2=B hot-reload default + per-change-kind `ReloadStrategy` seam (CHANGE_KIND_STRATEGY) for future selective restart**; Q3=A interactive config bootstrap + `~/.caduceus/config.toml`; Q4=A apply→read-back+health verify; Q5=B `--soul`/`--soul-file` both (reject if both set); Q6=A human default + `--json` + exit codes 0/2/1.
  - Artifacts: domain-entities.md, business-logic-model.md (L1-L6 incl. composition-root wiring of U1/U2/U3; 6 PBT-01 props), business-rules.md (BR-G/E/L/O/W). U4 wires injected U3 callables + U1 token_lookup.
- [x] **Build and Test** ✅ COMPLETE & APPROVED (after all units)
  - **Build**: ✅ editable install + wheel build OK; console script verified; all modules import OK.
  - **Tests**: ✅ **141/141 pass** (118 unit + 23 PBT) on CPython 3.12.3, `.venv` (+9 AcpTransport tests).
  - **Integration**: ✅ **all 6 scenarios PASS live** (Docker 29.4.0 + sbx + hermes 0.17.0 + Ollama): CLI↔daemon, AI-Gateway auth, provision, E2E LLM, ACP chat (streamed "PONG"/"OK"), supervisor auto-restart (~50s).
  - **10 defects found & fixed (A–J)** during integration — see build-and-test-summary.md. Biggest: **transport pivot `hermes serve`→`hermes acp` (stdio)** because serve needs a full Node web build (contradicts slim image). User-approved (image-packaging→ACP).
  - **Code changes (post-CONSTRUCTION, in Build & Test):** new `caduceus/transport/acp.py` (AcpTransport) + `Transport.for_agent` local→ACP; provisioner/service/health/wiring rewired (no serve/port); `images.py` auto-loads image into sbx; hermes config writes inline `api_key`; `cli/client.py` provision timeout; daemon supervisor boot fix; Dockerfile `[acp]` extra + correct git ref. No new caduceus runtime dependency (raw JSON-RPC).
  - **Performance**: N/A as gate (personal local tool).
  - Artifacts: build-instructions.md, unit-test-instructions.md, integration-test-instructions.md, performance-test-instructions.md, build-and-test-summary.md.

## 🔵 NEW CYCLE — U5 Gateway Web UI (started 2026-06-30)
- **Trigger**: user request for a simple Web UI on `caduceus gateway` (dashboard + add agent + streaming chat w/ thinking & tool display).
- **Phase**: INCEPTION — Requirements Analysis.
- [x] Requirements Analysis (U5) — complete, **awaiting approval gate**
  - Answers (all recommended): Q1=A static vanilla SPA (no build); Q2=A mount on Control API 127.0.0.1:9700; Q3=A full thinking+tool args/results collapsible; Q4=A local provision + remote register parity; Q5=A history via ACP session/load replay (best-effort); Q6=A loopback no auth; Q7=A polling; Q8=A inherit extensions; Q9=none.
  - **Core enabler (cross-cutting U3)**: extend ChatEvent (`transport/events.py`) + AcpTransport (`transport/acp.py`) to surface thinking (`agent_thought_chunk`) + tool calls (`tool_call`/`tool_call_update`), currently dropped — preserving terminal-event invariant + CLI compat.
  - Extensions inherited: Security=No, Resiliency=Yes/full, PBT=Yes/full.
  - Artifacts: requirements/web-ui-verification-questions.md, requirements/web-ui-requirements.md.
- [x] Workflow Planning (U5) — complete & approved
  - Stages to EXECUTE: Functional Design (light) → Code Generation → Build & Test.
  - Stages to SKIP: Application Design, Units Generation (single small unit), NFR Req/Design, Infrastructure Design (all inherit U1–U4 + shared-infrastructure.md).
  - Risk: Low–Medium (cross-cutting U3 event-path change must preserve terminal invariant + CLI compat). Rollback: Easy (additive).
  - Artifacts: plans/web-ui-execution-plan.md.

### 🟢 CONSTRUCTION (U5)
- [x] **U5 Functional Design** (light) — complete, **awaiting approval gate**
  - Decisions (made inline, adaptive — no separate question round; requirements were specific):
    - Event model: extend `ChatEventType` with `thinking` + `tool_call`; add optional `meta` dict to `ChatEvent` (ToolCallMeta: id/name/status/input/output). `normalize_stream` unchanged (terminal invariant preserved). Reuse `message` w/ meta role for replayed history.
    - ACP mapping: `agent_thought_chunk`→thinking, `tool_call`/`tool_call_update`→tool_call (merge by toolCallId), defensive parse, truncate input/output 4 KiB.
    - History (FR-W10): `ChatService.history()` via dedicated short-lived transport doing session/load replay capture; best-effort, local-only, text-only.
    - Serving: `caduceus/webui/` static assets mounted `/ui` on Control API; `GET /`→redirect; new `GET /agents/{name}/history` JSON.
    - Frontend: vanilla no-build SPA (Header / Sidebar dashboard / ChatView w/ collapsible thinking + tool cards).
  - Artifacts: construction/u5-webui/functional-design/{domain-entities,business-logic-model,business-rules,frontend-components}.md
  - PBT targets: PBT-W1 (terminal invariant under extended events), PBT-W2 (to_dict/from_dict round-trip w/ meta).

- [x] **U5 Code Generation** — complete, **awaiting approval gate**
  - Part 1 plan (14 steps) approved; Part 2 executed.
  - Created: `caduceus/webui/{__init__,serve}.py` + `assets/{index.html,styles.css,app.js}`.
  - Modified: `transport/events.py` (thinking/tool_call + meta + HistoryTurn), `transport/acp.py` (_map_update + load_history), `transport/base.py` (load_history no-op), `transport/chat.py` (history()), `daemon/control_api.py` (mount_webui + GET /agents/{name}/history), `pyproject.toml` (note), `README.md`. Tests across 5 files + fakes.
  - **173 tests pass** (was 154; +19). Wheel build verified to include webui assets (force-include removed — `packages=["caduceus"]` already ships them).
  - Artifacts: construction/u5-webui/code/code-summary.md; plan construction/plans/u5-webui-code-generation-plan.md (all [x]).

- [x] **U5 Build & Test** — complete, **awaiting approval gate**
  - Build ✅ (editable + wheel incl. webui assets). Tests ✅ **174/174** (154 +20).
  - Live integration ✅ (Docker+sbx+hermes 0.17.0+Ollama): `/`→`/ui/` redirect, `/ui/` index+assets, BR-W1 (no UI on :9701 → 404), local provision, **streaming chat with thinking** (107 thinking + 162 token + 1 done; terminal invariant holds live), **history** 4-turn replay via session/load, unknown-agent history 404.
  - **Defect K fixed** (live: 6.1s→~1ms): dashboard `/agents` ran a per-agent `sbx` reconcile + ACP health handshake every call (~6s/1 agent, ~12s/2). `?probe=false` (UI) is now an instant registry-only projection; Supervisor sweep caches `last_health`; frontend fetches `/status` + `/agents` independently and fires immediately on load; poll 3s. CLI `agent ls` unchanged (probe=true authoritative). Trade-off: health supervisor-refreshed (~30s), may be stale for one sweep after restart.
  - Tool-call live invocation not forced (test prompts produced thinking, no tool call); ACP→event mapping unit-verified.
  - Artifacts: construction/build-and-test/web-ui-build-and-test-summary.md.

## 🔵 NEW CYCLE — U6 Gateway Config Command (started 2026-07-01)
- **Trigger**: user request — add `caduceus gateway config` to view/change `upstream_base_url` and `default_model`.
- **Phase**: INCEPTION — Requirements Analysis.
- [x] Requirements Analysis (U6) — complete & **APPROVED**
  - Answers (all recommended A): Q1=A hot-apply live + persist; Q2=A dedicated `--upstream-url`/`--model` + `--get`/`--json`; Q3=A only the two keys; Q4=A works daemon up or down (down → edit config.toml directly); Q5=A light validation (non-empty + URL shape, no network); Q6=A extensions inherited.
  - Extensions inherited: Security=No, Resiliency=Yes/full, PBT=Yes/full.
  - Scope touches: `cli/app.py`, `cli/client.py`, `common/settings.py`, `daemon/control_api.py`, `daemon/wiring.py`, AI-Gateway upstream/routing seam (live hot-apply).
  - Artifacts: requirements/u6-gateway-config-verification-questions.md, requirements/u6-gateway-config-requirements.md.
- [x] Workflow Planning (U6) — complete & **APPROVED**
  - Stages to EXECUTE: Functional Design (light) → Code Generation → Build & Test.
  - Stages to SKIP: Application Design, Units Generation, NFR Requirements, NFR Design, Infrastructure Design (all inherit U1–U4 + shared-infrastructure.md).
  - Risk: Low–Medium (live hot-apply of UpstreamClient/routing without restart). Rollback: Easy (additive command + route).
  - Artifacts: plans/u6-gateway-config-execution-plan.md.

### 🟢 CONSTRUCTION (U6)
- [x] **U6 Functional Design** (light) — complete, **awaiting approval gate**
  - Confirmed hot-apply feasibility: `UpstreamClient._url()` + `routing.build_route()` read the shared `Settings` live → daemon mutates `Services.settings` in place, no restart.
  - Decisions: GatewayConfigView (secret-free, source live/file, env_override warn) + GatewayConfigChange in common/dto.py; atomic key-preserving `config.toml` read-modify-write (temp+os.replace, 600); additive Control-API `GET`/`POST /gateway/config`; CLI `gateway config --get/--json/--upstream-url/--model` works daemon up or down.
  - Rules BR-GC1..GC11; PBT-GC1..GC3 (URL validation totality, config round-trip + key preservation, change idempotence).
  - Artifacts: construction/u6-gateway-config/functional-design/{domain-entities,business-logic-model,business-rules}.md

- [x] **U6 Functional Design** (light) — **APPROVED** (committed aaeb140)
- [x] **U6 Code Generation** — **APPROVED**; Part 2 (Generation) complete.
  - Plan (all 10 steps [x]): construction/plans/u6-gateway-config-code-generation-plan.md.
  - Created: `caduceus/config/gateway_config.py` (validate + atomic key-preserving store + GatewayConfigService) + 4 test files.
  - Modified: common/dto.py, daemon/wiring.py, daemon/control_api.py, cli/{client,app,render}.py, tests/fakes.py, README.md.
  - Artifacts: construction/u6-gateway-config/code/code-summary.md.
- [x] **U6 Build & Test** — complete & **APPROVED** — U6 cycle ✅ COMPLETE
  - Build ✅ (editable install + entrypoint + import + wheel; no new runtime dep). Tests ✅ **208/208** (was 174; +34).
  - Live ✅ real `caduceus` entry point: **offline** path (file edit, exit codes, env-shadow warning) + **hot-apply** path
    (running daemon: `--model` change visible on a fresh request with no restart; config.toml persisted; clean shutdown).
  - Config routes loopback-only, no Docker needed. Performance N/A (personal tool).
  - Artifacts: construction/build-and-test/u6-gateway-config-build-and-test-summary.md.

## 🔵 NEW CYCLE — U7 Performance & Stability (started 2026-07-01)
- **Trigger**: user request — evaluate/improve overall perf & stability: (1) `agent ls` too slow;
  (2) agent only boots on first chat → `create` should reach chat-ready; (3) `create` should
  provision in background (non-blocking) with live `agent ls` state; running+healthy ⇒ chat now;
  (4) fix mis-reported status; decouple gateway shutdown from agent sandboxes; reconnect running
  agents on daemon restart.
- **Phase**: INCEPTION — Requirements Analysis.
- **Diagnosis (confirmed)**: `sbx ls --json` ~2.5–3.9s, called 2×N in `AgentService.list(probe=True)`
  (provisioner.status + HealthChecker shallow) → slowness. `create` never starts `hermes acp` → first
  chat pays ACP cold start. CLI blocks up to PROVISION_TIMEOUT=1800s. Lifecycle reconcile has a
  present-sandbox→failed/stopped edge; daemon lifecycle entangled with agent perception.
- [x] Requirements Analysis (U7) — complete, **awaiting approval gate**
  - Answers (all A): Q1=A async create + `--wait`; Q2=A full ACP warm-up (no LLM spend); Q3=A single
    batched `sbx ls` snapshot for reconcile+shallow-health; Q4=A fully decouple gateway/sandbox +
    reconcile-from-`sbx` on boot; Q5=A background failure → `lifecycle=failed` + detail, compensate.
  - Extensions inherited: Security=No, Resiliency=Yes/full, PBT=Yes/full.
  - Scope: `caduceus/agents/{service,health,provisioner}.py`, `transport/{chat,supervisor}.py`,
    `daemon/{gateway,wiring,control_api}.py`, `cli/{app,client}.py`.
  - Artifacts: requirements/u7-perf-stability-verification-questions.md,
    requirements/u7-perf-stability-requirements.md.
- [x] Requirements Analysis (U7) — **APPROVED** (2026-07-01).
- [x] Workflow Planning (U7) — complete, **awaiting approval gate**
  - Stages to EXECUTE: Functional Design (light) → Code Generation → Build & Test.
  - Stages to SKIP: Application Design, Units Generation, NFR Requirements, NFR Design,
    Infrastructure Design (all inherit U1–U4 + shared-infrastructure.md).
  - Risk: Medium (async state machine + shutdown decouple + boot reconcile touch daemon/Supervisor;
    must preserve fail-fast gate, session continuity, terminal-event invariant, all 211 tests).
    Rollback: Moderate. Testing: Moderate.
  - Critical path: agents/service.py → transport/chat.py → daemon/gateway.py+wiring.py → control_api+cli.
  - Artifacts: plans/u7-perf-stability-execution-plan.md.
- [x] Workflow Planning (U7) — **APPROVED** (2026-07-01).

### 🟢 CONSTRUCTION (U7)
- [x] **U7 Functional Design** (light) — **APPROVED** (2026-07-01)
  - Decisions (inline, adaptive — requirements were specific, no separate question round):
    - No breaking model changes: reuse AgentRecord/Lifecycle/HealthStatus; failure cause carried in
      `last_health.detail`. New in-memory `SandboxSnapshot` (one `sbx ls`, `ok` flag) + `ProvisioningJob`.
    - L1 fast list: `provisioner.list_statuses()` once/list, reused for reconcile + shallow health;
      `HealthChecker.check(rec, deep, sandbox_status=None)` avoids re-probe.
    - L2 async create: register `creating` + return; bg saga → running → warm → healthy; `--wait` blocks.
    - L3 warm-up: `ChatService.warm(name)` opens pooled ACP (initialize+session/new, no LLM), reused first turn.
    - L4 shutdown decouple: no sbx stop/rm on shutdown (stdio-only teardown). L5 boot `reconcile_all()`.
    - L6 supervisor supervises only `running` agents.
  - Rules BR-P1..P15; PBT-P1 reconcile totality, P2 async state machine, P3 single-snapshot invariant,
    P4 shutdown safety.
  - Artifacts: construction/u7-perf-stability/functional-design/{domain-entities,business-logic-model,business-rules}.md

- [x] **U7 Code Generation — Part 1 (Plan)** — **APPROVED** (2026-07-01).
- [x] **U7 Code Generation — Part 2 (Generation)** — **APPROVED** (2026-07-01)
  - All 11 plan steps [x]. Modified: agents/{provisioner,health,service}.py, transport/{chat,supervisor}.py,
    daemon/{wiring,gateway,control_api}.py, cli/{client,app}.py, README.md; tests/fakes.py + unit
    (agent_service, chat_service, supervisor, control_api, cli) + new tests/pbt/test_u7_properties.py.
  - **225 unit + PBT tests pass** (was 208; +17). No new runtime dependency.
  - Artifacts: construction/u7-perf-stability/code/code-summary.md.

- [x] **U7 Build & Test** — complete & **APPROVED** — U7 cycle ✅ COMPLETE
  - Build ✅ (editable import clean; no new runtime dep). Tests ✅ **228** (225 unit+PBT +3 e2e).
  - Live ✅ (Docker+sbx+hermes 0.17.0+Ollama): `agent ls` flat in N (1 `sbx ls`; 2 agents 3.77s,
    empty 4.10→1.22s); background create returns 1.31s → `creating`→`running/healthy` ~6s; warm first
    chat (PONG/OK) no cold stall; `gateway stop` left sandboxes running; `gateway start` reconnected
    both to running/healthy, chat-able.
  - **Defect U7-L1 fixed live**: `sbx ls` timeout propagated → `agent ls` error; now `list_statuses`
    catches any error → `ok=False` (BR-P2), and `agent ls` skips `sbx ls` when no local agents. PBT-P3 updated.
  - Artifacts: construction/build-and-test/u7-perf-stability-build-and-test-summary.md.

## 🔵 NEW CYCLE — U8 HTTP/SSE Transport + Docker Runtime Migration (started 2026-07-01)
- **Trigger**: user request — re-architecture. Replace `hermes acp`+`sbx` local stack with the
  official **hermes API Server** (HTTP+SSE); unify Local/Remote transport into one HTTP/SSE
  transport; replace `sbx` with **plain Docker containers** (sbx blocks inbound; HTTP server
  needs inbound); add optional **gVisor (`runsc`)** runtime (default `runc`, opt-in via config).
- **Phase**: INCEPTION — Requirements Analysis.
- **Terminology locked**: "hermes API server" = per-agent HTTP/SSE server (`hermes gateway`);
  "gateway"/"caduceus gateway" = the caduceus daemon (unchanged meaning).
- [x] Requirements Analysis (U8) — complete, **awaiting approval gate**
  - Answers: Q1=A Sessions+Runs composed; Q2=A loopback port publish (`-p 127.0.0.1:<hp>:8642`);
    Q3=A new `caduceus doctor`; Q4=A fail-fast when `runsc` configured-but-unavailable;
    Q5=A `gateway config --runtime`; Q6=A→**strengthened: NO legacy at all** (never deployed,
    zero existing agents; sbx forgotten entirely, no migration/fallback — clean docker-only);
    Q7=A unify transport, keep remote as management distinction (drop Acp+Serve transports);
    Q8=A auto-approve + surface tool events; Q9=Security **best-effort/advisory (non-blocking)**.
  - **Refinement (user, post-draft)**: drop U7 fast-`ls` caching/single-snapshot sweep →
    `agent ls` does **real-time, no-cache** status: parallel `/health` HTTP probes + live
    `docker` status every request. Caching may be re-added later if slow (deferred, not U8).
  - **Extensions (this cycle)**: Security Baseline = **Yes (best-effort/advisory, non-blocking)**;
    Resiliency = Yes (full); PBT = Yes (full).
  - Scope touches: transport/{base,acp,serve,chat,supervisor,events}, agents/{provisioner,images,
    health,service,hermes_config}, common/{models,settings}, config/gateway_config, cli/{app,client,
    render}, daemon/{control_api,wiring,gateway}, webui (history), images/hermes/Dockerfile.
  - Key risk: hermes API endpoint/SSE shapes need a spike (mirrors ACP discovery); inbound trust
    boundary (mitigated loopback+bearer); large cross-cutting blast radius (preserve all invariants).
  - Artifacts: requirements/u8-http-sse-docker-verification-questions.md,
    requirements/u8-http-sse-docker-requirements.md.
- [x] Requirements Analysis (U8) — **APPROVED** (2026-07-01, incl. refinements: no-legacy + real-time no-cache ls).
- [x] Workflow Planning (U8) — complete, **awaiting approval gate**
  - Stages to EXECUTE: **Functional Design (std) + Spike**, **Infrastructure Design (LIGHT)**,
    Code Generation, Build & Test.
  - Stages to SKIP: Application Design (behind existing ports), Units Generation (single cycle),
    NFR Requirements + NFR Design (inherit U1/U3 cross-cutting; NFRs captured in requirements).
  - Risk: **High** (architectural transformation: runtime + protocol swap; must preserve
    terminal-event invariant, warm-up, boot-reconnect, lifecycle decoupling, full suite;
    hermes API shapes need a spike). Rollback: Moderate. Testing: Complex.
  - Critical path: spike → models+settings → transport(events+HermesApiTransport, retire acp/serve)
    → provisioner(Docker)+images(docker-only)+health(HTTP) → service+chat+supervisor →
    daemon(wiring/control_api/doctor/gateway)+gateway_config(--runtime) → cli+webui → tests+B&T.
  - Artifacts: plans/u8-http-sse-docker-execution-plan.md.
- [x] Workflow Planning (U8) — **APPROVED** (2026-07-01).

### 🟢 CONSTRUCTION (U8)
- [x] **U8 Spike (hermes API server)** — CONCLUSIVE & POSITIVE. Key findings (hermes 0.17.0):
  API server is a platform of **`hermes gateway run`** (foreground; docs say "recommended for
  Docker"), enabled by env `API_SERVER_ENABLED=true`+`API_SERVER_KEY`(+HOST/PORT, default 8642),
  Bearer auth. Endpoints confirmed: `/api/sessions/{id}/chat/stream` (SSE), `/api/sessions/{id}/
  messages` (history), `/v1/runs/{id}/stop`+`/approval`, `/health`,`/v1/health`,`/health/detailed`.
  **run_id surfaced on session stream** → stop wireable. SSE events (assistant.delta/tool.progress
  [_thinking]/tool.started|completed|failed/run.completed/done/error) map onto U5 ChatEvent
  (superset). ⚠️ `hermes gateway` (0.17.0) is otherwise the *messaging* gateway; the linked docs
  track `main`. Artifact: construction/u8-http-sse-docker/functional-design/spike-hermes-api.md.
- [x] **U8 Functional Design** (std) — complete, **awaiting approval gate**
  - Inline decisions (D1–D6): one `HermesApiTransport` (drop Acp+Serve); turns via Sessions
    chat/stream + stop via Runs run_id; Docker ephemeral loopback port `-p 127.0.0.1::8642`
    read back; one token = Bearer + API_SERVER_KEY; entrypoint `hermes gateway run`; real-time
    no-cache list. AgentRecord reshape (drop serve_port/serve_auth; add host_port/container_name/
    runtime). L1–L9 logic units; BR-T/D/R/N/O rules; PBT-U8-1..5.
  - Security (advisory/Q9): loopback-only bind + Bearer + secret-off-argv + fail-closed —
    surfaced non-blocking. Resiliency/PBT full.
  - Artifacts: construction/u8-http-sse-docker/functional-design/{spike-hermes-api,domain-entities,
    business-logic-model,business-rules}.md
- [x] **U8 Functional Design** (std) — **APPROVED** (2026-07-01).
- [x] **U8 Infrastructure Design** (LIGHT) — complete, **awaiting approval gate**
  - Deployment-model change recorded: sbx→plain Docker; NEW inbound loopback publish
    (`-p 127.0.0.1::8642` → ephemeral host_port); outbound bridge gw `:9701` unchanged; optional
    `runsc` runtime (default runc, spawn-time fail-fast); docker-build-only image (no sbx load);
    HTTP `/health`+live `docker inspect` (no cache); boot reconcile via `docker ps`.
    Added `container_runtime` config key. Updated shared-infrastructure.md (sbx notes marked historical).
  - Artifacts: construction/u8-http-sse-docker/infrastructure-design/infrastructure-design.md;
    updated construction/shared-infrastructure.md.

- [x] **U8 Infrastructure Design** (LIGHT) — **APPROVED** (2026-07-01, committed 17a9d9b).
- [x] **U8 Code Generation — Part 1 (Plan)** — **APPROVED** (2026-07-01).
- [x] **U8 Code Generation — Part 2 (Generation)** — complete, **awaiting approval gate**
  - All 17 plan steps [x]. Created transport/hermes_api.py + config/doctor.py + 3 test files;
    modified models/settings/dto/base/chat/supervisor/provisioner/images/hermes_config/health/
    names/service/gateway_config/wiring/gateway/control_api/cli(app,render)/Dockerfile/pyproject/
    README + migrated tests+fakes; deleted transport/acp.py, transport/serve.py, test_acp_transport.py.
  - **241 unit+PBT tests pass** (was 211; +30). No new runtime dep (dropped websockets). Editable
    install + entrypoint + import verified; full suite (incl e2e) collects clean.
  - Test authoring: `fork` subagent unavailable in this environment → written inline (full context).
  - Artifacts: construction/u8-http-sse-docker/code/code-summary.md;
    plan construction/plans/u8-http-sse-docker-code-generation-plan.md (all [x]).

- [x] **U8 Code Generation — Part 2 (Generation)** — **APPROVED** (2026-07-01).
- [x] **U8 Build & Test** — complete & **APPROVED** — U8 cycle ✅ COMPLETE
  - Build ✅ (editable + entrypoint + import; image rebuilt: base hermes + aiohttp 3.14.1 +
    `CMD hermes gateway run`). Tests ✅ **243** unit+PBT (was 211; +32) without Docker.
  - Live ✅ (Docker 29.4.0 + hermes 0.17.0 API server + Ollama): doctor; in-container API server
    (/health 200, sessions, 401 on bad key); create --wait + background → running/healthy; chat
    streamed real "PONG" (agent→AI-Gateway→Ollama); history 2-turn replay; gateway stop left
    container running + start reconnected running/healthy; runsc **fail-fast** with gVisor guidance.
  - **3 real defects found & fixed live** (+ 1 non-defect): U8-D2 nested session id
    (`{"session":{"id"}}`), U8-D3 host-port read after **start** (Docker assigns at start not
    create → saga reordered), U8-D4 `/messages` items under `"data"` not `"messages"`. 2 regression
    tests added. U8-D1 = placeholder-key rejection (real minted tokens fine; no change).
  - Artifacts: construction/build-and-test/u8-{build,unit-test,integration-test}-instructions.md,
    u8-build-and-test-summary.md.

## 🔵 NEW CYCLE — U10 Review Remediation (started 2026-07-02)
- **Trigger**: user requested a full-codebase review, then approved ALL 18 findings at the
  most robust level ("미구현 항목은 구현, 추천 제안은 수락; 공격적 리팩토링 허용").
- **Review**: aidlc-docs/reviews/2026-07-02-codebase-review.md (R1–R18 + Decision Record —
  all approved; per-item choices recorded there).
- **Plan (single source of spec)**: aidlc-docs/plans/2026-07-02-review-remediation-plan.md
  — 5 phases: P1 dead-code/comments/refactors (R11–R13) → P2 bug fixes (R1–R8) →
  P3 `agent config` real implementation incl. hermes-schema spike (R9) →
  P4 cancel/Stop-button/markdown/tooltip/remote-history (R10, R15, R18) →
  P5 stop-wait/restart/doctor-upstream/README (R14, R16, R17).
- **Gates**: per-stage approval gates WAIVED for this cycle (blanket user pre-approval);
  audit.md entry required per phase; commit per phase (one-line message, no trailer).
- **Baseline**: 271 unit+PBT green + 3 Playwright e2e; DoD in the plan file.
- [ ] Phase 1 · [ ] Phase 2 · [ ] Phase 3 · [ ] Phase 4 · [ ] Phase 5 · [ ] DoD verified

## Current Status
- **Lifecycle Phase**: CONSTRUCTION (U10 Review Remediation) — plan approved, execution
  pending (to run via goal command; gates waived, audit per phase).
- **Prior**: CONSTRUCTION (U9 Real-time Dashboard via SSE) — ✅ CODE COMPLETE,
  committed 058d4a0.
- **U9 Real-time Dashboard (polling → SSE push)**: Replaced the Web UI's 3s poll of
  `/status` + `/agents?probe=false` with a single `GET /api/events` SSE stream (llama-swap
  style). New EventBus (caduceus/daemon/events.py): coalescing per-subscriber, snapshot-on-
  connect, idle keepalive, fault-isolated. Producers: Registry.on_change (upsert/delete/
  set_session) + Supervisor on_change (post-sweep) → bus.notify. Frontend app.js switched to
  native EventSource (auto-reconnect), removed setInterval polling + post-action refreshes.
  234 unit+PBT (was 223; +11 in tests/unit/test_events.py) + 3 Playwright e2e pass;
  live-verified on the running daemon (correct snapshot, no busy loop). Not yet committed.
- **Prior lifecycle phase**: CONSTRUCTION (U8 HTTP/SSE Transport + Docker Runtime Migration) —
  ✅ COMPLETE & APPROVED (→ Operations placeholder).
- **Current Stage**: — (Operations placeholder).
- **Next Stage**: —
- **U8 HTTP/SSE + Docker Runtime**: ✅ COMPLETE & APPROVED — Requirements + Plan + FD/Spike +
  Infra + CodeGen + Build & Test all approved. 243 tests; live-verified (in-container API server,
  chat stream, history, stop/start reconnect, runsc fail-fast); 3 integration defects fixed.
  Replaced hermes-acp+sbx with a single HTTP/SSE transport over the hermes API server on plain
  Docker containers (optional gVisor); added `caduceus doctor` + `gateway config --runtime`.
- **Prior**: CONSTRUCTION (U7 Performance & Stability) — ✅ COMPLETE & APPROVED.
- **U7 Performance & Stability**: ✅ COMPLETE & APPROVED — Requirements + Plan + FD + CodeGen +
  Build & Test all approved. 228 tests; live-verified (fast `agent ls`, background create, warm
  first chat, gateway stop/start reconnect).
- **U6 Gateway Config**: ✅ COMPLETE & APPROVED — Requirements + Plan + FD + CodeGen + Build & Test all approved. 208/208; live offline + hot-apply verified.
- (prior) U5 Gateway Web UI: 🟢 COMPLETE (committed); U1–U4 + Build & Test: ✅ COMPLETE & APPROVED.
- **U5 Gateway Web UI**: 🟢 COMPLETE pending gate — Requirements + Plan + FD + CodeGen approved; Build & Test done. 174/174 tests; live verified.
- (prior) all 4 units + Build & Test: ✅ COMPLETE & APPROVED.
- **U3 Transport & Chat**: ✅ COMPLETE & COMMITTED (design f244457, code d5e488b)
- **U1 AI-Gateway**: ✅ COMPLETE (committed 8f25e5d)
- **U2 Registry & Provisioner**: ✅ COMPLETE & APPROVED (committed a9439df)
