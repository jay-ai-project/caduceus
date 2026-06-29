# AI-DLC State Tracking

## Project Information
- **Project Name**: Caduceus
- **Project Type**: Greenfield
- **Start Date**: 2026-06-29T12:19:17Z
- **Current Stage**: INCEPTION - Requirements Analysis
- **Requirements Depth**: Comprehensive (multi-component system)
- **Complexity / Scope**: Complex / System-wide (gateway daemon + AI-proxy + agent registry + transport abstraction + CLI)

## Target Architecture (working hypothesis — pending Requirements approval)
- **caduceus daemon (gateway hub)**: hosts (a) AI-Gateway = OpenAI-compatible LLM proxy that agents route through (forwards to host llama-swap by default, per-agent override later), (b) agent chat/control hub, (c) agent registry + state.
- **caduceus CLI**: thin client to the daemon (`agent create|register|ls|chat|config|rm`, `gateway start|stop|status`).
- **Agents (two kinds)**: (1) *managed/local* — provisioned via `sbx` + hermes pre-installed image; (2) *registered/remote* — existing hermes endpoint registered by URL.
- **Transport abstraction**: common streaming interface; remote via `hermes serve` (JSON-RPC/WS), local optimization via `hermes acp` (stdio over `sbx exec -i`).
- **LLM routing**: agent `hermes` `custom_providers.base_url` → caduceus AI-Gateway (`host.docker.internal:<port>/v1`) → llama-swap (`localhost:9292/v1`, model `llamacpp/gemma-4-12b`).

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
- **Host LLM endpoint**: http://localhost:9292/v1 (llama-swap), model `llamacpp/gemma-4-12b`

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
- [~] **U2 Registry & Provisioner**: [x] FD · [x] NFR-Req · [x] NFR-Design · [x] Infra · [ ] CodeGen
  - Spike: hermes-agent v0.17.0 (NousResearch git project, official Dockerfile); custom_providers list (name/base_url/model/api_mode); bearer via OpenAI-SDK key. Image pinned 0.17.0; agent→AIGW via `172.17.0.1:9701` + OPENAI_API_KEY=token.
  - Infra: **slim image (Q1=A)**; provisioning sequence (create→cp config+env→serve 0.0.0.0:9119→sbx ports publish→health); added `AgentRecord.serve_auth`. Build-time validation items flagged for Build&Test.
  - FD decisions: name→`cad-<name>` (Q1=A); remote = token+guidance, read-only config (Q2=A); **remote start/stop not possible (user-confirmed, BR-A10)**. Stateful registry PBT planned.
- [ ] **U3 Transport & Chat**: FD · NFR-Req · NFR-Design · Infra · CodeGen
- [ ] **U4 CLI / Daemon / Config**: FD · NFR-Req · NFR-Design · Infra · CodeGen
- [ ] Build and Test (after all units)

## Current Status
- **Lifecycle Phase**: INCEPTION → (about to enter CONSTRUCTION)
- **Current Stage**: CONSTRUCTION — U2 Registry & Provisioner → Infrastructure Design complete (awaiting approval)
- **Next Stage**: U2 → Code Generation (registry/provisioner/image)
- **U1 AI-Gateway**: ✅ COMPLETE (committed 8f25e5d)
