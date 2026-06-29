# U2 Registry & Provisioner — NFR Design Patterns

Realizes U2's NFRs. Project-wide resiliency process decisions (CI/rollback/testing/incident) were settled at U1 NFR Design and are inherited.

## Resilience patterns (RESILIENCY-10/12)
| Pattern | Application | Notes |
|---|---|---|
| **Saga / compensation** | `create` is a multi-step saga (ensure image → create sandbox → configure hermes → start serve+publish → mint+register → verify). Each step records a compensating action; on failure they run in reverse (teardown sandbox, discard token, no persist). | BR-A7 |
| **Timeout on every subprocess** | all `sbx`/`docker` calls bounded (exec 30s / create 300s / ls·ports 15s); no unbounded waits | RESILIENCY-10 |
| **Bounded retry (transient only)** | retry a small, fixed number of times w/ backoff for clearly *transient* failures (port-publish race, transient docker error); never retry deterministic failures (bad name, image build error) | conservative |
| **Atomic state write + single-writer** | `state.json` written via temp + `os.replace`; one in-process `asyncio.Lock` serializes all mutations | RESILIENCY-12 |
| **Reconciliation / self-heal** | `list` reconciles registry vs `sbx ls` (sandbox missing→failed, stopped→stopped); state converges to reality after external changes | R-4 |
| **Idempotent lifecycle ops** | `stop`/`start`/`remove` are idempotent (no error on already-in-target-state where sensible) | BR-A9 |
| **Fault isolation** | one agent's failed op never crashes the daemon or blocks other agents | RESILIENCY-10 |

## Performance patterns
- **Lazy, idempotent image build**: `ImageBuilder.ensure_image` builds only if absent/stale; subsequent creates skip it.
- **Health caching**: `last_health` cached on the record; deep checks only on demand (`--deep`).
- **Async orchestration**: subprocess calls are awaited concurrently where safe.

## Security patterns (baseline; Security ext OFF)
- **Secret-at-rest**: token + state files perms 600 (dir 700) via `os.chmod`.
- **No shell / argv form**: `create_subprocess_exec` (no `shell=True`) → no injection; tokens passed via env/file/stdin into the sandbox, not argv, to keep them out of `ps`.
- **Redaction**: lifecycle logs route through the redaction filter.

## Observability
- Structured op log: `{op, name, kind, result, duration_ms}`; secrets redacted. Per-agent hermes logs via Provisioner (consumed by U4 FR-L1).

## Resolved project-wide decisions (inherited from U1 NFR Design)
- CI = GitHub Actions (pytest + Hypothesis, seed-logged); rollback = reinstall previous version; deploy = direct install; resiliency testing = lightweight fault injection (here: simulate `sbx`/`docker`/upstream failures); incident = log-based triage + restart.
