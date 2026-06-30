# Unit Test Execution

Covers the per-unit `pytest` suites generated during Code Generation: deterministic
unit tests (`tests/unit/`) and property-based tests (`tests/pbt/`, Hypothesis).
Pure in-process — **no Docker, sbx, hermes, or upstream LLM required**.

## Run Unit Tests

### 1. Execute All Tests (unit + PBT)
```bash
. .venv/bin/activate
pytest                       # config in pyproject.toml: asyncio_mode=auto, testpaths=tests
```

### 2. Execute by suite
```bash
pytest tests/unit            # deterministic unit tests
pytest tests/pbt             # property-based (Hypothesis) tests
```

### 3. Property-based test reproducibility (RESILIENCY-04 / PBT-08)
```bash
HYPOTHESIS_PROFILE=ci pytest tests/pbt   # print_blob=True → logs @reproduce_failure seeds
```
On a failure, copy the printed `@reproduce_failure(...)` decorator onto the property to replay the exact counterexample. The `ci` profile is what GitHub Actions uses.

### 4. Review Test Results
- **Expected**: **132 passed, 0 failures** (`109` unit + `23` PBT).
- **Per-suite expectation**:

  | Suite | Tests | Notes |
  |---|---|---|
  | `tests/unit` | 109 | U1 + U2 + U3 + U4 unit tests |
  | `tests/pbt` | 23 | aigateway 6 · registry 4 (stateful) · transport 4 (incl. stateful Supervisor) · u4 9 |
  | **Total** | **132** | |

- **Coverage stance**: by design, the real protocol/IO seams are **excluded** from unit tests and exercised in integration instead:
  - `caduceus/transport/serve.py` `_WIRE_*` (real hermes-serve JSON-RPC/WS framing)
  - `caduceus/daemon/gateway.py` daemon serve/fork path
  - `caduceus/cli/client.py` real `ControlAPIClient` HTTP calls
  - sandbox config codec / real `sbx` provisioning
  These import cleanly (build import-sanity check) and are validated under integration tests.

### 5. Fix Failing Tests
If tests fail:
1. Review pytest output (failing node id + assertion / Hypothesis falsifying example).
2. For PBT failures, replay with the printed `@reproduce_failure` seed.
3. Fix the code, re-run the affected suite, then the full `pytest` before proceeding.
