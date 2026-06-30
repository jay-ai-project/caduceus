# Build and Test Summary

_Caduceus — local-first gateway hub + CLI for sandboxed hermes agents. All 4 units
(U1 AI-Gateway · U2 Registry & Provisioner · U3 Transport & Chat · U4 CLI/Daemon/Config)
complete._

## Build Status
- **Build Tool**: Python 3.12.3 + pip, hatchling backend (PEP 517).
- **Build Status**: ✅ **Success**
- **Build Artifacts**:
  - editable install `caduceus 0.1.0`
  - console script `caduceus` (groups: `agent`, `gateway`) — verified via `caduceus --help`
  - wheel `dist/caduceus-0.1.0-py3-none-any.whl` — `python -m build --wheel` succeeded
  - import sanity: all **43** modules import cleanly (incl. protocol/daemon/client seams unit-untested by design)
- **Build Time**: a few seconds (pure-Python, no compilation).

## Test Execution Summary

### Unit Tests (`tests/unit` + `tests/pbt`)
- **Total Tests**: **146**
- **Passed**: **146**
- **Failed**: **0**
- **Breakdown**: 123 deterministic unit + 23 property-based (Hypothesis)
  - includes 9 new `AcpTransport` tests (protocol mapping, session resume/recreate, auto-approve permission, cooperative cancel, health) driving a fake `hermes acp` process.
  - PBT: aigateway 6 · registry 4 (stateful) · transport 4 (incl. stateful Supervisor) · u4 9
- **Coverage stance**: real protocol/IO seams (daemon serve/fork, real Control-API HTTP client, real `sbx`/`hermes acp`) are exercised in integration (all PASS), not the unit suite.
- **Status**: ✅ **Pass**

### Integration Tests — EXECUTED on host (Docker 29.4.0 + sbx + hermes 0.17.0 + llama-swap)
All 6 scenarios executed end-to-end against the live host and **PASS**. Integration
surfaced 10 real defects (all fixed); the largest was that `hermes serve` requires a
full Node web build, which prompted an approved **transport pivot to `hermes acp`
(stdio JSON-RPC)** for local agents. Validated by an end-to-end spike (agent →
AI-Gateway → LLM returned "PONG") and then via the production code path.

| Scenario | Result | Notes |
|---|---|---|
| 1. CLI ↔ daemon Control API | ✅ **PASS** | `gateway status` / `agent ls` (human + `--json`), exit 0; real `ControlAPIClient` loopback |
| 2. AI-Gateway auth/proxy | ✅ **PASS** | no-auth / bogus bearer → `401` OpenAI error shape; valid agent token → `/v1/chat/completions` 200 |
| 3. Provision local agent | ✅ **PASS** | `agent create demo` → sandbox `cad-demo` running, lifecycle=running, health=healthy (no serve port — ACP) |
| 4. E2E LLM round-trip | ✅ **PASS** | agent (`hermes acp`) → AI-Gateway (`172.17.0.1:9701`) → llama-swap; streamed answer |
| 5. Chat over real transport | ✅ **PASS** | `agent chat demo` → streamed tokens from the code-generated config (no manual edits) |
| 6. Supervisor fault-injection (RES-14) | ✅ **PASS** | manual stop/start lifecycle OK; out-of-band crash → supervisor auto-restarted in ~50 s (`restarted agent demo (attempt 1)`) |

**Transport pivot (approved):** local agents now use `AcpTransport` (`hermes acp`
stdio JSON-RPC, spawned per chat via `sbx exec -i`) instead of `ServeTransport`
(`hermes serve` web dashboard). `hermes serve` needs a Node-built web dist
(contradicts the slim-image decision); ACP needs only the lightweight `[acp]`
extra and no network port. Remote agents keep `ServeTransport`. The host daemon
speaks raw newline JSON-RPC (no new caduceus dependency).

**Defects found & fixed (all ✅):**

| # | Defect | Resolution |
|---|---|---|
| A | `GatewayService.start()` started the Supervisor **before** the event loop → `no running event loop`, daemon crash on boot | Start the Supervisor inside the `_serve` loop (`daemon/gateway.py`) |
| B | Dockerfile pinned non-existent git tag `v0.17.0`; real hermes-agent tags are date-based (`v2026.6.19` == release 0.17.0) | `HERMES_GIT_REF` build-arg (`Dockerfile`, `agents/images.py`) |
| C | `sbx create shell` called without the required workspace **PATH** | Provisioner creates/passes a per-agent workspace dir |
| D | Host-Docker image invisible to **sbx's** separate image store → `pull failed` | `ImageBuilder` bridges via `docker save \| sbx template load` (`_ensure_in_sbx`) |
| E | `ControlAPIClient` one 30 s timeout for all calls → `ReadTimeout` during provisioning | Long per-call timeout for create/register (`PROVISION_TIMEOUT`) |
| F | **`hermes serve` requires a full Node web build** (absent from the slim image; `--skip-build` refuses without a prebuilt dist) | **Pivot to `hermes acp`** (stdio); add `[acp]` extra to the image; new `AcpTransport` + `Transport.for_agent` local→ACP |
| G | `start_serve` published the port with `sbx ports --publish … --json` (wrong) | Obsolete — serve/port path removed entirely under ACP |
| H | `provisioner.status` mis-parsed `sbx ls --json` (it returns `{"sandboxes":[…]}`, not a list) → `'str' object has no attribute 'get'` | Parse `data["sandboxes"]`; tolerate non-dict items |
| I | hermes won't send `OPENAI_API_KEY` to a non-openai.com base_url (#28660), so the agent got `401` from the AI-Gateway | Write the bearer inline as the custom provider's `api_key` in the sandbox config (perms 600) + `key_env` backup |
| J | `sbx start` is not a valid command → `agent start` failed | `provisioner.start` uses `sbx exec … true` (sbx auto-starts a stopped sandbox) |

Also hardened: the post-create health probe is now best-effort (a probe error no
longer rolls back a successfully-provisioned agent).

**Post-integration improvements (from usage feedback):**
- **Per-turn latency / probe noise** — `ChatService` now **reuses one `hermes acp`
  process per agent** across turns (pooled transport, per-agent serialized,
  evicted on stop/remove/broken/shutdown) instead of spawning per turn. hermes'
  cold-start + provider/model probing (the repeated `/api/tags`, `/props`,
  `/v1/models/default` 404s) is paid once, not every turn. Measured: cold turn
  ~13 s → warm turn ~8 s. (Idle reaping of pooled processes is a future nicety.)
- **Periodic probe storm** — the Supervisor's 30 s **deep** health sweep was
  spawning a throwaway `hermes acp` per local agent each cycle, re-triggering the
  same probe 404s on a loop. Local ACP agents have no persistent process to probe,
  so deep health now **skips the transport sub-probe for local agents** (running
  sandbox = liveness; real failures surface on chat). Verified: 0 probes / 0
  gateway requests over 75 s idle with a running agent, while supervisor
  auto-restart still recovers a stopped sandbox (~40 s).
- **Agent file outputs** — the ACP session `cwd` is now the agent's bind-mounted
  host workspace (`AgentRecord.workspace_path`), so files the agent writes land in
  `~/.caduceus/agents/<sandbox>/workspace/` on the host and persist (verified:
  agent-written `hello.txt` appeared on the host). (sbx mounts at the same path
  as host and can't remap onto `/root`, which would also shadow `~/.hermes`.)

- **Status**: ✅ **All 6 scenarios PASS** (control plane + agent data plane); +2 usage-driven improvements verified live.

### Performance Tests
- **Response Time / Throughput / Error Rate**: no SLAs (personal local tool; R1=A). Lightweight streaming-passthrough TTFB, timeout, and memory-stability smoke checks documented.
- **Status**: 🔵 **N/A as a gate** (best-effort smoke checks only).

### Additional Tests
- **Contract Tests**: N/A — single package, no inter-service contracts; the only external contract is OpenAI-compatibility, exercised in integration Scenario 2.
- **Security Tests**: N/A — Security Baseline extension **disabled** (Requirements Q7=B). Note: per-agent bearer-token auth on the AI-Gateway and `600` token-file perms are validated in integration Scenarios 2–3.
- **E2E Tests**: covered by integration Scenarios 4–5 (agent → AI-Gateway → upstream; chat over real transport).

## Extension Compliance (enabled extensions only)
- **Resiliency Baseline** (enabled, full/blocking): ✅
  - RESILIENCY-04 (CI/rollback): GitHub Actions pytest+Hypothesis with **seed logging** — `ci` Hypothesis profile (`print_blob=True`) wired in `tests/conftest.py`; rollback = reinstall pinned wheel.
  - RESILIENCY-05/-06/-10/-12 (logging, health checks, timeouts/graceful degradation, state durability): exercised by unit tests + integration Scenarios 2/3/6.
  - RESILIENCY-14 (fault-injection): integration Scenario 6 (Supervisor kill/restart/circuit-open).
  - RESILIENCY-15 (triage/restart): `caduceus gateway start|stop|status` + `~/.caduceus/logs/`.
- **Property-Based Testing** (enabled, full/blocking): ✅ — 23 Hypothesis properties incl. stateful registry and stateful Supervisor models; reproducible seeds via `HYPOTHESIS_PROFILE=ci`.
- **Security Baseline**: disabled — not enforced (logged).

## Overall Status
- **Build**: ✅ Success
- **Automated Tests**: ✅ Pass (146/146 unit + PBT).
- **Integration**: ✅ **All 6 scenarios PASS** live (control plane + agent data plane: provision → chat → supervise). 10 defects found and fixed, incl. an approved transport pivot to `hermes acp` (stdio).
- **Ready for Operations**: **Yes** — full local-agent lifecycle works end-to-end on the host; automated suite green; build reproducible (image auto-loaded into sbx).

## Next Steps
Automated build + test pass. Run the documented integration scenarios on a host with
Docker + `sbx` + hermes image + upstream LLM before a real deployment, then proceed to
the **Operations** phase for deployment/monitoring planning.
