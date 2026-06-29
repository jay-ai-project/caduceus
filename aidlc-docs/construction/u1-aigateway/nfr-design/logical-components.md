# U1 AI-Gateway — Logical Components

Internal decomposition of the `aigateway/` module. Distinguishes **pure** (unit/property-testable in isolation) from **I/O** components.

| Component | Kind | Responsibility | Pattern(s) | Pure? |
|---|---|---|---|---|
| **AIGatewayApp** | I/O (FastAPI) | route `/v1/*`; wires middleware + handlers; emits SSE | framework glue | no |
| **AuthMiddleware** | I/O-light | parse bearer token → AgentIdentity via token map; 401 on miss | bearer auth | no (reads map) |
| **RouteResolver** | **pure** | `resolve_model` + build UpstreamTarget (v1 = config upstream) | model-resolution rule | **yes** |
| **HeaderSanitizer** | **pure** | strip agent token + hop-by-hop; attach upstream auth | token hygiene | **yes** |
| **UpstreamClient** | I/O | async forward via shared `httpx.AsyncClient`; timeouts; `stream()` | timeout, pooling | no |
| **StreamPump** | I/O | bridge upstream SSE → client SSE; handle disconnect + mid-stream error | streaming pass-through, cancellation | no (thin) |
| **ErrorMapper** | **pure** | exception/status → ProxyError → OpenAI error JSON | error normalization | **yes** |
| **ModelsAugmenter** | **pure** | merge `default` alias into upstream model list (dedup) | — | **yes** |
| **MetricsCounter** | I/O-light | increment request/error/timeout/active-stream counters | observability | no (atomic) |
| **LogRedactionFilter** | **pure** | scrub token-like values from log records | secret hygiene | **yes** |

## Wiring (request path)
```
AIGatewayApp
  -> AuthMiddleware (401 | AgentIdentity)
  -> RouteResolver (Route: effective_model, target)         [pure]
  -> HeaderSanitizer (clean headers)                        [pure]
  -> UpstreamClient.stream()/request()  --- httpx --->  upstream
       (stream) -> StreamPump -> client SSE
       (unary)  -> response body -> client
  -> ErrorMapper on any failure                             [pure]
  -> MetricsCounter + structured log (redacted)
```

## Testability mapping (PBT-01 → components)
- P1/P2/P3 (model resolution) → **RouteResolver**
- P4 (token never leaks) → **HeaderSanitizer** + **LogRedactionFilter**
- P5 (well-formed errors) → **ErrorMapper**
- P6 (stream/unary equivalence) → **StreamPump** + **UpstreamClient** against a deterministic upstream stub
- P7 (models default alias) → **ModelsAugmenter**

The pure components carry the business-critical invariants and are the primary PBT targets; the thin I/O components are covered by example-based + integration tests (incl. the RESILIENCY-14 fault-injection tests).

## No infrastructure middleware needed
- No queue / cache / external circuit-breaker for U1 (transparent proxy). The only "logical infrastructure" is the shared httpx connection pool and the in-process counters. (Circuit-breaking is U3.)
