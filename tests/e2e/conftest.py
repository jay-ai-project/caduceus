"""E2E harness: serve the real Control API (with fake services) in-process, so
Playwright can drive the actual Web UI (static SPA + `/status` + `/agents`).

The app under test is exactly the one shipped by `build_control_app` — only the
*service* layer is faked (no Docker/sbx/hermes/LLM), so the HTML/CSS/JS, the
`/ui` mount and the `/` → `/ui/` redirect are all real.

We use Playwright's **async** API (not the sync `pytest-playwright` fixtures):
this repo runs pytest-asyncio in ``asyncio_mode = "auto"``, and the sync
Playwright fixtures drive their own greenlet loop that clashes with it. The
async API shares the pytest-asyncio event loop, so browser and non-browser
tests coexist in one session.
"""

from __future__ import annotations

import socket
import threading
import time

import httpx
import pytest
import pytest_asyncio
import uvicorn
from playwright.async_api import async_playwright

from caduceus.daemon.control_api import build_control_app

from tests.fakes import build_fake_services, make_agent


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def webui_server():
    """Start the Control API app on a loopback port for the whole e2e session.

    Yields the base URL (e.g. ``http://127.0.0.1:54321``). Uses fake services
    seeded with one local agent so the dashboard has something to render.
    """
    demo = make_agent(name="demo-agent")
    demo.dashboard_port = 59119            # U11: card shows Dashboard link + Creds
    demo.dashboard_password = "e2e-pw"
    plain = make_agent(name="plain-agent")  # no dashboard → no link
    services = build_fake_services(agents=[demo, plain])
    app = build_control_app(services)

    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"
    # Wait until the server is accepting requests (healthz) before handing off.
    deadline = time.time() + 10
    while time.time() < deadline:
        if server.started:
            try:
                if httpx.get(f"{base_url}/healthz", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
        time.sleep(0.05)
    else:  # pragma: no cover - only on a startup failure
        raise RuntimeError("Control API test server did not start in time")

    yield base_url

    server.should_exit = True
    thread.join(timeout=5)


@pytest_asyncio.fixture
async def page():
    """A fresh headless Chromium page per test (async Playwright)."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        context = await browser.new_context(viewport={"width": 1280, "height": 800})
        pg = await context.new_page()
        try:
            yield pg
        finally:
            await context.close()
            await browser.close()
