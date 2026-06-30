# Build and Test Summary — U5 Gateway Web UI

## Build Status
- **Build Tool**: hatchling (PEP 517). Python 3.12.3, `.venv`.
- **Build**: ✅ editable install (`pip install -e .`) OK; wheel build OK. Console script `caduceus` intact.
- **Packaging**: ✅ wheel includes `caduceus/webui/assets/{index.html,styles.css,app.js}` (shipped via `packages=["caduceus"]`; the initial `force-include` was removed after it caused a duplicate-file build error).
- **New runtime deps**: none (Starlette `StaticFiles` ships with FastAPI).

## Test Execution Summary

### Unit + Property-Based Tests
- **Total**: **174 passed** (was 154 at end of U4 cycle; **+20** for U5), 0 failures, ~4.4s.
- New/extended coverage:
  - Event model: thinking/tool_call/message round-trip incl. `meta`; `meta` omitted when None; thinking/tool non-terminal; normalize_stream passes them through with one terminal.
  - PBT-W1: terminal-event invariant holds with arbitrary token/thinking/tool_call/message sequences. PBT-W2: tool_call round-trip with populated `meta`.
  - ACP mapping: `agent_thought_chunk`→thinking, `tool_call`/`tool_call_update`→tool_call (id/status/input/output, truncation), malformed update ignored (not fatal); history replay coalesces user/assistant turns; failure/no-session → [].
  - ChatService.history matrix (local turns / remote [] / sessionless [] / unknown [] / error-swallowed []).
  - Control API: `/`→`/ui/` redirect, `/ui/` serves index, `/agents/{n}/history` returns turns + unknown→404.
  - probe=false skips the health handshake (dashboard-poll perf).

### Integration Tests (LIVE — Docker 29.4.0 + sbx + hermes 0.17.0 + llama-swap)
Daemon started (`caduceus gateway start`), real local agent `webui-test` provisioned, exercised over HTTP:
| Scenario | Result |
|---|---|
| `GET /` → 307 redirect to `/ui/` | ✅ |
| `GET /ui/` → 200 `text/html` (index) + `app.js`/`styles.css` 200 | ✅ |
| `GET /status`, `GET /agents` JSON | ✅ |
| **BR-W1**: `/ui/` and `/` on AI-Gateway `:9701` → **404** (UI loopback-only) | ✅ |
| Local provision (`agent create`) with live progress | ✅ created (running) |
| **Streaming chat with thinking** | ✅ 107 `thinking` + 162 `token` + **exactly 1 `done`** (terminal invariant holds live); answer correct (391) |
| Second turn | ✅ thinking + token + done; "PONG" |
| **History** (`GET /agents/{n}/history`) | ✅ **4 turns** replayed (user/assistant, coalesced, correct text) via ACP `session/load` |
| Unknown-agent history → 404 | ✅ |
| Cleanup (`agent rm`, `gateway stop`) | ✅ |

**Tool-call display**: the ACP→event mapping is unit-verified (thought + tool_call + tool_call_update → events with meta). A *live* tool invocation depends on the agent having tools enabled and a prompt that triggers one; the gemma test prompts produced thinking but no tool call, so live tool rendering was not forced (mapping covered by unit tests).

## Defects found & fixed (during U5 integration)
- **K — dashboard poll was slow/dangerous**: `GET /agents` ran a per-agent ACP health **handshake** every call (~6 s for 1 agent; spawns `sbx exec hermes acp` per poll). For a 3 s-polling dashboard this piled up processes. **Fix**: `GET /agents?probe=false` (used by the UI) skips the handshake and returns cached `last_health`; the **Supervisor sweep now caches `last_health`** so the cached value stays fresh in the background. CLI `agent ls` keeps `probe=true` (unchanged). UI poll interval raised to 5 s to keep the sbx-status reconcile non-overlapping.
  - *Note*: a transient `stopped/unhealthy` can appear in a `probe=true` listing run **concurrently** with an active chat (two acp spawns contend); the dashboard (probe=false) is unaffected. Pre-existing CLI behavior, not a U5 regression.

## Overall Status
- **Build**: ✅ Success (incl. wheel with assets).
- **All Tests**: ✅ 174/174 unit+PBT pass; live integration of UI serving, streaming chat (thinking), and history replay passing.
- **Performance**: N/A as a gate (personal local tool); dashboard responsiveness addressed (Defect K).
- **Ready for Operations**: Yes (Operations is a workflow placeholder in v1).
