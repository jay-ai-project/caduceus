# U6 — Business Logic Model (Functional Design, light)

Technology-agnostic flows for `caduceus gateway config`. Concrete seams named for clarity.

## L1 — View (`gateway config --get` / no set flags)
1. If the daemon is **running** (`/healthz` ok): fetch `GET /gateway/config` → `GatewayConfigView`
   with `source="live"` (the daemon reports its in-memory `Settings`, i.e. the values actually
   serving traffic).
2. If the daemon is **down**: build `Settings.from_env_and_file(config.toml)` locally and project a
   `GatewayConfigView` with `source="file"`. Populate `env_override` from which `CADUCEUS_*` vars are set.
3. Render human-readable (key: value, "(not set)" when `None`) or `--json`.

## L2 — Set (`--upstream-url` and/or `--model`)
1. **Build change** from flags → `GatewayConfigChange`. If empty → usage error (BR-GC1, exit 2).
2. **Validate** (light, BR-GC2/GC3) client-side first → on failure, usage error (exit 2), nothing written.
3. **Apply**, branching on daemon state:
   - **Daemon running** → `POST /gateway/config` with the change. The daemon handler:
     a. re-validates defensively (→ 400 on bad input),
     b. **persists** atomically to `config.toml` (BR-GC4),
     c. **hot-applies**: mutates `Services.settings.upstream_base_url` / `.default_model` in place
        (BR-GC5) — `UpstreamClient._url()` and `routing.build_route()` read these live, so the next
        request uses the new values without restart,
     d. returns the updated `GatewayConfigView` (`source="live"`).
   - **Daemon down** → the CLI itself performs the persist step (b) locally (offline path, Q4=A):
     read-modify-write `config.toml` atomically, then report `source="file"`, "applied on next start".
4. **Report** (BR-GC10): list changed keys + new values; state whether applied **live** or
   **persisted (restart pending)**; if a relevant env var is set, warn it shadows the file on reload
   (BR-GC7). Exit 0.

## L3 — Atomic, key-preserving persist (shared by daemon route + CLI offline path)
`GatewayConfigStore.update(path, change)`:
1. Load existing TOML into a dict (empty if file absent).
2. Set `upstream_base_url` / `default_model` for provided fields (leave all other keys untouched —
   preserves `control_bind`, `aigateway_bind`, `[timeouts]`, etc.).
3. Serialize and write via **temp file in the same dir + `os.replace`** (atomic), `chmod 600`,
   parent dir `700` (BR-GC4). This supersedes `Settings.write_config_toml` for partial edits
   (which rewrites only known keys); the store does a true read-modify-write.

## L4 — Live-apply seam
- The daemon route closes over `Services.settings` (the exact object injected into `UpstreamClient`
  and used by `routing.build_route`). Hot-apply = attribute assignment on that object; no rebuild of
  the AI-Gateway app, no port rebind, no restart.
- **In-flight requests**: each forward already resolved its `base_url`/model at call time, so they
  are unaffected; only requests started after the mutation see new values (acceptable; documented).

## Control-API contract (additive)
- `GET /gateway/config` → `GatewayConfigView.to_dict()`.
- `POST /gateway/config` body `{ "upstream_base_url"?, "default_model"? }` → validate → persist →
  hot-apply → `GatewayConfigView.to_dict()`; `400` on validation error.

## CLI surface
`caduceus gateway config [--get] [--json] [--upstream-url URL] [--model NAME]`
- No flags → behaves as `--get` (show current).
- `--upstream-url` / `--model` (≥1) → set. Both view and set work daemon-up or daemon-down.

## PBT targets (extension: PBT full)
- **PBT-GC1**: URL validation is total & deterministic; `validate(x)` stable under idempotent re-check.
- **PBT-GC2**: `config.toml` round-trip — after `update`, reload yields the written
  `upstream_base_url`/`default_model`, **and** any unrelated pre-existing keys are preserved.
- **PBT-GC3**: change application is idempotent — applying the same `GatewayConfigChange` twice equals once.
