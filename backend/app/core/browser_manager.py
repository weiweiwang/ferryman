from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional, TypedDict

from app.core.config import Settings

if TYPE_CHECKING:
    from app.core.browser import BrowserController

logger = logging.getLogger(__name__)


class BrowserEntry(TypedDict):
    instance: "BrowserController"
    last_active: float


class BrowserManager:
    """Manage browser controllers and their session-scoped lifecycle."""

    def __init__(self, settings: Settings, get_session_workspace: Callable[[str], Path]) -> None:
        self._settings = settings
        self._get_session_workspace = get_session_workspace
        self._browsers: dict[str, BrowserEntry] = {}
        self._session_headless: dict[str, bool] = {}

    async def get_browser(self, session_id: str, headless: Optional[bool] = None) -> "BrowserController":
        await self.cleanup_stale_browsers()

        requested_headless = headless if headless is not None else True
        if headless is not None:
            self._session_headless[session_id] = headless

        if session_id in self._browsers:
            entry = self._browsers[session_id]
            existing_browser = entry["instance"]

            if headless is not None and existing_browser._headless != headless:
                logger.info(
                    f"Browser mode change detected ({existing_browser._headless} -> {headless}). Restarting..."
                )
                await self.close_browser(session_id)
            else:
                entry["last_active"] = time.time()
                return existing_browser

        max_instances: int = self._settings.get("system.browser.max_instances", 3)
        if session_id not in self._browsers and len(self._browsers) >= max_instances:
            oldest_sid = min(
                self._browsers.keys(),
                key=lambda sid: self._browsers[sid]["last_active"],
            )
            logger.info(f"Max browser instances ({max_instances}) reached. Evicting oldest: {oldest_sid}")
            await self.close_browser(oldest_sid)

        if session_id not in self._browsers:
            from app.core.browser import BrowserController

            workspace_dir = self._get_session_workspace(session_id)
            browser_profile_dir = workspace_dir / ".browser"

            browser = BrowserController(
                headless=requested_headless,
                user_data_dir=str(browser_profile_dir),
            )
            await browser.__aenter__()
            self._browsers[session_id] = {
                "instance": browser,
                "last_active": time.time(),
            }

        return self._browsers[session_id]["instance"]

    async def close_browser(self, session_id: str) -> None:
        entry = self._browsers.pop(session_id, None)
        if entry:
            browser = entry["instance"]
            try:
                await browser.__aexit__(None, None, None)
            except Exception as e:
                logger.exception(
                    f"Failed to gracefully close browser for session {session_id}, "
                    f"but removed from cache, exception: {e}"
                )

    async def cleanup_stale_browsers(self) -> None:
        ttl = self._settings.get("system.browser.ttl", 1800)
        now = time.time()
        stale_sids = [
            sid
            for sid, entry in self._browsers.items()
            if now - entry["last_active"] > ttl
        ]

        for sid in stale_sids:
            logger.info(f"Cleaning up stale browser for session: {sid}")
            await self.close_browser(sid)

    async def shutdown(self) -> None:
        for sid in list(self._browsers.keys()):
            await self.close_browser(sid)
