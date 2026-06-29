# U2 Registry & Provisioner — NFR Requirements

Cross-cutting NFRs (requirements.md) + global stack are inherited from U1. This records U2-specific targets/tunable defaults. No new clarifying questions (stack locked; NFRs derive from FD).

## Performance
- **P-1 Provisioning latency**: dominated by image build/pull + `sbx create` (seconds first time; image build is one-time). caduceus orchestration overhead small; show progress for long ops.
- **P-2 ls/health**: `agent ls` fast on cached health; `--deep` bounded by per-agent probe timeout (default 5 s).
- **P-3 State I/O**: registry read/write is small JSON; negligible.

## Concurrency / Scalability
- **S-1**: agent operations are async; **state writes serialized** by an in-process lock (single daemon).
- **S-2**: provisioning operations may run concurrently for distinct names; same-name operations are serialized. Modest scale (a handful of agents).

## Reliability (RESILIENCY-10/12)
- **R-1 Subprocess timeouts**: every `sbx`/`docker` call has an explicit timeout (defaults: exec 30 s, create 300 s, ls/ports 15 s); non-zero exit → actionable error.
- **R-2 Create rollback**: failure after sandbox creation → best-effort teardown; no half-registered agents (BR-A7).
- **R-3 State durability**: atomic write (temp + `os.replace`); never leave a truncated `state.json`; schema `version` for migration.
- **R-4 Reconciliation**: `ls` reconciles registry vs `sbx ls` (sandbox missing/stopped) so state self-heals after external changes.

## Security (baseline; Security ext OFF)
- **SEC-1 Token storage**: tokens stored in `~/.caduceus` with file perms 600; directory perms 700; never logged (redaction).
- **SEC-2 No secret in args**: avoid passing tokens on the command line where avoidable (prefer env/stdin/file inside the sandbox) to keep them out of process listings.

## Observability
- Structured logs for each lifecycle op (name, op, result, duration); secrets redacted. Per-agent hermes logs surfaced via Provisioner (FR-L1 lives in U4, uses Provisioner here).

## Maintainability / Testability
- **M-1**: `Provisioner`, `ImageBuilder`, and the transport health probe are **interfaces**, mocked in unit tests; real sbx/docker exercised only in Build & Test integration + RESILIENCY-14 fault-injection.
- **M-2 PBT**: registry round-trip + **stateful registry model** (Hypothesis stateful) per P-U2-1/5.

## Out of scope (v1)
- Parallel bulk provisioning limits/quotas; per-agent resource (cpu/mem) tuning beyond sbx defaults (could pass through later).
- Remote agent process lifecycle (start/stop) — not caduceus-managed (BR-A10).
