# U8 — Build & Test Summary (HTTP/SSE Transport + Docker Runtime)

## Build
- ✅ Editable install + `caduceus` entry point + `import caduceus` clean. No new runtime dep
  (dropped `websockets`; `httpx` reused). Full suite (incl e2e) collects clean.
- ✅ Agent image rebuilt from the U8 Dockerfile: `caduceus/hermes:0.17.0` — base `hermes-agent`
  + `aiohttp 3.14.1`, `CMD hermes gateway run`. (The pre-existing image was the old ACP build —
  `sleep infinity`, no aiohttp — confirming the Dockerfile change was required.)

## Tests
- ✅ **243 unit + PBT pass** (211 prior + 32 U8) on CPython 3.12, `.venv`, **without Docker**
  (fakes + `httpx.MockTransport`). Includes PBT-U8-1..5 and 2 live-shape regression tests.
- Browser E2E (`tests/e2e`, Playwright) not part of this gate (unchanged; runner territory).

## Live integration (real Docker 29.4.0 + hermes 0.17.0 API server + Ollama)
All scenarios PASS:
1. **doctor** — docker OK, image OK, `runc` OK, gVisor absent (warn), daemon warn/ok. `--json` ok.
2. **in-container API server** — `hermes gateway run` serves `/health` (200), `POST /api/sessions`
   (Bearer), rejects a bad key (401).
3. **agent create** (`--wait` and background) — reaches **running/healthy**; container published on
   `127.0.0.1:<ephemeral>→8642`; hermes config copied in; warm session created.
4. **chat/stream** — streamed a real LLM turn end-to-end (agent→AI-Gateway→Ollama), terminal-event
   invariant held; session persisted.
5. **history** — `/agents/e2e/history` replays both turns from `/api/sessions/{id}/messages`.
6. **gateway stop/start reconnect** — stop left the container running; start reconciled it back to
   running/healthy (endpoint/host_port recomputed), chat-able.
7. **runtime config + runsc fail-fast** — `gateway config --runtime runsc` hot-applied; a create
   then **failed fast** with gVisor install guidance (no silent fallback to runc).

## Defects found & fixed during integration
- **U8-D1 (not a defect)** — hermes refuses to start the API server if `API_SERVER_KEY` looks like
  a placeholder (e.g. "testkey"). Real `mint_token()` secrets (43 chars) are accepted — no change.
- **U8-D2** — create-session response is `{"session":{"id":...}}` (nested), not flat →
  `_session_id_of` now reads the nested `session.id` (+ flat fallback). Regression test added.
- **U8-D3** — Docker assigns the published ephemeral host port at **start**, not `create` →
  reordered the saga to create → put_file(config) → **start** → read host_port → endpoint.
- **U8-D4** — `/messages` returns items under `"data"` (OpenAI-list), not `"messages"` →
  `_parse_history` now reads `data` (+ `messages`/bare-list fallback). Regression test added.

## Security (advisory, Q9 — non-blocking)
- Loopback-only publish (`127.0.0.1::8642`) confirmed live; Bearer required (bad key → 401);
  strong minted tokens; secrets via env/`docker cp` 600, not argv; fail-closed errors. No blocking
  findings.

## Performance
- N/A as a gate (personal local tool). `agent ls` is real-time (parallel `/health` + one
  `docker ps`), no cache — acceptable at the scales tested.

## Overall
- **Build**: ✅  **Tests**: ✅ 243  **Live**: ✅  **Ready for Operations**: Yes.
