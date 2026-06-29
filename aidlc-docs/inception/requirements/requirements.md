# Caduceus — Requirements

**Status**: Draft for approval — Requirements Analysis (Comprehensive depth)
**Date**: 2026-06-29

---

## 1. Intent Analysis

| Aspect | Finding |
|---|---|
| **User request** | Build `caduceus`: a CLI + always-on gateway hub that provisions/registers isolated `hermes` agents, proxies their LLM calls (AI-Gateway), and lets the user chat with and configure each agent. |
| **Request type** | New Project (greenfield) |
| **Scope** | System-wide (daemon + proxy + agent registry + transport abstraction + CLI) |
| **Complexity** | Complex |
| **Project type** | Local-first developer tool (single user, single host: Linux/WSL2 + Docker) |

### Source statements (traceability)
- R-SRC-1: "sbx 를 통해 샌드박싱된 환경에서 hermes를 완전 격리시켜서 실행" → FR-A1, NFR-2.
- R-SRC-2: "caduceus 는 자체 gateway를 서비스 ... '등록된' 원격 hermes agent 들과 선택적으로 대화" → FR-G1..G4, FR-A2, FR-C1.
- R-SRC-3: "원격지의 hermes agent는 기본적으로 ... caduceus 를 중앙 proxy (ai-gateway) 로써 경유 ... default model llamacpp/gemma-4-12b" → FR-P1..P6.
- R-SRC-4: "추후 각 hermes-agent 마다 다른 llm 모델이나 llm url을 ... 수정" → FR-P4 (designed-for, v2).
- R-SRC-5: "create agent 를 통해 직접 로컬에 sbx 로 ... provisioning 하고 연결" → FR-A1.
- R-SRC-6: "원격지 hermes 와 일관된 방식 ... 로컬은 acp 로 최적화 ... stream 출력이나 기타 모든 프로토콜이 공통적으로" → FR-C3, FR-C4 (common transport; serve-first, ACP later).
- R-SRC-7: "각 ... hermes agent의 설정 (skills, soul, tools 등) 을 편집" → FR-E1..E3.
- R-SRC-8: "caduceus agent ls ... 상태, 내부 hermes agent의 헬스 상태" → FR-A3, FR-L2.
- R-SRC-9: "caduceus agent chat ... 이전 세션 유지" → FR-C1, FR-C2.

---

## 2. Glossary

- **caduceus daemon (gateway hub)**: long-lived process hosting the AI-Gateway, the agent control/chat hub, and the agent registry/state.
- **caduceus CLI**: thin client that talks to the daemon.
- **Agent**: a hermes instance managed by caduceus. Two kinds:
  - **Managed (local)**: provisioned by caduceus via `sbx` into a Docker sandbox from a hermes-preinstalled image.
  - **Registered (remote)**: an already-running hermes endpoint registered by URL.
- **AI-Gateway**: caduceus's OpenAI-compatible LLM proxy that agents call instead of the LLM directly; forwards to an upstream (default: host llama-swap).
- **Transport**: the common, streaming-capable interface caduceus uses to talk to an agent (v1 implementation: `hermes serve` JSON-RPC/WebSocket; future: `hermes acp` for local).
- **Upstream**: the real LLM backend (default `http://localhost:9292/v1`, model `llamacpp/gemma-4-12b`).

---

## 3. Architecture Overview (text + diagram)

```
                 caduceus CLI  (thin client)
                       |
                       v   local control API (loopback)
        +-----------------------------------+        +-------------------------+
        |        caduceus daemon (hub)      |        | host upstream: llama-swap|
        |  +-----------------------------+  | -----> | localhost:9292/v1        |
        |  | AI-Gateway (LLM proxy)      |  | <----- | model llamacpp/gemma-4-12b|
        |  |  OpenAI-compatible /v1      |  |        +-------------------------+
        |  +-----------------------------+  |
        |  | Agent control / chat hub    |  |   (per-agent override of model/url: v2)
        |  | Agent registry + state      |  |
        |  +-----------------------------+  |
        +------------------+----------------+
                           |  common Transport (streaming): hermes serve (v1)
            +--------------+-------------------------+
            v                                        v
   Managed agent (local)                     Registered agent (remote)
   sbx sandbox + hermes image                existing hermes endpoint (URL)
   hermes serve published to loopback        registered by caduceus
            |                                        |
            +-- LLM calls routed back to caduceus ---+
                base_url = host.docker.internal:<caduceus-port>/v1  (local agents)
```

Text alternative: The CLI calls the daemon over a loopback control API. The daemon contains three parts — AI-Gateway (OpenAI-compatible LLM proxy), the chat/control hub, and the registry/state. Agents are either local (sbx sandbox built from a hermes image, with `hermes serve` published to loopback) or remote (registered endpoint). Agents are configured so their LLM provider `base_url` points back at the caduceus AI-Gateway, which forwards to the upstream llama-swap by default. caduceus talks to agents through a common streaming Transport abstraction whose v1 implementation is `hermes serve`.

---

## 4. Functional Requirements

### 4.1 Daemon & Gateway
- **FR-G1**: caduceus runs as a long-lived daemon exposing a local control API consumed by the CLI.
- **FR-G2**: `caduceus gateway start|stop|status` manages the daemon lifecycle and reports health.
- **FR-G3**: The daemon hosts AI-Gateway, agent chat/control hub, and agent registry/state.
- **FR-G4**: CLI↔daemon transport is loopback-only by default (HTTP on 127.0.0.1 or a Unix socket).

### 4.2 AI-Gateway (LLM proxy)
- **FR-P1**: Expose an OpenAI-compatible API: `POST /v1/chat/completions` (including streaming/SSE) and `GET /v1/models`.
- **FR-P2**: Default behavior routes agent LLM calls to upstream `http://localhost:9292/v1`, default model `llamacpp/gemma-4-12b`.
- **FR-P3**: Upstream base URL and default model are configurable via caduceus config.
- **FR-P4**: (Designed-for, v2) per-agent override of model and/or upstream URL; v1 architecture must not preclude it.
- **FR-P5**: The proxy is reachable from inside sandboxes via `host.docker.internal:<port>`; the daemon binds so both CLI (loopback) and sandbox traffic work.
- **FR-P6**: Streaming is passed through end-to-end (agent ← AI-Gateway ← upstream) without buffering whole responses.

### 4.3 Agent lifecycle
- **FR-A1**: `caduceus agent create --name <n>` provisions a local sandbox via `sbx` from a hermes-preinstalled image, configures hermes to use the caduceus AI-Gateway as its provider, starts the agent's transport endpoint (`hermes serve`), registers it, and verifies connectivity.
- **FR-A2**: `caduceus agent register --name <n> --endpoint <url> [auth]` registers an existing remote hermes endpoint.
- **FR-A3**: `caduceus agent ls` lists all agents with kind (local/remote), sandbox status (local), and hermes health; supports `--json`.
- **FR-A4**: `caduceus agent rm --name <n>` removes an agent; for local it tears down the sandbox, for remote it de-registers only. Destructive action is confirmed or `--force`.
- **FR-A5**: `caduceus agent stop|start --name <n>` stops/starts a managed agent's sandbox; clearly messaged as unsupported for remote agents.
- **FR-A6**: Agent names are unique and validated against sbx naming constraints.

### 4.4 Chat
- **FR-C1**: `caduceus agent chat --name <n>` opens an interactive, streaming chat with the selected agent.
- **FR-C2**: Each agent maintains one persistent session, auto-resumed across `chat` invocations ("이전 세션 유지").
- **FR-C3**: Chat behavior (including streaming) is identical regardless of transport, via the common Transport abstraction.
- **FR-C4**: (Designed-for) an optimized local transport (`hermes acp`) can be added behind the same abstraction without changing chat UX.

### 4.5 Configuration editing
- **FR-E1**: `caduceus agent config ...` edits a **local** managed agent's hermes configuration — skills, soul (`SOUL.md`), tools, and relevant core config — applied inside the sandbox (`sbx exec`/`sbx cp`).
- **FR-E2**: For **remote** agents, configuration is read/observe-only in v1, with a clear message that editing is not yet supported.
- **FR-E3**: Config changes take effect on the agent (restarting the agent's hermes endpoint if required).

### 4.6 Logs & Health
- **FR-L1**: `caduceus agent logs --name <n>` shows the agent's hermes logs (local: from the sandbox).
- **FR-L2**: caduceus performs per-agent health checks — **shallow** (endpoint/process reachable) and **deep** (hermes responsive + AI-Gateway/upstream reachable) — surfaced in `agent ls` and on demand.

---

## 5. Non-Functional Requirements

- **NFR-1 Usability**: one `caduceus` CLI with consistent `agent`/`gateway` subcommands, actionable error messages, `--json` for scriptable output.
- **NFR-2 Portability**: target Linux/WSL2 with Docker; runtime deps: `docker`, `sbx`, and a buildable hermes image; `hermes` on host not required for agents.
- **NFR-3 Performance**: caduceus overhead negligible vs LLM latency; first-token streaming preserved; supports multiple concurrent agents and chats.
- **NFR-4 Observability**: structured daemon logs; per-agent log access; `gateway status` + `agent ls` health views.
- **NFR-5 Maintainability**: Python, packaged for `pipx` install, type-hinted; tests via `pytest` + **Hypothesis** (PBT).
- **NFR-6 Security (baseline good-practice; formal Security extension OFF per Q7=B)**: daemon and AI-Gateway bind to loopback by default; sandbox access via host-gateway only; remote-agent credentials stored locally with restrictive permissions; never log secrets. These are engineering defaults, not extension-enforced blocking constraints.
- **NFR-7 State**: a local state store (registry, agent→session mapping, per-agent settings) written atomically; human-inspectable.

---

## 6. Resiliency Requirements (Resiliency Baseline = ON; scope = personal local tool per R1=A, R2=A)

Applicability is scoped to a single-user localhost tool; cloud/HA rules are N/A with rationale.

- **RES-1 (RESILIENCY-01 criticality)**: daemon = High (hub), AI-Gateway = High (all inference flows through it), agents = Medium (individually replaceable). External dependencies: host llama-swap, Docker/`sbx`, hermes image. Documented here and carried into design.
- **RES-2 (RESILIENCY-02 RTO/RPO/DR)**: **N/A for cross-region DR.** Recovery model = durable local state (FR-NFR-7) + ability to recreate (`create`) or re-`register` agents. No standby infrastructure.
- **RES-3 (RESILIENCY-06 health checks)**: **Applicable** — shallow + deep health per agent (FR-L2) and a daemon self-status (FR-G2).
- **RES-4 (RESILIENCY-10 dependency isolation)**: **Applicable** — explicit timeouts on all external calls (AI-Gateway→upstream, Transport→agent, sbx/docker invocations); graceful degradation when an agent or the upstream is unavailable (mark unhealthy, surface a clear error, never crash the daemon); fail-fast / basic circuit-breaking for repeatedly failing agents.
- **RES-5 (process supervision)**: **Applicable** — the daemon supervises managed agents, reconnects transports, and restarts an agent's hermes endpoint where feasible ("프로세스 자동 재시작").
- **RES-6 (RESILIENCY-05 observability)**: structured logging applicable; metrics/traces/dashboards **N/A** (personal tool) with rationale.
- **RES-7 (RESILIENCY-12 state durability)**: atomic writes to the local state store; optional manual export/backup. Cross-region replication **N/A**.
- **Deferred to NFR Design**: RESILIENCY-03 (change management), RESILIENCY-04 (CI/CD, rollback, deployment style), RESILIENCY-14 (resiliency testing approach), RESILIENCY-15 (incident response) — expected lightweight/N/A for a personal tool; to be decided in NFR Design as the rules permit.
- **N/A with rationale**: RESILIENCY-07 (resiliency posture monitoring), RESILIENCY-08 (multi-zone/region), RESILIENCY-09 (auto-scaling), RESILIENCY-11 (DR strategy), RESILIENCY-13 (failover/failback) — not applicable to a single-host localhost developer tool.

---

## 7. Property-Based Testing (PBT = ON, Full)

- Framework: **Hypothesis** (Python) — recorded for NFR Requirements (PBT-09).
- Property identification (PBT-01) will be performed during Functional Design. Likely candidates:
  - Round-trip (PBT-02): state-store (de)serialization; hermes config render/parse; OpenAI request↔upstream request mapping.
  - Invariant (PBT-03): agent-name validation; provider rewrite always points to the AI-Gateway for local agents.
  - Stateful (PBT-06): agent registry lifecycle (create→ls→stop→start→rm) modeled against a reference state.
- PBT complements example-based tests for business-critical paths (PBT-10).

---

## 8. Constraints & Assumptions

- Host runs llama-swap at `http://localhost:9292/v1` with model `llamacpp/gemma-4-12b`.
- Docker + `sbx` are installed; `sbx` has no native hermes agent, so local agents use the `shell` agent with a custom hermes image (`-t/--template`).
- Inside a sandbox, `localhost` is the container; the host is reached via `host.docker.internal`.
- `hermes serve` requires an auth provider on non-loopback binds; local agents publish the serve port to loopback via `sbx ports`.
- Single user, single host. One persistent session per agent (auto-resume).

---

## 9. Out of Scope (v1 — designed-for but deferred)

- Per-agent LLM model/URL override (FR-P4) — architecture supports it; CLI surface lands in v2.
- Editing configuration of **remote** agents (v1 is read-only).
- Optimized local transport via `hermes acp` (abstraction ready; implementation later).
- Multiple named sessions per agent.
- Multi-host / HA / production deployment.

---

## 10. Acceptance Criteria (high-level)

- AC-1: `caduceus gateway start` brings up the daemon; `gateway status` reports healthy with the AI-Gateway listening.
- AC-2: `caduceus agent create --name a1` provisions a sandbox, the agent is configured to use the AI-Gateway, and `agent ls` shows it running + healthy.
- AC-3: `caduceus agent chat --name a1` streams a model response; exiting and re-running `chat` continues the same session.
- AC-4: With the upstream (llama-swap) stopped, `chat` fails gracefully with a clear message and the daemon stays up; `agent ls` shows the upstream/agent as unhealthy.
- AC-5: `caduceus agent register --name r1 --endpoint <url>` registers a remote agent and `chat` works through the same interface.
- AC-6: `caduceus agent config` changes a local agent's skills/tools/soul, verified inside the sandbox.
- AC-7: `caduceus agent rm --name a1` removes the agent and tears down its sandbox.

---

## 11. Summary

Caduceus is a local-first **gateway hub** (daemon) plus a thin CLI. It (1) provisions isolated hermes agents in `sbx` sandboxes from a custom image or registers remote hermes endpoints, (2) acts as a central **AI-Gateway** so agents route inference through caduceus to a configurable upstream (default llama-swap / `llamacpp/gemma-4-12b`), and (3) lets the user chat (streaming, session-persistent) with and configure each agent through a **common transport abstraction** (serve-first; ACP optimization later). Resiliency is scoped to a personal tool (health checks, timeouts, graceful degradation, process supervision, durable local state); cloud-scale resiliency rules are N/A. Testing uses pytest + Hypothesis (PBT, full). Security extension is off by choice, with sensible loopback defaults retained.
