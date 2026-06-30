# U1 AI-Gateway — Business Logic Model

Technology-agnostic logic for the OpenAI-compatible proxy. Owns FR-P1..P6.

## Request lifecycle

```
receive ProxyRequest
   -> authenticate(agent_token) -> AgentIdentity
        if not authenticated: return ProxyError(401 authentication_error)
   -> resolve_route(identity, request) -> Route
   -> sanitize_headers(request)            # strip agent token + hop-by-hop; attach upstream_auth
   -> if path == /v1/models:  proxy + augment_with_default_alias
      elif request.stream:    forward_streaming(Route, body)   # SSE pass-through
      else:                   forward_unary(Route, body)
   -> on any upstream failure/timeout: map_error -> ProxyError (graceful; daemon stays up)
```

### resolve_route (v1)
- `target.base_url = config.upstream_base_url` (always, in v1; per-agent override is v2).
- `effective_model = resolve_model(request.model)`.
- `rewrite_model = (request.model.lower() == "default")`.

### resolve_model(m) — the Q2 rule
- if `m` is absent OR `m.lower() == "default"` → `config.default_model` (`your-model`).
- else → `m` (pass-through unchanged).
- When `rewrite_model`, the outgoing body's `model` field is replaced with `effective_model`; otherwise body is forwarded byte-for-byte.

### forward_streaming (SSE pass-through)
- Open upstream stream with connect timeout; then read chunks under a per-chunk idle timeout.
- Emit each upstream SSE chunk to the client immediately (no buffering of the full body).
- Propagate terminal `data: [DONE]`.
- **Client disconnect** → cancel the upstream request (no orphan upstream calls).
- **Upstream error mid-stream** → emit one OpenAI-style error SSE event, then close.

### forward_unary
- Forward request, await response under total timeout, return status+body pass-through.

### /v1/models
- Proxy upstream `GET /v1/models`; merge an injected `{id:"default", object:"model", owned_by:"caduceus"}` alias (dedup if upstream already lists it).
- If upstream is unreachable → return a minimal list containing only the `default` alias (so agents still have a usable model) and log the upstream error.

### generic /v1/* (Q3=A)
- Any other path/method is forwarded as-is (token stripped, timeouts applied, errors mapped).

---

## Data flow (text)
agent hermes → ProxyRequest → [auth] → [route/model resolution] → [header sanitize] → UpstreamClient → upstream LLM → (stream|body) → agent. Errors normalize to OpenAI error JSON at any step.

## Concurrency
- Fully async; many agents/requests concurrent. No shared mutable state in the hot path except read-only config + a token→agent lookup (read-mostly).

## Integration points
- **Inbound**: agents' hermes (OpenAI client) over `host.docker.internal`.
- **Outbound**: upstream LLM (Ollama) via UpstreamClient.
- **Config**: caduceus Settings (upstream_base_url, default_model, timeouts); token→agent map from Registry (U2) — injected, read-only here.

---

## Testable Properties (PBT-01 — Hypothesis)

| # | Property | Category | Sketch |
|---|---|---|---|
| P1 | `resolve_model("default")==default_model`; case-insensitive (`"DEFAULT"`, `"Default"`) | Invariant | generate case variants of "default" |
| P2 | `resolve_model(m)==m` for all `m` not equal-ignore-case to "default" (incl. empty-after-strip handling) | Invariant / pass-through | generate arbitrary model strings excluding the sentinel |
| P3 | `resolve_model` is idempotent for non-sentinel: `resolve(resolve(m))==resolve(m)` | Idempotence | |
| P4 | Agent bearer token is **never** present in the sanitized upstream headers, and never in log output | Invariant (security) | generate random tokens; assert absent downstream |
| P5 | Every failure path yields a well-formed OpenAI error object (`error.type`, `error.message` present; `http_status` in allowed set) | Invariant | fuzz upstream statuses/exceptions via stub |
| P6 | Streaming vs unary equivalence against a **stub upstream**: concatenated stream chunks == unary body for identical input | Oracle | deterministic stub upstream (not the real LLM) |
| P7 | `/v1/models` response always contains the `default` alias exactly once (dedup) | Invariant | generate upstream lists with/without "default" |

Example-based tests (PBT-10) will pin: 401 on missing token, default-rewrite happy path, SSE happy path, upstream-down → 502/504.
