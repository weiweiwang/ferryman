from pydantic_ai.messages import BinaryImage
from pydantic_ai.tools import RunContext
from app.core.deps import AgentDeps
from typing import Optional

class WebToolkit:
    """Browser tools for page navigation, inspection, interaction, and capture."""

    @staticmethod
    def get_tools():
        return [
            WebToolkit.browser_navigate,
            WebToolkit.browser_get_distilled_dom,
            WebToolkit.browser_aria_snapshot,
            WebToolkit.browser_click,
            WebToolkit.browser_type,
            WebToolkit.browser_wait,
            WebToolkit.browser_screenshot,
        ]

    @staticmethod
    async def browser_navigate(ctx: RunContext[AgentDeps], url: str, headless: Optional[bool] = None) -> str:
        """Open a URL in the session browser.

        Set `headless=False` when the browser should stay visible to the user.
        """
        browser = await ctx.deps.kernel.get_browser(ctx.deps.session_id, headless=headless)
        return await browser.navigate(url)

    @staticmethod
    async def browser_get_distilled_dom(ctx: RunContext[AgentDeps]) -> str:
        """Extract readable page text for analysis.

        Best for article or content reading, not precise interaction targeting.
        """
        browser = await ctx.deps.kernel.get_browser(ctx.deps.session_id)
        return await browser.get_distilled_dom()

    @staticmethod
    async def browser_click(ctx: RunContext[AgentDeps], selector: str) -> str:
        """Click an element in the current page.

        Accepts a selector. IDs from `browser_aria_snapshot` are recommended
        for stability.
        """
        browser = await ctx.deps.kernel.get_browser(ctx.deps.session_id)
        return await browser.click(selector)

    @staticmethod
    async def browser_type(ctx: RunContext[AgentDeps], selector: str, text: str) -> str:
        """Type into an element in the current page.

        Accepts a selector. IDs from `browser_aria_snapshot` are recommended
        for stability.
        """
        browser = await ctx.deps.kernel.get_browser(ctx.deps.session_id)
        return await browser.type(selector, text)

    # Note: Other tools like aria_snapshot, hover, scroll etc are internal/advanced
    # and can be added if needed, but the RISC goal is 4 core actions.

    @staticmethod
    async def browser_aria_snapshot(ctx: RunContext[AgentDeps]) -> str:
        """Return an accessibility snapshot with stable IDs for later interactions."""
        browser = await ctx.deps.kernel.get_browser(ctx.deps.session_id)
        return await browser.get_aria_snapshot()
        
    @staticmethod
    async def browser_wait(ctx: RunContext[AgentDeps], timeout_ms: int = 2000) -> str:
        """Wait for the given number of milliseconds."""
        browser = await ctx.deps.kernel.get_browser(ctx.deps.session_id)
        return await browser.wait(timeout_ms)

    @staticmethod
    async def browser_screenshot(ctx: RunContext[AgentDeps], selector: Optional[str] = None) -> BinaryImage:
        """Capture a page or element screenshot.

        Saves the image under the session workspace and returns it as
        `BinaryImage`.
        """
        browser = await ctx.deps.kernel.get_browser(ctx.deps.session_id)
        screenshot_dir = ctx.deps.kernel.get_session_workspace(ctx.deps.session_id) / "screenshots"
        return await browser.screenshot(selector, output_dir=screenshot_dir)
