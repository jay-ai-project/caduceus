# U1 AI-Gateway — API/Integration Layer Summary (code)

## Created (application code)
| File | Purpose |
|---|---|
| `caduceus/aigateway/upstream.py` | `UpstreamClient` — async httpx client, timeouts (R-1), shared pool, `stream()`/`request()` |
| `caduceus/aigateway/auth.py` | `authenticate` / `parse_bearer` — bearer token → agent_id via injected `token_lookup` (BR-1) |
| `caduceus/aigateway/stream.py` | `pump_stream` — SSE pass-through; client-disconnect cancels upstream; mid-stream error → OpenAI error event (BR-5) |
| `caduceus/aigateway/app.py` | `build_aigateway_app(settings, token_lookup, upstream)` → FastAPI: `POST /v1/chat/completions` (stream+unary), `GET /v1/models`, generic `/v1/{path}` (BR-1/5/6/7/8/9) |
| `caduceus/aigateway/__init__.py` | light (no FastAPI import) so pure logic imports without the web framework (M-1) |

## Endpoints
- `POST /v1/chat/completions` — auth → model rewrite (`default`→configured) → forward (stream/unary) → errors normalized.
- `GET /v1/models` — proxy upstream + inject `default` alias; upstream-down still returns `[default]`.
- `ANY /v1/{path}` — generic pass-through (token-stripped, timed, error-mapped).

## Tests (`tests/unit/test_app_aigateway.py`, ASGI + deterministic stub upstream in `tests/conftest.py`)
- 401 (missing/invalid token), default-model rewrite, explicit-model pass-through, SSE streaming, `/v1/models` augmentation, **upstream-down → 502**, and **P6** (stream/unary content equivalence ×3 models).

## Result
- **26/26 tests pass** (`pytest -q`) in an isolated venv (fastapi 0.138, httpx 0.28, hypothesis 6.155). Formal execution + CI is the Build & Test stage.

## Deferred to later units
- Real `token_lookup` + `UpstreamClient` lifecycle wired by the daemon (U4); per-agent override (v2) plugs into `build_route(agent_id=...)`.
