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

### Agent image (pulled automatically on first `agent create`)
```bash
docker pull nousresearch/hermes-agent:v2026.6.19   # official image, ~3.8 GB
```
- caduceus uses the **official** `nousresearch/hermes-agent` image (pinned version tag). It
  ships the full toolchain (Python, Node+Playwright/Chromium, ffmpeg, git, ripgrep, Docker CLI,
  curl/wget, ...) and runs the API server via `gateway run` (:8642). No custom Dockerfile.

## Verify build
- `python -c "import caduceus"` → OK.
- `pip wheel . -w dist` → wheel builds (ships `caduceus/webui/assets/`).
- No `websockets` dependency (dropped in U8).

## Troubleshooting
- **`docker build` fails on pip/git** → check network + the pinned `HERMES_GIT_REF`.
- **Container has no `aiohttp`** → old image; rebuild with this Dockerfile.
