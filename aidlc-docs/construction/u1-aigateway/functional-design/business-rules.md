# U1 AI-Gateway — Business Rules

| ID | Rule | Rationale / source |
|---|---|---|
| **BR-1 Auth** | A request whose bearer token does not map to a known agent → **401** `authentication_error`. Missing `Authorization` → 401. (Q1=A) | FR-P5, identification/security |
| **BR-2 Model resolution** | If body `model` is absent or equals `default` (case-insensitive) → set outgoing `model = config.default_model` (`your-model`). Otherwise forward `model` unchanged. (Q2) | FR-P2, FR-P3 |
| **BR-3 Upstream target (v1)** | Always forward to `config.upstream_base_url`. Per-agent base_url/model override is **v2** (keyed by agent token). | FR-P2, FR-P4 |
| **BR-4 Token handling** | Strip the agent bearer token before forwarding upstream; attach `upstream_auth` only if configured. The agent token MUST NOT appear in upstream requests or logs (redact). | NFR-6, PBT P4 |
| **BR-5 Streaming** | If `stream:true` (chat/completions) → SSE pass-through, flush chunks immediately, propagate `[DONE]`. On client disconnect → cancel upstream. On mid-stream upstream error → emit one OpenAI error SSE event, then close. | FR-P6 |
| **BR-6 Timeouts** | Apply connect timeout + per-chunk idle timeout (streaming) / total timeout (unary). On timeout → **504** `timeout_error`. No unbounded waits. | RESILIENCY-10 |
| **BR-7 Error mapping** | Upstream non-2xx: if body already OpenAI-error-shaped, pass status+body through; else wrap into OpenAI error with upstream status. Upstream unreachable/connection error → **502** `upstream_error`. A single request failure never crashes the daemon. | RESILIENCY-10 (graceful degradation) |
| **BR-8 /v1/models** | Proxy upstream models and inject the `default` alias (dedup). If upstream unreachable → return a minimal list `[default]` + log the error (do not 5xx the model list). | FR-P1 |
| **BR-9 Generic pass-through** | Any `/v1/*` path/method not specially handled is forwarded as-is (after BR-4 token strip, BR-6 timeouts, BR-7 error mapping). | Q3=A, FR-P1 |
| **BR-10 Header hygiene** | Strip hop-by-hop headers (Connection, Keep-Alive, Transfer-Encoding, etc.); preserve Content-Type and OpenAI-relevant headers. | correctness |
| **BR-11 No request mutation beyond model** | Except for the `model` rewrite (BR-2) and header sanitation (BR-4/BR-10), the request body is forwarded unchanged (byte-preserving where possible). | transparency |

## Validation rules
- Reject malformed JSON on endpoints that require a JSON body with **400** `invalid_request_error` (pass-through of upstream's own validation is also acceptable for generic paths).
- `stream` is honored only where OpenAI defines it (chat/completions, completions); ignored elsewhere.

## Error type catalog (OpenAI shape)
| http_status | type |
|---|---|
| 400 | invalid_request_error |
| 401 | authentication_error |
| 404 | invalid_request_error (unknown route, if not generically proxied) |
| 502 | upstream_error |
| 504 | timeout_error |
| 5xx | upstream_error |

## Resiliency/PBT linkage
- BR-6/BR-7 satisfy RESILIENCY-10 (timeouts, graceful degradation) at the U1 boundary.
- BR-2/BR-4/BR-7/BR-8 are covered by PBT properties P1–P7 (see business-logic-model.md) + example-based tests (PBT-10).
