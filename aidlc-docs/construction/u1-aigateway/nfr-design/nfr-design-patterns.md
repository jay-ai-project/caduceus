# U1 AI-Gateway — NFR Design Patterns

How U1's NFR requirements are realized as patterns. Plus the resolved project-wide resiliency process decisions (recorded once here).

## Resilience patterns (RESILIENCY-10)
| Pattern | Application in U1 | Notes |
|---|---|---|
| **Timeout** | `httpx.Timeout(connect=10, read=120, write, pool)`; unary total 300s | tunable via Settings; R-1 |
| **Cooperative cancellation** | client disconnect → cancel upstream `stream()` context | R-3; avoids orphan upstream calls |
| **Error normalization** | `ErrorMapper`: exceptions/upstream status → OpenAI error JSON | BR-7; never leak stack/secret |
| **Graceful degradation** | upstream unreachable → 502; per-request failure isolated | daemon stays up; RESILIENCY-10 |
| **No-retry at proxy** | U1 does NOT auto-retry LLM calls | retries belong to the agent/hermes; avoids duplicate generations & double latency |
| **Bulkhead (lightweight)** | each request/stream is an independent async task; shared `AsyncClient` pool with limits | one slow stream doesn't block others |

> Circuit-breaking lives in **U3 Supervisor** (per-agent), not U1. U1 stays a transparent, stateless proxy.

## Performance patterns
- **Streaming pass-through**: async generator pipes upstream SSE chunks straight to the client; no full-body buffering (P-2).
- **Connection pooling**: a single shared `httpx.AsyncClient` (keep-alive) for upstream (P-1).
- **Pure hot-path functions**: `resolve_model`, `sanitize_headers`, `map_error`, `augment_models` are synchronous/pure → cheap + testable.

## Security patterns (baseline; Security extension OFF)
- **Bearer-token auth middleware**: validates `Authorization` against the token→agent map; 401 on miss (BR-1).
- **Token stripping**: agent token removed before upstream; replaced with upstream creds if configured (BR-4).
- **Log redaction filter**: a logging filter scrubs `Authorization`/token-like values (PBT P4).
- **Minimal bind**: AI-Gateway bound only to the container-reachable address chosen in Infrastructure Design (not broadly 0.0.0.0 unless required).

## Observability patterns (RESILIENCY-05 scaled)
- Structured per-request log: `{agent_id, method, path, status, latency_ms, stream, bytes}` (no secrets).
- In-process counters: `requests_total`, `errors_total`, `timeouts_total`, `active_streams` → surfaced by `gateway status`.

---

## Resolved project-wide Resiliency process decisions (RESILIENCY-03/04/14/15)
Asked once at U1 NFR Design; apply to the whole project.

| Rule | Decision | Implication |
|---|---|---|
| **RESILIENCY-03 Change mgmt** | **N/A — exempt** (personal/internal tool) | no formal CAB; rationale documented |
| **RESILIENCY-04 CI/CD + rollback + deploy** | **GitHub Actions** (pytest + Hypothesis, **seed logged** per PBT-08); **rollback = reinstall previous pinned version** (pip/pipx); **deploy = direct/in-place install** | CI config produced in Build & Test; satisfies PBT-08 |
| **RESILIENCY-14 Resiliency testing** | **Lightweight fault-injection integration tests** — simulate upstream/agent down, assert graceful degradation (aligns with AC-4) | included in Build & Test |
| **RESILIENCY-15 Incident response** | **Lightweight** — log-based troubleshooting/triage note + restart procedures (daemon/agent); no formal on-call | troubleshooting note produced in Build & Test |

These propagate to U2–U4 (inherited) and to the Build & Test stage.
