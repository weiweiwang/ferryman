from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.browser import BrowserActionError
from app.core.browser import BrowserController
from app.core.tool_errors import RetryableToolError
from app.core.toolkits.web import WebToolkit


def make_ctx(browser_manager, session_id: str = "test-session"):
    return SimpleNamespace(
        deps=SimpleNamespace(
            browser_manager=browser_manager,
            workspace_dir=browser_manager.workspace,
            session_id=session_id,
        )
    )


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


class FailingBrowser(FakeBrowser):
    async def scroll(self, direction="down", selector=None):
        raise BrowserActionError("Failed to scroll: boom")


class FakeBrowserManager:
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
    browser_manager = FakeBrowserManager()

    result = await WebToolkit.browser_scroll(make_ctx(browser_manager), direction="up", selector="[3]")

    assert result == "scroll-ok"
    assert browser_manager.calls == [("get_browser", "test-session", None)]
    assert browser_manager.browser.calls == [("scroll", "up", "[3]")]


@pytest.mark.asyncio
async def test_browser_toolkit_uses_browser_manager_when_provided():
    browser_manager = FakeBrowserManager()

    result = await WebToolkit.browser_scroll(
        make_ctx(browser_manager),
        direction="up",
        selector="[3]",
    )

    assert result == "scroll-ok"
    assert browser_manager.calls == [("get_browser", "test-session", None)]


@pytest.mark.asyncio
async def test_browser_console_forwards_clear_flag():
    browser_manager = FakeBrowserManager()

    result = await WebToolkit.browser_console(make_ctx(browser_manager), clear=True)

    assert result == "console-ok"
    assert browser_manager.calls == [("get_browser", "test-session", None)]
    assert browser_manager.browser.calls == [("console", True)]


@pytest.mark.asyncio
async def test_browser_wait_forwards_selector_and_timeout():
    browser_manager = FakeBrowserManager()

    result = await WebToolkit.browser_wait(make_ctx(browser_manager), timeout_ms=1234, selector="#ready")

    assert result == "wait-ok"
    assert browser_manager.calls == [("get_browser", "test-session", None)]
    assert browser_manager.browser.calls == [("wait", 1234, "#ready")]


@pytest.mark.asyncio
async def test_web_toolkit_converts_browser_action_error_to_retryable_tool_error():
    browser_manager = FakeBrowserManager(browser=FailingBrowser())

    with pytest.raises(RetryableToolError) as exc_info:
        await WebToolkit.browser_scroll(make_ctx(browser_manager), direction="down")

    assert str(exc_info.value) == "Failed to scroll: boom"
    assert exc_info.value.error_type == "browser_action_error"


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
    browser_manager = FakeBrowserManager(browser=browser, workspace=workspace)
    ctx = make_ctx(browser_manager, session_id="browser-e2e")

    try:
        navigate_result = await WebToolkit.browser_navigate(ctx, page_path.as_uri(), include_snapshot=True)
        assert navigate_result["status"] == 200
        assert navigate_result["title"] == "Ferryman Browser E2E"
        assert navigate_result["resource_type"] == "html"
        assert navigate_result["meta"]["title"] == "Ferryman Browser E2E"
        assert navigate_result["snapshot_included"] is True
        assert "[Browser content: untrusted]" in navigate_result["interactive_snapshot"]
        assert "textbox" in navigate_result["interactive_snapshot"]
        assert "button" in navigate_result["interactive_snapshot"]

        wait_result = await WebToolkit.browser_wait(ctx, timeout_ms=2000, selector="#late-ready")
        assert wait_result == "Selector '#late-ready' appeared."

        scroll_result = await WebToolkit.browser_scroll(ctx, direction="down")
        assert scroll_result == "Successfully scrolled down"
        scroll_y = await browser._page.evaluate("window.scrollY")
        assert scroll_y > 0

        console_result = await WebToolkit.browser_console(ctx)
        assert "[Browser content: untrusted]" in console_result
        assert "boot error from page" in console_result

        screenshot_result = await WebToolkit.browser_screenshot(ctx, max_image_side=512)
        assert screenshot_result.media_type == "image/jpeg"
        assert getattr(screenshot_result, "data", b"").startswith(b"\xff\xd8")

        empty_console_result = await WebToolkit.browser_console(ctx, clear=True)
        assert "boot error from page" in empty_console_result
        cleared_console_result = await WebToolkit.browser_console(ctx)
        assert "No browser console messages captured." in cleared_console_result
    finally:
        await browser.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_browser_navigate_returns_bounded_page_summary(tmp_path):
    page_path = tmp_path / "directory.html"
    page_path.write_text(
        """
<!doctype html>
<html>
<head>
  <title>AI Product Directory</title>
  <meta name="description" content="Fresh AI products with funding and growth signals.">
  <link rel="canonical" href="https://example.test/directory">
</head>
<body>
  <header><a href="/login">Login</a></header>
  <main>
    <h1>Trending AI Products</h1>
    <section class="product-card">
      <h2>Rillet</h2>
      <a href="https://rillet.com">View Rillet</a>
      <p>AI-native accounting platform with Sequoia funding and mid-market finance teams.</p>
    </section>
    <section class="product-card">
      <h2>Decagon</h2>
      <a href="https://decagon.ai">View Decagon</a>
      <p>Enterprise AI support agent with named customers and fast growth.</p>
    </section>
    <section class="product-card">
      <h2>Bland AI</h2>
      <a href="https://bland.ai">View Bland AI</a>
      <p>Voice AI platform for automated phone calls, pricing, and enterprise deployment.</p>
    </section>
  </main>
</body>
</html>
""",
        encoding="utf-8",
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    browser = BrowserController(headless=True, user_data_dir=str(workspace / ".browser"))
    await browser.__aenter__()
    browser_manager = FakeBrowserManager(browser=browser, workspace=workspace)
    ctx = make_ctx(browser_manager, session_id="browser-preview-directory")

    try:
        result = await WebToolkit.browser_navigate(
            ctx,
            page_path.as_uri(),
        )

        assert result["snapshot_included"] is False
        assert result["status"] == 200
        assert result["resource_type"] == "html"
        assert result["meta"]["title"] == "AI Product Directory"
        assert result["meta"]["description"] == "Fresh AI products with funding and growth signals."
        assert result["headings"][0] == {
            "text": "Trending AI Products",
            "tag": "h1",
            "truncated": False,
        }
        assert [item["url"] for item in result["items"]] == [
            "https://rillet.com/",
            "https://decagon.ai/",
            "https://bland.ai/",
        ]
        assert all(set(item) == {"text", "url", "truncated"} for item in result["items"])
        assert result["items"][0]["text"].startswith("Rillet View Rillet AI-native accounting platform")
        assert "Login" not in {item["text"] for item in result["items"]}
    finally:
        await browser.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_browser_navigate_summary_does_not_extract_long_article_body(tmp_path):
    page_path = tmp_path / "article.html"
    long_paragraph = " ".join(["This paragraph is article body text about AI accounting markets."] * 35)
    page_path.write_text(
        f"""
<!doctype html>
<html>
<head>
  <title>Rillet raises funding</title>
  <meta name="description" content="A funding news article about Rillet.">
</head>
<body>
  <main>
    <article>
      <h1>Rillet raises funding from major investors</h1>
      <p>{long_paragraph}</p>
      <p>Read the <a href="https://rillet.com/blog">company blog</a> for more background.</p>
    </article>
  </main>
</body>
</html>
""",
        encoding="utf-8",
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    browser = BrowserController(headless=True, user_data_dir=str(workspace / ".browser"))
    await browser.__aenter__()
    browser_manager = FakeBrowserManager(browser=browser, workspace=workspace)
    ctx = make_ctx(browser_manager, session_id="browser-preview-article")

    try:
        result = await WebToolkit.browser_navigate(
            ctx,
            page_path.as_uri(),
        )

        assert result["meta"]["title"] == "Rillet raises funding"
        assert result["meta"]["description"] == "A funding news article about Rillet."
        assert result["headings"] == [
            {
                "text": "Rillet raises funding from major investors",
                "tag": "h1",
                "truncated": False,
            }
        ]
        assert result["items"] == []
    finally:
        await browser.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_browser_navigate_summary_truncates_each_item_text(tmp_path):
    page_path = tmp_path / "long-card.html"
    long_description = " ".join(["growth signal"] * 25)
    page_path.write_text(
        f"""
<!doctype html>
<html>
<head>
  <title>Long Card Directory</title>
</head>
<body>
  <main>
    <section class="product-card">
      <h2>Verbose Product</h2>
      <a href="https://example.test/product">View product</a>
      <p>{long_description}</p>
    </section>
  </main>
</body>
</html>
""",
        encoding="utf-8",
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    browser = BrowserController(headless=True, user_data_dir=str(workspace / ".browser"))
    await browser.__aenter__()
    browser_manager = FakeBrowserManager(browser=browser, workspace=workspace)
    ctx = make_ctx(browser_manager, session_id="browser-summary-truncation")

    try:
        result = await WebToolkit.browser_navigate(
            ctx,
            page_path.as_uri(),
        )
        assert result["items"] == [
            {
                "text": result["items"][0]["text"],
                "url": "https://example.test/product",
                "truncated": True,
            }
        ]
        assert len(result["items"][0]["text"]) <= 220
    finally:
        await browser.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_browser_navigate_summary_limits_heading_and_item_counts(tmp_path):
    page_path = tmp_path / "large-directory.html"
    headings = "\n".join(f"<h2>Category {index}</h2>" for index in range(14))
    cards = "\n".join(
        f"""
        <section class="product-card">
          <h3>Product {index}</h3>
          <a href="https://example.test/products/{index}">View Product {index}</a>
          <p>Useful visible summary for product {index} with enough text.</p>
        </section>
        """
        for index in range(10)
    )
    page_path.write_text(
        f"""
<!doctype html>
<html>
<head><title>Large Directory</title></head>
<body>
  <main>
    <h1>Large Directory</h1>
    {headings}
    {cards}
  </main>
</body>
</html>
""",
        encoding="utf-8",
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    browser = BrowserController(headless=True, user_data_dir=str(workspace / ".browser"))
    await browser.__aenter__()
    browser_manager = FakeBrowserManager(browser=browser, workspace=workspace)
    ctx = make_ctx(browser_manager, session_id="browser-summary-limits")

    try:
        result = await WebToolkit.browser_navigate(ctx, page_path.as_uri())

        assert len(result["headings"]) == 12
        assert len(result["items"]) == 8
        assert result["headings"][0]["tag"] == "h1"
        assert result["items"][0]["url"] == "https://example.test/products/0"
    finally:
        await browser.__aexit__(None, None, None)
