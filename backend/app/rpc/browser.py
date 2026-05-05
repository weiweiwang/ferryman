from __future__ import annotations

from jsonrpcserver import Success, method


@method
async def get_browser_runtime_status(context):
    from app.core.browser import BrowserController

    return Success(BrowserController.get_runtime_status())

