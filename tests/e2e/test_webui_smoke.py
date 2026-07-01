"""Browser E2E smoke test for the Caduceus Web UI.

Drives the real SPA in a headless Chromium via Playwright (async API) and
asserts the core render + one interaction path work end to end:

  1. `/` redirects to `/ui/` and the shell loads.
  2. The gateway status header reflects the live `/status` response.
  3. The seeded agent is listed from `/agents`.
  4. The "Add agent" modal opens and its tabs toggle.

Run with:  pytest tests/e2e
"""

from __future__ import annotations

import pytest
from playwright.async_api import Page, expect

pytestmark = pytest.mark.e2e


async def test_root_redirects_to_ui_and_shell_loads(webui_server: str, page: Page):
    await page.goto(webui_server + "/")
    # `/` → `/ui/` redirect is served by the app, so the landing URL is /ui/.
    await expect(page).to_have_url(webui_server + "/ui/")
    await expect(page).to_have_title("Caduceus")
    await expect(page.get_by_text("⚕ Caduceus")).to_be_visible()


async def test_gateway_status_and_agent_list_render(webui_server: str, page: Page):
    await page.goto(webui_server + "/ui/")

    # Header polls /status and paints "running · N agents · …".
    status = page.get_by_test_id("gateway-status")
    await expect(status).to_contain_text("running", timeout=5000)
    await expect(status).to_contain_text("agents")

    # The seeded agent from /agents shows up in the sidebar.
    await expect(page.get_by_test_id("agent-list")).to_contain_text("demo-agent", timeout=5000)


async def test_add_agent_modal_opens_and_tabs_toggle(webui_server: str, page: Page):
    await page.goto(webui_server + "/ui/")

    modal = page.get_by_test_id("add-agent-modal")
    await expect(modal).to_be_hidden()

    await page.get_by_test_id("add-agent-button").click()
    await expect(modal).to_be_visible()

    # Defaults to the "Local sandbox" tab/form.
    await expect(page.get_by_test_id("form-local")).to_be_visible()
    await expect(page.get_by_test_id("form-remote")).to_be_hidden()

    # Switching to "Remote" swaps the visible form.
    await page.get_by_test_id("tab-remote").click()
    await expect(page.get_by_test_id("form-remote")).to_be_visible()
    await expect(page.get_by_test_id("form-local")).to_be_hidden()

    # Close returns to the hidden state.
    await page.get_by_test_id("modal-close").click()
    await expect(modal).to_be_hidden()
