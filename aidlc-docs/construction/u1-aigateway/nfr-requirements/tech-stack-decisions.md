# U1 AI-Gateway — Tech Stack Decisions

Confirms the global stack as applied to U1. (Global choices were locked in earlier gates; recorded here per NFR Requirements + **PBT-09**.)

## Runtime & framework
| Concern | Choice | Rationale |
|---|---|---|
| Language | **Python 3.11+** | hermes ecosystem; async; rich HTTP libs |
| Web framework | **FastAPI** (on Starlette/uvicorn) | async, `StreamingResponse` for SSE, pydantic validation |
| ASGI server | **uvicorn** | standard, supports streaming, runs both listeners |
| Upstream HTTP client | **httpx** (async, `stream()` API) | streaming pass-through, timeouts, connection pooling |
| SSE | Starlette `StreamingResponse` / manual SSE framing | OpenAI-compatible streaming |
| Models/validation | **pydantic v2** | request/error schemas |

## Testing (PBT-09)
| Concern | Choice |
|---|---|
| Test runner | **pytest** |
| Property-based testing | **Hypothesis** (required by PBT extension; supports custom strategies, shrinking, seed reproducibility) |
| HTTP test client | `httpx.ASGITransport` / `starlette.testclient` |
| Upstream stub | a deterministic in-process fake upstream (OpenAI-shaped) for oracle property P6 + error-path tests |

## U1 dependencies (to appear in pyproject)
`fastapi`, `uvicorn[standard]`, `httpx`, `pydantic` ; dev: `pytest`, `pytest-asyncio`/`anyio`, `hypothesis`.

## Key implementation notes (for Code Generation)
- Separate **pure functions** (`resolve_model`, `sanitize_headers`, `map_error`, `augment_models`) from the FastAPI layer → directly unit/property-testable (M-1).
- Stream with `httpx.AsyncClient.stream()` → async-generator → `StreamingResponse`; ensure upstream response is closed on client disconnect (R-3).
- Timeouts via `httpx.Timeout(connect=10, read=120, ...)` (R-1), overridable from caduceus Settings.

## PBT framework note
Hypothesis is the selected PBT framework for the whole project (Python). Recorded here to satisfy **PBT-09** (framework selected + will be a project dependency).
