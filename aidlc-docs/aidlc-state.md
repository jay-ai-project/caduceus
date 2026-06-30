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

## Current Status
- **Lifecycle Phase**: CONSTRUCTION (U6 Gateway Config) — Functional Design complete pending approval.
- **Current Stage**: CONSTRUCTION — U6 Functional Design (light) complete, awaiting approval.
- **Next Stage**: CONSTRUCTION — U6 Code Generation after approval.
- (prior) U5 Gateway Web UI: 🟢 COMPLETE (committed); U1–U4 + Build & Test: ✅ COMPLETE & APPROVED.
- **U5 Gateway Web UI**: 🟢 COMPLETE pending gate — Requirements + Plan + FD + CodeGen approved; Build & Test done. 174/174 tests; live verified.
- (prior) all 4 units + Build & Test: ✅ COMPLETE & APPROVED.
- **U3 Transport & Chat**: ✅ COMPLETE & COMMITTED (design f244457, code d5e488b)
- **U1 AI-Gateway**: ✅ COMPLETE (committed 8f25e5d)
- **U2 Registry & Provisioner**: ✅ COMPLETE & APPROVED (committed a9439df)
