# Integration Test Instructions

> **EXECUTED 2026-06-30 — all 6 scenarios PASS.** During execution the local
> transport was pivoted from `hermes serve` (web dashboard; needs a Node build)
> to **`hermes acp` (stdio JSON-RPC)**, spawned per chat via `sbx exec -i`. The
> caduceus daemon auto-builds the image and loads it into sbx's store
> (`docker save | sbx template load`). References to `hermes serve` / published
> ports below are historical for **local** agents (remote agents still use
> `hermes serve`). See `build-and-test-summary.md` for results and Findings A–J.

## Purpose
Validate the cross-unit seams that are **intentionally excluded** from unit tests
because they cross a real process / IO / network boundary: the AI-Gateway → upstream
LLM hop, sbx provisioning of a hermes agent, the real `hermes serve` JSON-RPC/WS
transport, and the CLI → daemon Control-API loopback. These require a live host
environment (Docker Engine + `sbx` + `hermes` image + an upstream LLM).

> Local-first tool — no cloud. "Services" below are local processes/containers.

## Environment-dependency matrix
| Scenario | Docker | sbx | hermes image | upstream LLM (Ollama) | caduceus daemon |
|---|---|---|---|---|---|
| 1. CLI ↔ daemon Control API | — | — | — | — | ✅ |
| 2. AI-Gateway → upstream | — | — | — | ✅ | ✅ |
| 3. Provision local agent (sbx) | ✅ | ✅ | ✅ | — | ✅ |
| 4. Agent → AI-Gateway → upstream (E2E LLM) | ✅ | ✅ | ✅ | ✅ | ✅ |
| 5. Chat over real `hermes serve` transport | ✅ | ✅ | ✅ | ✅ | ✅ |
| 6. Supervisor fault-injection (RESILIENCY-14) | ✅ | ✅ | ✅ | — | ✅ |

## Setup Integration Test Environment

### 1. Prerequisites (the daemon builds + loads the image automatically)
```bash
# The caduceus daemon builds images/hermes (pinned hermes-agent 0.17.0 == git
# tag v2026.6.19, with the [acp] extra) on first `agent create`, then loads it
# into sbx's image store via `docker save | sbx template load`. To pre-build:
docker build -t caduceus/hermes:0.17.0 --build-arg HERMES_GIT_REF=v2026.6.19 images/hermes
docker info >/dev/null            # confirm Docker Engine reachable
sbx ls >/dev/null                 # confirm sbx CLI works
# Upstream LLM (host Ollama) reachable at the configured base url, e.g.:
curl -s http://localhost:11434/v1/models | head
```

### 2. Configure & start the daemon
```bash
. .venv/bin/activate
export CADUCEUS_UPSTREAM_BASE_URL=http://localhost:11434/v1
export CADUCEUS_DEFAULT_MODEL=your-model
caduceus gateway start            # foreground; add -d to daemonize
caduceus gateway status           # expect: running, Control API 127.0.0.1:9700, AI-Gateway <bridge-ip>:9701
```

## Test Scenarios

### Scenario 1 — CLI → Daemon Control API (loopback)
- **Description**: real `ControlAPIClient` HTTP calls over `127.0.0.1:9700` (the seam stubbed in unit tests).
- **Steps**: `caduceus gateway status`; `caduceus agent ls --json`.
- **Expected**: exit 0; valid JSON; human renderer for non-`--json`. Bad daemon state → exit code 1, clear message.
- **Cleanup**: none.

### Scenario 2 — AI-Gateway → Upstream LLM
- **Description**: OpenAI-compatible proxy forwards to the configured upstream, augments `/v1/models`, maps errors, streams SSE.
- **Steps** (from the host, using a provisioned agent's bearer token `$TOK`):
  ```bash
  GW=$(caduceus gateway status --json | python -c "import sys,json;print(json.load(sys.stdin)['aigateway_url'])")
  curl -s $GW/v1/models -H "Authorization: Bearer $TOK" | head
  curl -sN $GW/v1/chat/completions -H "Authorization: Bearer $TOK" \
       -H 'Content-Type: application/json' \
       -d '{"model":"your-model","stream":true,"messages":[{"role":"user","content":"ping"}]}'
  ```
- **Expected**: `/v1/models` lists the upstream model(s); streaming returns SSE `data:` chunks ending in `[DONE]`; missing/invalid bearer → 401; upstream error mapped to OpenAI error shape.

### Scenario 3 — Provision a local agent (sbx)
- **Description**: registry + provisioner create a `cad-<name>` sandbox from the hermes image, mint a bearer token, wire `custom_providers.base_url` → AI-Gateway advertise host (bridge IP `172.17.0.1:9701`).
- **Steps**: `caduceus agent create demo`; `caduceus agent ls`; inspect `~/.caduceus/state.json` (token file perms `600`).
- **Expected**: agent `cad-demo` listed `running`; container present in `sbx ls`; health check passes (protocol handshake only, no LLM spend).
- **Cleanup**: `caduceus agent rm demo`.

### Scenario 4 — End-to-end LLM round-trip (agent → AI-Gateway → upstream)
- **Description**: the full default routing path from inside the sandbox.
- **Steps**: `caduceus agent chat demo --message "say hello in one word"` (or exec hermes inside the sandbox).
- **Expected**: streamed assistant tokens; the agent's LLM call egressed through the AI-Gateway (verify a `/v1/chat/completions` entry in `~/.caduceus/logs/`).

### Scenario 5 — Chat over the real ACP transport
- **Description**: exercises `transport/acp.py` against `hermes acp` (stdio JSON-RPC) spawned via `sbx exec -i` — initialize → session/new (or session/load to resume, U3 Q1) → session/prompt; the path unit-tested with a fake process and integration-tested here.
- **Steps**: `caduceus agent chat demo "..."`; send 2 turns, confirm session persistence/auto-resume; cancel mid-stream (cooperative cancel → `session/cancel`, U3 Q6).
- **Expected**: streamed `agent_message_chunk` tokens; second turn shares the session; cancel stops the stream without killing the agent. **Result: PASS** — streamed "PONG"/"OK".

### Scenario 6 — Supervisor fault-injection (RESILIENCY-14, lightweight)
- **Description**: validate Supervisor defaults (30s sweep; 2 consecutive fails → restart; exp backoff; circuit open after repeated restart failures) against a real agent. Under ACP "restart" = ensure the sandbox is running again (`sbx exec` auto-starts).
- **Steps**: stop the sandbox out-of-band (`sbx stop cad-demo`); observe the Supervisor detect → restart; (optionally repeat to force circuit-open); `caduceus agent start demo` to reset.
- **Expected**: agent auto-recovers to running/healthy. **Result: PASS** — recovered in ~50 s (`supervisor: restarted agent demo (attempt 1)`).

## Cleanup
```bash
caduceus agent rm demo           # remove sandbox + registry entry + token
caduceus gateway stop            # stop daemon, release single-instance lock
```

## Notes
- Scenarios 3–6 are **manual / host-dependent** smoke procedures (no automated harness in v1); run them on a host with Docker + sbx + hermes + upstream LLM before release.
- Remote (registered) agents are **read-only** and **cannot be started/stopped** by caduceus (BR-A10) — Scenarios 3 and 6 apply to local sbx agents only.
