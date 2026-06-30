# U6 — Code Generation Summary

`caduceus gateway config` to view/change `upstream_base_url` + `default_model`, with live
hot-apply (daemon up) or direct atomic `config.toml` edit (daemon down).

## Created
- `caduceus/config/gateway_config.py` — validation (light, no network), atomic key-preserving
  `config.toml` read-modify-write (temp + `os.replace`, perms 600), `view_from_settings`,
  `env_override_keys`, and `GatewayConfigService` (persist-then-hot-apply).
- `tests/unit/test_gateway_config.py` — validation, store round-trip + key preservation, DTOs,
  service apply (persist + live mutation), env-override detection.
- `tests/unit/test_cli_gateway_config.py` — CLI view/set, daemon up + offline paths, exit codes, env warning.
- `tests/unit/test_control_api_gateway_config.py` — `GET`/`POST /gateway/config`, 200 apply+persist, 400 validation/empty.
- `tests/pbt/test_gateway_config_pbt.py` — PBT-GC1 (validation totality/idempotence), PBT-GC2
  (round-trip preserves unrelated keys), PBT-GC3 (apply idempotence).

## Modified
- `caduceus/common/dto.py` — `GatewayConfigChange` + `GatewayConfigView` (to_dict/from_dict).
- `caduceus/daemon/wiring.py` — build `GatewayConfigService(settings, ~/.caduceus/config.toml)`;
  add `gateway_config_service` to `Services` (shares the live `settings` the AI-Gateway reads → BR-GC5).
- `caduceus/daemon/control_api.py` — additive routes `GET /gateway/config`, `POST /gateway/config`
  (ValueError → HTTP 400).
- `caduceus/cli/client.py` — `get_gateway_config` / `set_gateway_config` (HTTP 400 → `ControlError` exit 2).
- `caduceus/cli/app.py` — `gateway config` command (`--get`/`--json`/`--upstream-url`/`--model`),
  daemon-up via client, daemon-down via local atomic file edit.
- `caduceus/cli/render.py` — `render_gateway_config` + `render_gateway_config_applied` + env-shadow warnings.
- `tests/fakes.py` — `build_fake_services` default `gateway_config_service`; `FakeControlAPIClient`
  `get_gateway_config`/`set_gateway_config`.
- `README.md` — document `gateway config` (CLI table + Configuration section).

## Verification
- Full suite: **208 passed** (was 174; +34: 18 unit gateway_config, 7 CLI, 4 control-api, 5 PBT — counts approximate by file).
- Hot-apply mechanism unit-verified (live `Settings` mutation observed); real running-daemon HTTP path → Build & Test.

## Business-rule traceability
BR-GC1 (empty→usage), GC2/GC3 (validation), GC4 (atomic key-preserving write), GC5 (live mutation of
shared Settings), GC6 (offline → restart pending), GC7 (env-shadow warning), GC8 (no secrets in view),
GC9 (persist-then-apply order; invalid → nothing written), GC10 (applied-live vs restart-pending report),
GC11 (loopback only, no new surface). PBT-GC1/GC2/GC3 covered.
