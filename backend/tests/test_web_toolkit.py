from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.browser import BrowserController
from app.core.toolkits.web import WebToolkit


def make_ctx(kernel, session_id: str = "test-session"):
    return SimpleNamespace(deps=SimpleNamespace(kernel=kernel, session_id=session_id))


class FakeBrowser:
    def __init__(self):
        self.calls: list[tuple] = []

    async def scroll(self, direction="down", selector=None):
        self.calls.append(("scroll", direction, selector))
        return "scroll-ok"

    async def get_console_messages(self, clear=False):
        self.calls.append(("console", clear))
        return "console-ok"

    async def wait(self, timeout_ms=2000, selector=None):
        self.calls.append(("wait", timeout_ms, selector))
        return "wait-ok"


class FakeKernel:
    def __init__(self, browser=None, workspace: Path | None = None):
        self.browser = browser or FakeBrowser()
        self.workspace = workspace or Path("/tmp/ferryman-test")
        self.calls: list[tuple] = []

    async def get_browser(self, session_id: str, headless=None):
        self.calls.append(("get_browser", session_id, headless))
        return self.browser

    def get_session_workspace(self, session_id: str) -> Path:
        return self.workspace


@pytest.mark.asyncio
async def test_browser_scroll_forwards_direction_and_selector():
    kernel = FakeKernel()

    result = await WebToolkit.browser_scroll(make_ctx(kernel), direction="up", selector="[3]")

    assert result == "scroll-ok"
    assert kernel.calls == [("get_browser", "test-session", None)]
    assert kernel.browser.calls == [("scroll", "up", "[3]")]


@pytest.mark.asyncio
async def test_browser_console_forwards_clear_flag():
    kernel = FakeKernel()

    result = await WebToolkit.browser_console(make_ctx(kernel), clear=True)

    assert result == "console-ok"
    assert kernel.calls == [("get_browser", "test-session", None)]
    assert kernel.browser.calls == [("console", True)]


@pytest.mark.asyncio
async def test_browser_wait_forwards_selector_and_timeout():
    kernel = FakeKernel()

    result = await WebToolkit.browser_wait(make_ctx(kernel), timeout_ms=1234, selector="#ready")

    assert result == "wait-ok"
    assert kernel.calls == [("get_browser", "test-session", None)]
    assert kernel.browser.calls == [("wait", 1234, "#ready")]


@pytest.mark.asyncio
async def test_web_toolkit_browser_e2e(tmp_path):
    browser_status = BrowserController.get_runtime_status()
    if not browser_status["available"]:
        pytest.skip("System Chrome unavailable for browser e2e test.")

    page_path = tmp_path / "browser-e2e.html"
    page_path.write_text(
        """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>Ferryman Browser E2E</title>
  <style>
    body { font-family: sans-serif; margin: 0; }
    main { padding: 24px; }
    .spacer { height: 2200px; background: linear-gradient(#fff, #ddd); }
  </style>
</head>
<body>
  <main>
    <h1>Ferryman Browser E2E</h1>
    <label for="name">Name</label>
    <input id="name" placeholder="Type here" />
    <button id="save">Save</button>
    <div id="status">Idle</div>
    <div class="spacer"></div>
    <div id="footer-marker">Bottom marker</div>
  </main>
  <script>
    console.error("boot error from page");
    setTimeout(() => {
      const ready = document.createElement("div");
      ready.id = "late-ready";
      ready.textContent = "Late ready";
      document.body.appendChild(ready);
    }, 150);
    document.getElementById("save").addEventListener("click", () => {
      document.getElementById("status").textContent =
        "Saved: " + document.getElementById("name").value;
      console.log("save-clicked");
    });
  </script>
</body>
</html>
""",
        encoding="utf-8",
    )

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    browser = BrowserController(headless=True, user_data_dir=str(workspace / ".browser"))
    await browser.__aenter__()
    kernel = FakeKernel(browser=browser, workspace=workspace)
    ctx = make_ctx(kernel, session_id="browser-e2e")

    try:
        navigate_result = await WebToolkit.browser_navigate(ctx, page_path.as_uri())
        assert "Successfully navigated to" in navigate_result
        assert "Title: Ferryman Browser E2E" in navigate_result
        assert "[Browser content: untrusted]" in navigate_result
        assert "textbox" in navigate_result
        assert "button" in navigate_result

        wait_result = await WebToolkit.browser_wait(ctx, timeout_ms=2000, selector="#late-ready")
        assert wait_result == "Selector '#late-ready' appeared."

        scroll_result = await WebToolkit.browser_scroll(ctx, direction="down")
        assert scroll_result == "Successfully scrolled down"
        scroll_y = await browser._page.evaluate("window.scrollY")
        assert scroll_y > 0

        console_result = await WebToolkit.browser_console(ctx)
        assert "[Browser content: untrusted]" in console_result
        assert "boot error from page" in console_result

        empty_console_result = await WebToolkit.browser_console(ctx, clear=True)
        assert "boot error from page" in empty_console_result
        cleared_console_result = await WebToolkit.browser_console(ctx)
        assert "No browser console messages captured." in cleared_console_result
    finally:
        await browser.__aexit__(None, None, None)
