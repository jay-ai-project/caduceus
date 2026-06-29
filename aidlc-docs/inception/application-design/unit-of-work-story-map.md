# Requirement → Unit Map — Caduceus

User Stories were skipped (single persona; comprehensive requirements). This map ties **functional requirements** and **acceptance criteria** to units, so every requirement has an owning unit.

## Functional requirements → units

| FR | Description | Unit |
|---|---|---|
| FR-G1..G4 | Daemon, control API, gateway lifecycle, loopback channel | U4 |
| FR-P1 | OpenAI-compatible `/v1` (chat/completions stream, models) | U1 |
| FR-P2 | Default route to llama-swap + default model | U1 |
| FR-P3 | Upstream/model configurable | U1 |
| FR-P4 | Per-agent override (designed-for, v2) | U1 |
| FR-P5 | Reachable via host.docker.internal | U1 (+ U4 bind) |
| FR-P6 | Streaming pass-through | U1 |
| FR-A1 | `agent create` local provisioning | U2 |
| FR-A2 | `agent register` remote | U2 |
| FR-A3 | `agent ls` (status + health) | U2 (+ U4 render) |
| FR-A4 | `agent rm` | U2 |
| FR-A5 | `agent stop/start` | U2 |
| FR-A6 | Name uniqueness/validation | U2 |
| FR-C1 | Interactive streaming chat | U3 (+ U4 CLI UX) |
| FR-C2 | Persistent session auto-resume | U3 |
| FR-C3 | Uniform behavior across transports | U3 |
| FR-C4 | Pluggable optimized local transport (ACP) later | U3 |
| FR-E1 | Edit local agent config (skills/soul/tools/core) | U4 |
| FR-E2 | Remote config read-only (v1) | U4 |
| FR-E3 | Config edits take effect (reload/restart) | U4 (+ U2 exec) |
| FR-L1 | `agent logs` | U4 (+ U2 provisioner) |
| FR-L2 | Health checks (shallow/deep) | U2 |

## Acceptance criteria → units

| AC | Primary unit(s) |
|---|---|
| AC-1 daemon up + AI-Gateway listening | U4, U1 |
| AC-2 create → configured → ls healthy | U2 (+ U1) |
| AC-3 chat streams + resumes session | U3 |
| AC-4 upstream down → graceful, daemon stays up | U1, U3 (Supervisor) |
| AC-5 register remote → chat works uniformly | U2, U3 |
| AC-6 config edit verified in sandbox | U4 (+ U2) |
| AC-7 rm tears down sandbox | U2 |

## NFR / Resiliency → units
- NFR-1 usability → U4 · NFR-2 portability → U2 (image/sbx) · NFR-3 streaming perf → U1/U3 · NFR-4 observability → U4 `common/` · NFR-5 maintainability/tests → all · NFR-6 loopback security → U4/U1 · NFR-7 state → U2.
- RES-3 health → U2 · RES-4 timeouts/isolation → U1/U3 · RES-5 supervision → U3 · RES-7 state durability → U2.

**Coverage check**: every FR (G/P/A/C/E/L) and AC-1..AC-7 has an owning unit. ✅
