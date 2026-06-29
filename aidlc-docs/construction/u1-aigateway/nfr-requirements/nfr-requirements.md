# U1 AI-Gateway — NFR Requirements

Scope: non-functional requirements specific to the AI-Gateway (LLM proxy). Cross-cutting NFRs from `requirements.md` (NFR-1..7) are inherited; this doc records U1-specific targets and **tunable defaults** (adjust at the approval gate if desired).

> No new clarifying questions were raised: the tech stack is already decided globally and U1's NFRs follow directly from FR-P1..P6 + the functional design. Concrete defaults below are the proposed values.

## Performance
- **P-1 Proxy overhead**: added latency (excluding upstream) target **< 50 ms** p95 per request; streaming first-byte added latency **< 20 ms**.
- **P-2 Streaming**: chunks forwarded incrementally; **no full-body buffering**; memory per stream O(chunk), not O(response).
- **P-3 Throughput**: bounded by upstream; gateway must not be the bottleneck for a single local user.

## Scalability / Concurrency
- **S-1**: fully async I/O; support **modest concurrency** (default soft target: up to **16 concurrent streams**) without thread-per-request. No hard cap enforced in v1; bounded by upstream.
- **S-2**: stateless hot path (no per-request server state beyond the read-only token→agent map + config).

## Reliability (RESILIENCY-10 at U1 boundary)
- **R-1 Timeouts** (tunable config): upstream **connect = 10 s**, streaming **idle/read = 120 s** per chunk, unary **total = 300 s**. On expiry → 504.
- **R-2 Graceful degradation**: upstream unreachable/error → OpenAI error (502/5xx); a single failed request never crashes the daemon.
- **R-3 Cancellation**: client disconnect cancels the upstream request (no orphan calls).

## Security (baseline good-practice; Security extension OFF)
- **SEC-1 AuthN**: per-agent bearer token required (BR-1); unknown/missing → 401.
- **SEC-2 Secret hygiene**: agent token stripped before upstream and **redacted in logs** (BR-4); upstream credentials never logged.
- **SEC-3 Bind**: AI-Gateway binds the Docker-reachable interface only as needed (Infrastructure Design decides exact bind); not 0.0.0.0 broadly unless required.

## Observability (RESILIENCY-05 scaled)
- **O-1**: structured logs per request (agent_id, path, status, latency, bytes) — **no secrets**.
- **O-2**: counters for requests/errors/timeouts exposed via `gateway status` (lightweight; full metrics platform N/A for a local tool).

## Maintainability / Testability
- **M-1**: U1 logic (model resolution, error mapping, header sanitation) is **pure/unit-testable** in isolation from FastAPI.
- **M-2 PBT**: properties P1–P7 (functional design) implemented with **Hypothesis**; example-based tests pin the happy/err paths (PBT-10).

## Out of scope (v1)
- Per-agent model/upstream override (v2) — design leaves the seam (route keyed by agent token).
- Rate limiting / quotas per agent (future).
