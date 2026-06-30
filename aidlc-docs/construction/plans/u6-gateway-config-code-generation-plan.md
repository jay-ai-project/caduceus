# U6 — `caduceus gateway config` · Code Generation Plan (single source of truth)

**Unit**: U6 Gateway Config · **Project**: Caduceus (brownfield, single Python package) ·
**Workspace root**: `/mnt/f/Workspace/Caduceus` · Code in `caduceus/`, tests in `tests/`.

**Approach**: brownfield — **modify existing files in place** (no `*_new.py` copies); add two new
modules. Each step lists files and the business rules / PBT targets it satisfies (traceability to
`construction/u6-gateway-config/functional-design/`).

---

## Step 1 — DTOs: `GatewayConfigView` + `GatewayConfigChange`
- [x] **Modify** `caduceus/common/dto.py`: add the two frozen dataclasses with `to_dict`/`from_dict`.
  - `GatewayConfigChange`: fields `upstream_base_url|None`, `default_model|None`; `is_empty()`; trims values.
  - `GatewayConfigView`: `upstream_base_url|None`, `default_model|None`, `upstream_configured`, `source`, `env_override:list[str]`.
- Covers: domain-entities.md; BR-GC1, BR-GC8.

## Step 2 — Validation + atomic, key-preserving store (new module)
- [x] **Create** `caduceus/config/gateway_config.py`:
  - `validate_url(url) -> None` (raise `ValueError`): non-empty, scheme in {http,https}, non-empty host; no network (Q5=A).
  - `validate_change(change) -> None`: non-empty (BR-GC1); per-field validation (BR-GC2/GC3).
  - `load_toml(path) -> dict` / `atomic_write_toml(path, data)`: temp file in same dir + `os.replace`, `chmod 600`, parent `700` (BR-GC4).
  - `apply_to_toml(path, change) -> None`: read-modify-write preserving unrelated keys (BR-GC4).
  - `env_override_keys() -> list[str]`: which of `CADUCEUS_UPSTREAM_BASE_URL`/`CADUCEUS_DEFAULT_MODEL` are set (BR-GC7).
  - `view_from_settings(settings, source, env_override) -> GatewayConfigView`.
- Covers: business-logic-model.md L2/L3; BR-GC2/3/4/7; PBT-GC1/GC2.

## Step 3 — `GatewayConfigService` (daemon-side apply + view)
- [x] **Create** `caduceus/config/service.py` addition **or** extend it: add `GatewayConfigService`
      holding the live `Settings`, the `config.toml` path, that does:
  - `view() -> GatewayConfigView` (source="live").
  - `apply(change) -> GatewayConfigView`: validate → `apply_to_toml` (persist) → mutate live `Settings`
    fields in place (hot-apply) → return view (BR-GC5/GC9). Order = persist then mutate.
  *(Implementation note: if `config/service.py` is agent-specific, place `GatewayConfigService` in
  `caduceus/config/gateway_config.py` instead to keep concerns separate — final location decided in generation.)*
- Covers: business-logic-model.md L4; BR-GC5, BR-GC9.

## Step 4 — Wire into Services + Control API routes
- [x] **Modify** `caduceus/daemon/wiring.py`: construct `GatewayConfigService(settings, config_path=sd/"config.toml")`
      and add `gateway_config_service` to the `Services` dataclass.
- [x] **Modify** `caduceus/daemon/control_api.py`: add
  - `GET /gateway/config` → `services.gateway_config_service.view().to_dict()`.
  - `POST /gateway/config` → parse `GatewayConfigChange`, `apply`, return view; `ValueError` → 400 (validation).
- Covers: business-logic-model.md (Control-API contract); BR-GC11.

## Step 5 — CLI client methods
- [x] **Modify** `caduceus/cli/client.py`: add `get_gateway_config() -> GatewayConfigView` and
      `set_gateway_config(change) -> GatewayConfigView` (map HTTP 400 → `ControlError(exit_code=2)`).
- Covers: business-logic-model.md L1/L2.

## Step 6 — CLI command `gateway config`
- [x] **Modify** `caduceus/cli/app.py`: add `@gateway_app.command("config")` with
      `--get`, `--json`, `--upstream-url`, `--model`.
  - No set flags → view. Daemon up → client; daemon down → local: view via `Settings.from_env_and_file`,
    set via `validate_change` + `apply_to_toml` (offline) reporting "restart pending" (BR-GC6).
  - Empty/invalid set → usage error exit 2 (BR-GC1/2/3); env-shadow warning (BR-GC7).
- Covers: business-logic-model.md L1/L2; BR-GC1/2/3/6/7/10.

## Step 7 — Render helper + exit codes
- [x] **Modify** `caduceus/cli/render.py`: add `render_gateway_config(view, json_out)` (human table or JSON),
      and a `changed`/applied-live vs restart-pending message (BR-GC10). Reuse `EXIT_USAGE`/`EXIT_RUNTIME`.
- Covers: BR-GC8 (no secrets), BR-GC10.

## Step 8 — Tests (unit + PBT)
- [x] **Create** `tests/unit/test_gateway_config.py`: validation (BR-GC2/3), atomic store round-trip +
      key preservation, DTO to_dict/from_dict, `GatewayConfigService.apply` (persist+hot-apply via a fake Settings),
      env-override detection.
- [x] **Create** `tests/unit/test_cli_gateway_config.py`: command via fake client (daemon up) and offline path
      (tmp config.toml), exit codes 0/2, env-shadow warning.
- [x] **Create/Modify** control-API test (e.g. `tests/unit/test_control_api_gateway_config.py`): GET/POST routes via
      fastapi `TestClient` with fake/real wired services; 400 on bad input.
- [x] **Create** `tests/pbt/test_gateway_config_pbt.py`: PBT-GC1 (validation totality/idempotence),
      PBT-GC2 (toml round-trip + unrelated-key preservation), PBT-GC3 (change idempotence).
- Covers: PBT-GC1/GC2/GC3; all BRs exercised.

## Step 9 — Documentation
- [x] **Modify** `README.md`: document `caduceus gateway config` under the CLI section
      (view + `--upstream-url`/`--model`, live-apply vs restart-pending).
- [x] **Create** `aidlc-docs/construction/u6-gateway-config/code/code-summary.md`: files created/modified + test counts.

## Step 10 — Local verification (pre-Build&Test sanity)
- [x] Run the existing venv test suite (`.venv`) to confirm new + existing tests pass (full live verification is Build & Test).
- [x] Mark all steps [x] and update `aidlc-state.md`.

---

### Traceability summary
- **BR-GC1** S1,S6,S8 · **BR-GC2/3** S2,S6,S8 · **BR-GC4** S2,S8 · **BR-GC5** S3,S4 · **BR-GC6** S6 ·
  **BR-GC7** S2,S6 · **BR-GC8** S1,S7 · **BR-GC9** S3 · **BR-GC10** S6,S7 · **BR-GC11** S4.
- **PBT-GC1** S8 · **PBT-GC2** S2,S8 · **PBT-GC3** S8.

**Total steps**: 10. Scope: 2 new modules + 6 modified files + 4 test files + README/code-summary.
