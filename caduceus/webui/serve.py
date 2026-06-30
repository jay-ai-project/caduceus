"""Mount the static Web UI on the Control API app (FR-W1, BR-W1..W4).

The UI is a self-contained, no-build SPA shipped as package data under
`assets/`. It is mounted at `/ui` (StaticFiles, html=True → serves `index.html`),
and `GET /` redirects to `/ui/`. Because it lives under `/ui`, it never shadows
the API routes (`/status`, `/agents…`, `/healthz`). Served only on the loopback
Control API listener — never on the AI-Gateway listener (BR-W1).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

ASSETS_DIR = Path(__file__).parent / "assets"


def mount_webui(app: FastAPI) -> None:
    """Mount the SPA + add the `/` → `/ui/` redirect (idempotent-safe per app)."""
    if ASSETS_DIR.is_dir():
        app.mount("/ui", StaticFiles(directory=str(ASSETS_DIR), html=True), name="webui")

    @app.get("/", include_in_schema=False)
    async def _root() -> RedirectResponse:
        return RedirectResponse(url="/ui/")
