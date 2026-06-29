# U1 AI-Gateway — Code Generation Plan

**Unit**: U1 — AI-Gateway. **Workspace root**: `/mnt/f/Workspace/Caduceus` (greenfield, single Python package).
**This plan is the single source of truth for U1 code generation.** Application code → workspace root (NEVER `aidlc-docs/`). Markdown summaries → `aidlc-docs/construction/u1-aigateway/code/`.

## Unit context
- Implements FR-P1..P6 (OpenAI-compatible proxy, default-model rule, streaming, generic `/v1/*`, error/timeout handling).
- Depends on: a **token→agent** lookup (owned by U2 Registry) and **Settings** (owned by U4 `common/`). For isolated build/test, U1 defines minimal `common/` scaffolding + accepts the token lookup via injection (a callable). U4 will extend `common/` and wire the real Registry.
- Design inputs: `functional-design/*`, `nfr-design/*`, `infrastructure-design/*`, `shared-infrastructure.md`.

## Target files (application code)
```
pyproject.toml                         # package + deps + tool config (created here; extended by later units)
caduceus/__init__.py
caduceus/common/__init__.py
caduceus/common/errors.py              # ProxyError + OpenAI error shaping
caduceus/common/settings.py            # Settings subset: upstream_base_url, default_model, timeouts, binds (env>file>default)
caduceus/common/logging.py             # structured logger + token redaction filter
caduceus/aigateway/__init__.py
caduceus/aigateway/models.py           # pydantic-light schemas / typed dicts (ModelList item, etc.)
caduceus/aigateway/routing.py          # PURE: resolve_model(), build_route()
caduceus/aigateway/headers.py          # PURE: sanitize_headers()
caduceus/aigateway/errors_map.py       # PURE: map_error() -> OpenAI error JSON
caduceus/aigateway/models_augment.py   # PURE: augment_models() default alias
caduceus/aigateway/upstream.py         # UpstreamClient (httpx async, timeouts, pool, stream)
caduceus/aigateway/auth.py             # AuthDependency: bearer token -> AgentIdentity (injected token map)
caduceus/aigateway/stream.py           # StreamPump: upstream SSE -> client SSE (+ cancel/error)
caduceus/aigateway/app.py              # build_aigateway_app(settings, token_lookup, upstream_client) -> FastAPI
tests/conftest.py                      # fixtures: stub upstream app, settings, token map
tests/unit/test_routing.py             # example-based
tests/unit/test_errors_map.py
tests/unit/test_models_augment.py
tests/unit/test_app_aigateway.py       # ASGITransport: 401, default-rewrite, SSE, 502, /v1/models
tests/pbt/test_aigateway_properties.py # Hypothesis P1–P5, P7 (+ P6 oracle vs stub)
```

---

## Steps

- [x] **Step 1 — Project scaffolding (greenfield)**: create `pyproject.toml` (package `caduceus`, entry point `caduceus` placeholder, deps: fastapi, uvicorn[standard], httpx, pydantic; dev: pytest, pytest-asyncio/anyio, hypothesis; tool config: pytest, hypothesis seed-logging note), package `__init__` files, minimal `common/` (settings/errors/logging).
- [x] **Step 2 — Business logic (pure)**: `routing.py`, `headers.py`, `errors_map.py`, `models_augment.py`, `models.py`. Implements BR-2 (model rule), BR-4/BR-10 (header hygiene), BR-7 (error mapping), BR-8 (models alias). [FR-P1..P3]
- [x] **Step 3 — Business logic unit tests**: `tests/unit/test_routing.py`, `test_errors_map.py`, `test_models_augment.py` (example-based, PBT-10 anchors).
- [x] **Step 4 — Property-based tests (Hypothesis)**: `tests/pbt/test_aigateway_properties.py` implementing P1 (default→model), P2 (pass-through), P3 (idempotence), P4 (token never in sanitized headers/logs), P5 (well-formed errors), P7 (models alias dedup). Seed logging enabled (PBT-08).
- [x] **Step 5 — API/integration layer**: `upstream.py` (httpx client w/ timeouts), `auth.py` (bearer dependency), `stream.py` (SSE pump w/ disconnect+mid-stream-error), `app.py` (`build_aigateway_app(...)` mounting `/v1/chat/completions`, `/v1/models`, generic `/v1/{path}`). Implements BR-1, BR-5, BR-6, BR-9. [FR-P4..P6]
- [x] **Step 6 — API layer tests + upstream stub**: `tests/conftest.py` (deterministic OpenAI-shaped stub upstream as an ASGI app; fixtures), `tests/unit/test_app_aigateway.py` (401 missing/invalid token, default-model rewrite forwarded, SSE happy path, upstream-down→502, `/v1/models` alias). Add **PBT P6** (stream-concat == unary body vs stub).
- [x] **Step 7 — Repository layer**: N/A for U1 (no DB; token map injected, read-only) — documented as N/A.
- [x] **Step 8 — Summaries & docs**: write `aidlc-docs/construction/u1-aigateway/code/business-logic-summary.md` and `api-layer-summary.md`; module docstrings; minimal `README.md` stub (project intro + U1 note).
- [x] **Step 9 — Deployment artifacts**: none beyond `pyproject.toml` for U1 (CI workflow + Dockerfile come in U2/Build&Test) — documented.

## Story/Requirement traceability
- FR-P1 (Step 2,5), FR-P2/P3 (Step 2), FR-P4 seam (Step 5 routing keyed by identity), FR-P5 (Step 5 app bind via settings; infra), FR-P6 (Step 5 stream).
- Resiliency: BR-6/BR-7 timeouts+graceful (Step 5), fault path tested (Step 6 → full AC-4 in Build&Test).
- PBT-01 properties → Step 4 + Step 6 (P6).

## Notes
- U1 code must import-cleanly and pass `pytest` in isolation (stub upstream; injected token map). No daemon wiring yet (U4).
- Total: ~16 files (9 source incl. scaffolding, ~5 test files, 2 summaries). Estimated scope: small-medium.
