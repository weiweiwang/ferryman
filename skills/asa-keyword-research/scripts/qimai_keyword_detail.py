import argparse
import json
import logging
import sys
import asyncio

# This script is intended to be run by the Ferryman agent which has access to the browser.
# However, for a standalone script, we can use playwright directly.
try:
    from playwright.async_api import async_playwright
    from playwright_stealth import stealth_async
except ImportError:
    print(json.dumps({"ok": False, "error": "Playwright or playwright-stealth not installed."}))
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

async def fetch_qimai_keyword_detail(appid: str, country: str = "cn"):
    """
    Fetch keyword details for a specific app from QiMai.
    Uses a headless browser to handle cookies and headers.
    """
    url = f"https://www.qimai.cn/app/keyword/appid/{appid}/country/{country}"
    api_url = f"https://api.qimai.cn/appDetail/keywordDetail?appid={appid}&country={country}"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        await stealth_async(page)

        try:
            # 1. Navigate to the app page to establish session/cookies
            logger.info(f"Navigating to {url}...")
            # We wait for the page to load and potentially trigger its own API calls
            await page.goto(url, wait_until="networkidle", timeout=30000)

            # 2. Call the API from the page context
            logger.info(f"Fetching API via page.evaluate: {api_url}")

            # Attempt to fetch directly from page context.
            # This is more likely to succeed as it includes cookies and the correct referrer.
            data_json = await page.evaluate("""
                async (apiUrl) => {
                    try {
                        const response = await fetch(apiUrl);
                        if (!response.ok) return { error: 'HTTP ' + response.status };
                        return await response.json();
                    } catch (e) {
                        return { error: e.message };
                    }
                }
            """, api_url)

            if not isinstance(data_json, dict):
                return {"ok": False, "error": "QiMai API returned a non-object response"}

            if "error" in data_json:
                return {"ok": False, "error": f"Fetch failed: {data_json['error']}"}

            if data_json.get("code") == 10000:
                return {"ok": True, "data": data_json.get("data")}
            else:
                return {"ok": False, "error": f"QiMai API error {data_json.get('code')}: {data_json.get('msg')}"}

        except Exception as e:
            logger.error(f"Error during QiMai fetch: {e}")
            return {"ok": False, "error": str(e)}
        finally:
            await browser.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch keyword details from QiMai")
    parser.add_argument("--appid", required=True, help="Apple App ID")
    parser.add_argument("--country", default="cn", help="Country code (default: cn)")

    args = parser.parse_args()

    result = asyncio.run(fetch_qimai_keyword_detail(args.appid, args.country))

    print(json.dumps(result, ensure_ascii=False))
