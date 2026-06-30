# U6 — Business Rules (Functional Design, light)

| ID | Rule |
|---|---|
| **BR-GC1** | A set requires ≥1 of `--upstream-url` / `--model`. Empty change → usage error, exit 2, nothing written or applied. |
| **BR-GC2** | `upstream_base_url` must be non-empty (after trim) and a syntactically valid URL: a scheme in {`http`, `https`} **and** a non-empty host. Invalid → usage error (exit 2 in CLI / HTTP 400 in daemon), nothing written/applied. No network call is made (Q5=A). |
| **BR-GC3** | `default_model` must be non-empty after trim. Invalid → usage error (exit 2 / 400), nothing written. |
| **BR-GC4** | Persisting is **atomic and key-preserving**: read-modify-write `config.toml` via temp file + `os.replace`; file perms `600`, parent dir `700`; keys other than the two edited are left intact. A crash mid-write cannot leave a partial/corrupt file (Resiliency, NFR-1). |
| **BR-GC5** | When the daemon is running, a successful set **hot-applies** by mutating the live `Settings` object the gateway reads from — no restart. Subsequent agent LLM calls use the new upstream URL / `default` model resolution. |
| **BR-GC6** | When the daemon is not running, a successful set edits `config.toml` only; it takes effect on the next `gateway start`. The command reports this explicitly. |
| **BR-GC7** | If a relevant env var (`CADUCEUS_UPSTREAM_BASE_URL` / `CADUCEUS_DEFAULT_MODEL`) is set, it overrides `config.toml` at load time. On any set/get that touches such a key, the command **warns** that the env var shadows the persisted value on (re)start, so the change may appear ineffective after restart. |
| **BR-GC8** | `--get` / the view never emits secrets. `upstream_auth` and all non-scoped settings are excluded from `GatewayConfigView`. |
| **BR-GC9** | Apply order for a set is **validate → persist (durable) → hot-apply (in-memory)**. If persist fails, no in-memory mutation occurs and an error is reported (consistent state: neither persisted nor applied). |
| **BR-GC10** | On success: report which keys changed and their new values, and whether the change was **applied live** (daemon up) or **persisted, restart pending** (daemon down). Exit 0. Human-readable by default; `--json` emits the `GatewayConfigView`. |
| **BR-GC11** | The new Control-API routes stay on the existing loopback Control API (`127.0.0.1`); no new listener, port, or auth surface (Security extension off; NFR-3). |

## Extension compliance (this stage)
- **Resiliency (full)**: BR-GC4 (atomic write) + BR-GC9 (consistent partial-failure state) satisfy state-durability/graceful-degradation rules. Health-probe/supervision rules N/A (no new process).
- **Property-Based Testing (full)**: PBT-GC1..GC3 (see business-logic-model.md) cover validation totality, config round-trip/key-preservation, and idempotence. Stateful PBT N/A (no new long-lived state machine).
- **Security (off)**: not enforced; BR-GC8/BR-GC11 nonetheless avoid secret exposure and new surface.
