# Performance Test Instructions

## Applicability
Caduceus is a **personal, local-first tool** (Resiliency operational context R1=A;
RTO/RPO/DR N/A). No throughput/concurrency SLAs were specified in Requirements or
the per-unit NFRs. Formal load/stress testing is therefore **out of scope for v1**.

What *does* matter for a streaming LLM proxy is **added latency and streaming
fidelity** — the AI-Gateway must not buffer or materially delay the upstream stream.
The checks below are lightweight smoke measurements, not a load campaign.

## Soft targets (best-effort, not SLAs)
- **Gateway overhead**: AI-Gateway adds negligible latency vs. calling the upstream directly (proxy + auth + header/model augmentation only).
- **Streaming**: tokens are forwarded incrementally (no full-response buffering); first-chunk latency tracks the upstream.
- **Memory**: daemon footprint stable across a chat session (no per-turn leak).

## Lightweight checks

### 1. Streaming-passthrough smoke (no buffering)
```bash
# Compare time-to-first-byte: direct upstream vs. through the AI-Gateway.
curl -sN -o /dev/null -w 'ttfb=%{time_starttransfer}s\n' \
  http://localhost:9292/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"llamacpp/gemma-4-12b","stream":true,"messages":[{"role":"user","content":"count to 20"}]}'

curl -sN -o /dev/null -w 'ttfb=%{time_starttransfer}s\n' \
  $GW/v1/chat/completions -H "Authorization: Bearer $TOK" \
  -H 'Content-Type: application/json' \
  -d '{"model":"llamacpp/gemma-4-12b","stream":true,"messages":[{"role":"user","content":"count to 20"}]}'
```
- **Pass**: gateway TTFB ≈ direct TTFB (small constant overhead); chunks arrive progressively, not all at the end.

### 2. Timeout behaviour (graceful degradation, RESILIENCY-10)
- Point the gateway at an unreachable/slow upstream; confirm configured timeouts (connect 10s / idle 120s / unary 300s) trigger and return a mapped error rather than hanging.

### 3. Memory stability (light)
- Run a ~20-turn chat against one agent; sample daemon RSS at start and end (`ps`/`/proc`); expect no monotonic growth.

## Optimization
If smoke checks reveal regressions:
1. Confirm streaming uses incremental forwarding (no accumulate-then-send).
2. Check httpx client reuse / connection pooling to the upstream.
3. Re-measure TTFB after the fix.

> Formal load/stress tooling (k6/locust) can be added later if caduceus moves
> beyond single-user local use; tracked as a future enhancement, not a v1 gate.
