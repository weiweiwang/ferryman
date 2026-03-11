import asyncio
import logging
from playwright.async_api import async_playwright, Page, BrowserContext
from playwright_stealth import Stealth
import trafilatura

logger = logging.getLogger(__name__)

class BrowserController:
    """
    RISC Web Kernel for Ferryman.
    Encapsulates Playwright headless browsing with stealth capabilities 
    and exposes only 4 core atomic actions to the LLM agent.
    """
    def __init__(self, headless: bool = True):
        self._headless = headless
        self._playwright = None
        self._browser = None
        self._context: BrowserContext = None
        self._page: Page = None
        
    async def __aenter__(self):
        self._playwright = await async_playwright().start()
        
        # OpenClaw-inspired Stealth args
        args = [
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
            "--password-store=basic",
            "--disable-sync"
        ]
        
        self._browser = await self._playwright.chromium.launch(
            headless=self._headless,
            args=args
        )
        
        self._context = await self._browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        self._page = await self._context.new_page()
        
        # Apply Playwright-Stealth patch (v2.x API)
        await Stealth().apply_stealth_async(self._page)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    # -------------------------------------------------------------------------
    # RISC Web Actions (Exposed to the Agent as Tools)
    # -------------------------------------------------------------------------

    async def navigate(self, url: str) -> str:
        """Navigates to the given URL and waits for it to load."""
        logger.info(f"Navigating to {url}")
        try:
            await self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
            # Add a small semantic wait for frameworks to catch up
            await asyncio.sleep(2)
            return f"Successfully navigated to {self._page.url}"
        except Exception as e:
            return f"Failed to navigate: {str(e)}"

    async def get_distilled_dom(self) -> str:
        """Distills the DOM to return pure text/markdown content, avoiding token waste."""
        logger.info("Distilling DOM content...")
        try:
            # 1. First, try to extract hyper-clean text using Trafilatura (ideal for articles)
            html = await self._page.content()
            distilled_text = trafilatura.extract(html, include_links=True, include_images=False)
            
            if distilled_text and len(distilled_text) > 100:
                return distilled_text
            
            # 2. Fallback if trafilatura yields too little (e.g. dynamic UI apps): get innerText
            logger.info("Trafilatura yielded low content. Falling back to body innerText.")
            body_text = await self._page.evaluate("document.body.innerText")
            # Limit to 15k chars to prevent blowing up the LLM context anyway
            return body_text[:15000]
        except Exception as e:
            return f"Failed to distill DOM: {str(e)}"

    async def get_aria_snapshot(self) -> str:
        """
        Returns a high-density 'Accessibility Tree' snapshot with stable interaction IDs.
        Enables the LLM to click/type using simple numeric indices like [12].
        """
        logger.info("Generating ID-mapped ARIA snapshot...")
        
        # Reset mapping for this snapshot
        self._id_to_selector = {}
        
        js_script = """
        () => {
            let nextId = 1;
            const mapping = {};
            
            const getAriaRole = (el) => {
                if (el.getAttribute('role')) return el.getAttribute('role');
                const tag = el.tagName.toLowerCase();
                const types = {
                    'button': 'button', 'a': 'link', 'input': 'textbox',
                    'h1': 'heading', 'h2': 'heading', 'h3': 'heading',
                    'nav': 'navigation', 'main': 'main', 'footer': 'contentinfo',
                    'header': 'banner', 'table': 'table', 'ul': 'list', 'li': 'listitem'
                };
                if (tag === 'input') {
                    const type = el.type.toLowerCase();
                    if (['button', 'submit', 'reset'].includes(type)) return 'button';
                    if (type === 'checkbox') return 'checkbox';
                    if (type === 'radio') return 'radio';
                }
                return types[tag] || null;
            };

            const getAriaName = (el) => {
                return (el.getAttribute('aria-label') || 
                       el.innerText?.trim().split('\\n')[0].substring(0, 50) || 
                       el.placeholder || 
                       el.title || 
                       el.alt || '').trim();
            };

            const isVisible = (el) => {
                const style = window.getComputedStyle(el);
                return style.display !== 'none' && style.visibility !== 'hidden' && el.offsetWidth > 0;
            };
            
            const isInteractive = (role) => {
                return ['button', 'link', 'textbox', 'checkbox', 'radio', 'combobox', 'menuitem'].includes(role);
            };

            const traverse = (el, depth = 0) => {
                let result = '';
                const role = getAriaRole(el);
                const name = getAriaName(el);
                
                if (role && isVisible(el)) {
                    const indent = '  '.repeat(depth);
                    let idStr = '';
                    if (isInteractive(role)) {
                        const id = nextId++;
                        el.setAttribute('data-ferryman-id', id.toString());
                        idStr = ` [${id}]`;
                        mapping[id] = `[data-ferryman-id="${id}"]`;
                    }
                    result += `${indent}- ${role}${name ? ' "' + name + '"' : ''}${idStr}\\n`;
                    depth++;
                }

                for (const child of el.children) {
                    result += traverse(child, depth);
                }
                return result;
            };

            const snapshot = traverse(document.body);
            return { snapshot, mapping };
        }
        """
        try:
            result = await self._page.evaluate(js_script)
            self._id_to_selector = result['mapping']
            return result['snapshot'] if result['snapshot'] else "(No semantic elements found)"
        except Exception as e:
            return f"Failed to generate ARIA snapshot: {str(e)}"

    async def click_id(self, element_id: str) -> str:
        """Clicks an element by its semantic ID from the last snapshot."""
        selector = self._id_to_selector.get(str(element_id))
        if not selector:
            return f"Error: ID '{element_id}' not found in the last snapshot. Please call browser_aria_snapshot again."
        return await self.click(selector)

    async def type_id(self, element_id: str, text: str) -> str:
        """Types text into an element by its semantic ID from the last snapshot."""
        selector = self._id_to_selector.get(str(element_id))
        if not selector:
            return f"Error: ID '{element_id}' not found. Please refresh the snapshot."
        return await self.type(selector, text)

    async def click(self, selector: str) -> str:
        """Clicks an element defined by the selector."""
        logger.info(f"Clicking on {selector}")
        try:
            await self._page.wait_for_selector(selector, state="visible", timeout=5000)
            await self._page.click(selector, timeout=5000)
            return f"Successfully clicked '{selector}'"
        except Exception as e:
            return f"Failed to click '{selector}': {str(e)}"

    async def hover(self, selector: str) -> str:
        """Hovers over an element defined by the selector."""
        logger.info(f"Hovering over {selector}")
        try:
            await self._page.wait_for_selector(selector, state="visible", timeout=5000)
            await self._page.hover(selector, timeout=5000)
            return f"Successfully hovered over '{selector}'"
        except Exception as e:
            return f"Failed to hover over '{selector}': {str(e)}"

    async def scroll(self, selector: str = None) -> str:
        """Scrolls the page or a specific element into view."""
        logger.info(f"Scrolling {selector if selector else 'page'}")
        try:
            if selector:
                await self._page.wait_for_selector(selector, state="visible", timeout=5000)
                await self._page.locator(selector).scroll_into_view_if_needed(timeout=5000)
                return f"Successfully scrolled to '{selector}'"
            else:
                await self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                return "Successfully scrolled to bottom of page"
        except Exception as e:
            return f"Failed to scroll: {str(e)}"

    async def wait(self, timeout_ms: int = 2000, selector: str = None) -> str:
        """Waits for a specified time or for a selector to become visible."""
        try:
            if selector:
                logger.info(f"Waiting for {selector} for {timeout_ms}ms")
                await self._page.wait_for_selector(selector, state="visible", timeout=timeout_ms)
                return f"Selector '{selector}' appeared."
            else:
                logger.info(f"Waiting for {timeout_ms}ms")
                await asyncio.sleep(timeout_ms / 1000)
                return f"Waited for {timeout_ms}ms."
        except Exception as e:
            return f"Wait failed: {str(e)}"

    async def screenshot(self, selector: str = None) -> str:
        """Takes a screenshot of the page or a specific element. Returns the path to the screenshot."""
        import uuid
        from pathlib import Path
        filename = f"screenshot_{uuid.uuid4().hex[:8]}.png"
        # Note: In a real scenario, we'd save this in the session's workspace.
        # For now, we'll use a predictable artifacts path if we can find it.
        # But this is just a tool, so we return the descriptive path.
        logger.info(f"Taking screenshot of {selector if selector else 'page'}")
        p = Path("/tmp") / filename
        try:
            if selector:
                await self._page.locator(selector).screenshot(path=str(p))
            else:
                await self._page.screenshot(path=str(p), full_page=True)
            return f"Screenshot saved to {p}"
        except Exception as e:
            return f"Failed to take screenshot: {str(e)}"

    async def type(self, selector: str, text: str) -> str:
        """Types text into an input field defined by the selector."""
        logger.info(f"Typing into {selector}")
        try:
            await self._page.wait_for_selector(selector, state="visible", timeout=5000)
            # Clear first, then type
            await self._page.fill(selector, text)
            return f"Successfully typed '{text}' into '{selector}'"
        except Exception as e:
            return f"Failed to type in '{selector}': {str(e)}"
