from pathlib import Path

import pytest
from pydantic_ai.exceptions import ModelRetry
from playwright.async_api import Error as PlaywrightError

from app.core.browser import BrowserController, CHROME_REQUIRED_MESSAGE


def test_browser_launch_plans_do_not_fallback_to_bundled_chromium(monkeypatch):
    monkeypatch.setattr(Path, "exists", lambda self: False)
    monkeypatch.setattr("app.core.browser.shutil.which", lambda name: None)

    controller = BrowserController()

    assert controller._build_launch_plans() == []


@pytest.mark.asyncio
async def test_browser_enter_shows_install_guidance_when_chrome_missing(monkeypatch):
    async def fake_start():
        return object()

    monkeypatch.setattr(Path, "exists", lambda self: False)
    monkeypatch.setattr("app.core.browser.shutil.which", lambda name: None)
    monkeypatch.setattr("app.core.browser.async_playwright", lambda: type(
        "FakePlaywrightFactory",
        (),
        {"start": staticmethod(fake_start)},
    )())

    controller = BrowserController()

    with pytest.raises(RuntimeError, match="Chrome runtime is unavailable"):
        await controller.__aenter__()

    assert "https://www.google.com/chrome/" in CHROME_REQUIRED_MESSAGE


@pytest.mark.asyncio
async def test_browser_click_raises_model_retry_when_interaction_fails():
    class FakePage:
        async def wait_for_selector(self, selector, state="visible", timeout=10000):
            return None

        async def click(self, selector, timeout=5000, force=False):
            raise PlaywrightError("boom")

    controller = BrowserController()
    controller._page = FakePage()

    with pytest.raises(ModelRetry, match="Failed to click 'button.submit': boom"):
        await controller.click("button.submit")
