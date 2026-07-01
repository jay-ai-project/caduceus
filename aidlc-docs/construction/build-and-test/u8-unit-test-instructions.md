# U8 Unit + Property Test Execution

Runs **without Docker** (fakes + `httpx.MockTransport`).

```bash
. .venv/bin/activate
python -m pytest tests/unit tests/pbt -q      # unit + Hypothesis (PBT)
```
- **Expected**: 241 passed (211 prior + 30 U8).
- Browser E2E (`tests/e2e`, Playwright) run separately in the runner; not part of this gate.

## Key U8 coverage
- `test_hermes_api_transport.py` — SSE→ChatEvent mapping, session/health/history, run stop.
- `test_doctor.py` — docker/runtime/gVisor checks + install guidance.
- `test_u8_properties.py` — PBT-U8-1 mapping totality+terminal, -2 runtime validation, -3
  provisioner state machine, -4 real-time list determinism, -5 cancel single-terminal.
- Migrated: models/names/agent_service/gateway_config/control_api/cli + fakes.
