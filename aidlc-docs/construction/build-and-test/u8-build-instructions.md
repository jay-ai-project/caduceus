# U8 Build Instructions (HTTP/SSE Transport + Docker Runtime)

## Prerequisites
- **Python 3.11+**, `pip`.
- **Docker Engine** (for local agents). Optional **gVisor (`runsc`)** for `runtime=runsc`.
- **Upstream LLM** (OpenAI-compatible), e.g. Ollama at `http://localhost:11434/v1`.

## Build steps
```bash
python -m venv .venv && . .venv/bin/activate
pip install -e .            # installs `caduceus`; deps: fastapi, uvicorn, httpx, pydantic, typer
caduceus --help             # verify entry point
```

### Build the agent image (done automatically on first `agent create`)
```bash
docker build -t caduceus/hermes:0.17.0 \
  --build-arg HERMES_VERSION=0.17.0 --build-arg HERMES_GIT_REF=v2026.6.19 images/hermes
```
- The image installs `hermes-agent` (base) + `aiohttp` (required by the API-server platform)
  and runs `hermes gateway run` (API server on :8642).

## Verify build
- `python -c "import caduceus"` → OK.
- `pip wheel . -w dist` → wheel builds (ships `caduceus/webui/assets/`).
- No `websockets` dependency (dropped in U8).

## Troubleshooting
- **`docker build` fails on pip/git** → check network + the pinned `HERMES_GIT_REF`.
- **Container has no `aiohttp`** → old image; rebuild with this Dockerfile.
