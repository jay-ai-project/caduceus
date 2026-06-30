# Integration Test Instructions

## Purpose
Validate the cross-unit seams that are **intentionally excluded** from unit tests
because they cross a real process / IO / network boundary: the AI-Gateway → upstream
LLM hop, sbx provisioning of a hermes agent, the real `hermes serve` JSON-RPC/WS
transport, and the CLI → daemon Control-API loopback. These require a live host
environment (Docker Engine + `sbx` + `hermes` image + an upstream LLM).

> Local-first tool — no cloud. "Services" below are local processes/containers.

## Environment-dependency matrix
| Scenario | Docker | sbx | hermes image | upstream LLM (llama-swap) | caduceus daemon |
|---|---|---|---|---|---|
| 1. CLI ↔ daemon Control API | — | — | — | — | ✅ |
| 2. AI-Gateway → upstream | — | — | — | ✅ | ✅ |
| 3. Provision local agent (sbx) | ✅ | ✅ | ✅ | — | ✅ |
| 4. Agent → AI-Gateway → upstream (E2E LLM) | ✅ | ✅ | ✅ | ✅ | ✅ |
| 5. Chat over real `hermes serve` transport | ✅ | ✅ | ✅ | ✅ | ✅ |
| 6. Supervisor fault-injection (RESILIENCY-14) | ✅ | ✅ | ✅ | — | ✅ |

## Setup Integration Test Environment

### 1. Build the agent image and start prerequisites
```bash
# hermes agent image (pinned hermes-agent 0.17.0; context images/hermes/)
sbx template build -t caduceus/hermes:0.17.0 images/hermes/   # or the project's documented build cmd
docker info >/dev/null            # confirm Docker Engine reachable
sbx ls >/dev/null                 # confirm sbx CLI works
# Upstream LLM (host llama-swap) reachable at the configured base url, e.g.:
curl -s http://localhost:9292/v1/models | head
```

### 2. Configure & start the daemon
```bash
. .venv/bin/activate
export CADUCEUS_UPSTREAM_BASE_URL=http://localhost:9292/v1
export CADUCEUS_DEFAULT_MODEL=llamacpp/gemma-4-12b
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
       -d '{"model":"llamacpp/gemma-4-12b","stream":true,"messages":[{"role":"user","content":"ping"}]}'
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

### Scenario 5 — Chat over the real `hermes serve` transport
- **Description**: exercises `transport/serve.py` `_WIRE_*` real JSON-RPC/WS framing + session recreate (U3 Q1) — the path unit-untested by design.
- **Steps**: open a chat, send 2 turns, confirm session persistence/auto-resume; cancel mid-stream (cooperative cancel, U3 Q6).
- **Expected**: ordered streamed events; second turn shares session; cancel stops the stream without killing the agent.

### Scenario 6 — Supervisor fault-injection (RESILIENCY-14, lightweight)
- **Description**: validate Supervisor defaults (30s sweep; 2 consecutive fails → restart; exp backoff 5/15/45s cap ~120s; 3 restart-fails → circuit open → `failed`; reset on manual start) against a real agent.
- **Steps**: kill the agent container out-of-band (`docker stop cad-demo`); observe Supervisor detect → restart with backoff; repeat to force circuit-open; then `caduceus agent start demo` to reset.
- **Expected**: state transitions and backoff timing match the design; circuit opens after 3 restart failures; manual start clears it; all transitions logged.

## Cleanup
```bash
caduceus agent rm demo           # remove sandbox + registry entry + token
caduceus gateway stop            # stop daemon, release single-instance lock
```

## Notes
- Scenarios 3–6 are **manual / host-dependent** smoke procedures (no automated harness in v1); run them on a host with Docker + sbx + hermes + upstream LLM before release.
- Remote (registered) agents are **read-only** and **cannot be started/stopped** by caduceus (BR-A10) — Scenarios 3 and 6 apply to local sbx agents only.
