# U2 Registry & Provisioner — Business Rules

| ID | Rule | Source |
|---|---|---|
| **BR-A1 Name validation** | Agent name: non-empty; allowed chars `[A-Za-z0-9._+-]` (sbx-compatible); bounded length; trimmed. Invalid → `invalid_request` error with reason. | FR-A6, sbx naming |
| **BR-A2 Sandbox naming** | Local sandbox name = `cad-<name>` (Q1=A). `ls` filters caduceus-managed sandboxes by the `cad-` prefix. | Q1=A |
| **BR-A3 Uniqueness** | `name` unique in the registry; `create`/`register` on an existing name → error (no silent replace in v1). | FR-A6 |
| **BR-A4 Token minting** | Per-agent token = `secrets.token_urlsafe(32)`; unique; stored with file perms 600; **never logged** (redaction). | NFR-6 |
| **BR-A5 Provider config (local)** | A local agent's hermes is configured: provider `base_url = AI-Gateway advertise URL`, `api_key = token`, `model = "default"`. This is invariant for all local agents (the LLM always routes through caduceus). | FR-P2, Q2(U1) |
| **BR-A6 Remote routing guidance** | `register` mints a token and returns the AI-Gateway URL + token + `model=default` for the user to configure on the remote hermes (caduceus cannot auto-configure remote in v1). | Q2=A |
| **BR-A7 Create rollback** | Any failure after sandbox creation → best-effort teardown (`sbx rm`) + discard token; the agent is NOT left half-registered. Daemon stays up; clear error returned. | RESILIENCY-10 |
| **BR-A8 Atomic persistence** | Every registry mutation is persisted via atomic write (temp + `os.replace`); access serialized by an in-process lock. | App Design Q2, RESILIENCY-12 |
| **BR-A9 Lifecycle transitions** | Allowed: creating→running\|failed; running→stopped\|unhealthy; stopped→running; any→removed. `start` on running and `stop` on stopped are idempotent no-ops. | FR-A5 |
| **BR-A10 Remote lifecycle ops** | A remote agent's process lifecycle is **not caduceus-managed**, so `stop`/`start` on a remote agent is **currently not possible** — caduceus returns a clear "not supported for remote agents" message (it never attempts to start/stop a remote process). `remove` on remote = de-register only (no sandbox teardown). *(User-confirmed v1 limitation.)* | FR-A5/A4 |
| **BR-A11 Health semantics** | shallow = endpoint/sandbox reachable; deep = + hermes responsive + caduceus upstream reachable; **deep never spends an LLM completion**. Health cached with timestamp. | FR-L2, RESILIENCY-06 |
| **BR-A12 sbx/docker call discipline** | All Provisioner subprocess calls have explicit timeouts; non-zero exits map to actionable errors; partial failures are surfaced, not swallowed. | RESILIENCY-10 |

## Validation details
- Reserved/normalization: reject a name that, after prefixing, would collide with an existing `cad-*` sandbox not owned by caduceus → error advising a different name.
- `register` endpoint must be a syntactically valid URL; reachability probe failure → error (do not persist).

## Resiliency / PBT linkage
- BR-A7/BR-A12 → RESILIENCY-10 (timeouts, graceful, no daemon crash).
- BR-A8 → RESILIENCY-12 (durable state).
- BR-A1/A2/A4/A5/A9 → PBT properties P-U2-1..6 (incl. stateful registry PBT-06).
