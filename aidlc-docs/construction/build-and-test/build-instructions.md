# Build Instructions

Caduceus is a single Python package (local-first tool, no cloud build). "Build" =
create a virtualenv, install the package (editable for dev, or a wheel for
distribution), and verify the console entry point resolves.

## Prerequisites
- **Build Tool**: Python `>=3.11` with `pip`; backend = `hatchling` (PEP 517, declared in `pyproject.toml`). Verified on CPython 3.12.3.
- **Dependencies** (runtime, resolved by pip from `pyproject.toml`):
  `fastapi>=0.110`, `uvicorn[standard]>=0.29`, `httpx>=0.27`, `pydantic>=2`,
  `websockets>=12`, `typer>=0.12`.
- **Dev dependencies** (`.[dev]` extra): `pytest>=8`, `pytest-asyncio>=0.23`, `anyio>=4`, `hypothesis>=6`.
- **Environment Variables** (build/test time): none required.
  Runtime config (`upstream_base_url`, `default_model`) is **not** needed to build or to run unit/PBT tests.
- **System Requirements**: Linux/macOS/WSL2; ~200 MB disk for the venv. Docker/sbx/hermes are runtime (integration) dependencies only — **not** needed to build or unit-test.

## Build Steps

### 1. Create venv & install dependencies
```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"        # editable install + dev tools
```

### 2. Configure Environment
```bash
# No environment variables are required to build or run unit/PBT tests.
# (Runtime only) export CADUCEUS_UPSTREAM_BASE_URL / CADUCEUS_DEFAULT_MODEL before
# starting the daemon — see shared-infrastructure.md "Configuration keys".
```

### 3. Build the distributable wheel (optional — for pipx/install)
```bash
pip install build
python -m build --wheel        # produces dist/caduceus-0.1.0-py3-none-any.whl
```

### 4. Verify Build Success
- **Expected Output**: `Successfully built caduceus` (editable) / `Successfully built caduceus-0.1.0-py3-none-any.whl` (wheel).
- **Build Artifacts**:
  - editable install registered as `caduceus 0.1.0`
  - console script `caduceus` on PATH (`caduceus --help` shows `agent` + `gateway` command groups)
  - wheel at `dist/caduceus-0.1.0-py3-none-any.whl` (gitignored)
- **Import sanity** (all 43 modules, incl. protocol/daemon/client modules that are unit-untested by design):
  ```bash
  python -c "import pkgutil, importlib, caduceus; \
[importlib.import_module(m.name) for m in pkgutil.walk_packages(caduceus.__path__, 'caduceus.')]; \
print('import OK')"
  ```
- **Common Warnings**: none expected.

## Troubleshooting

### Build Fails with Dependency Errors
- **Cause**: offline / incompatible Python (`<3.11`).
- **Solution**: confirm `python --version` >= 3.11; ensure network access to PyPI; re-run `pip install -e ".[dev]"`.

### `caduceus: command not found` after install
- **Cause**: venv not activated, or install was non-editable into a different prefix.
- **Solution**: activate `.venv` (`. .venv/bin/activate`) or invoke via `python -m caduceus`.

### Build Fails with Backend (hatchling) Errors
- **Cause**: stale build environment.
- **Solution**: `pip install -U build hatchling` and rebuild; remove `dist/` and `*.egg-info/` and retry.
