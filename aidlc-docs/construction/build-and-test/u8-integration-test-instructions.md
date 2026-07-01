# U8 Integration Test Instructions

Live end-to-end against real Docker + hermes API server + Ollama. Unit/PBT run without Docker.

## Setup
```bash
. .venv/bin/activate
export CADUCEUS_UPSTREAM_BASE_URL=http://localhost:11434/v1
export CADUCEUS_DEFAULT_MODEL=<a-model-in-ollama>
caduceus gateway start -d          # daemon: Control API :9700 + AI-Gateway :9701
caduceus doctor                    # docker/image/runtime/gVisor/daemon readiness
```

## Scenarios
1. **doctor** — reports Docker OK, image (built or not), `container runtime runc` OK, gVisor
   available/absent, daemon running. `--runtime runsc` when absent → `doctor` FAIL + guidance.
2. **image build (in-container API server)** — `docker run` the image with `API_SERVER_ENABLED=true
   API_SERVER_KEY=k API_SERVER_HOST=0.0.0.0 API_SERVER_PORT=8642 -p 127.0.0.1::8642`; then
   `GET /health` (200) and `POST /api/sessions` (Bearer) return a session id.
3. **agent create (background)** — `caduceus agent create a1`; returns immediately (`creating`);
   `agent ls` shows `creating → running/healthy` within seconds; container published on a
   loopback port; hermes config copied in.
4. **chat/stream** — `caduceus agent chat a1 "ping"`; streamed tokens (+ thinking/tool cards in
   Web UI). Terminal-event invariant holds. Session persisted; second turn resumes.
5. **stop (cancel)** — cancel a turn → ends promptly (`done{cancelled}`); Runs `stop` hit when a
   run_id was seen.
6. **history** — `GET /agents/a1/history` (or Web UI) replays prior turns from `/messages`.
7. **gateway stop/start reconnect** — `caduceus gateway stop` leaves the container running;
   `caduceus gateway start` reconciles it back to `running/healthy`, chat-able (endpoint/host_port
   recomputed).
8. **runtime config** — `caduceus gateway config --runtime runsc` persists + hot-applies; a new
   `agent create` with runsc unavailable **fails fast** with gVisor guidance (no silent runc).
9. **agent ls latency** — real-time (parallel `/health` + one `docker ps`), no cache.

## Cleanup
```bash
caduceus agent rm a1 --force
caduceus gateway stop
```
