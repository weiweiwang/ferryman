import time

import pytest

from app.core.browser_manager import BrowserManager
from app.core.config import Settings


class FakeRuntime:
    def __init__(self, tmp_path):
        self._settings = Settings(root_dir=tmp_path)
        self.workspace_root = tmp_path / "workspaces"
        self.max_instances = 3
        self.ttl = 1800

    def get_setting(self, key, default=None):
        return self.get(key, default)

    def get(self, key, default=None):
        if key == "system.browser.max_instances":
            return self.max_instances
        if key == "system.browser.ttl":
            return self.ttl
        return default

    def get_session_workspace(self, session_id):
        path = self.workspace_root / session_id
        path.mkdir(parents=True, exist_ok=True)
        return path


class FakeBrowserController:
    created = []

    def __init__(self, headless=True, user_data_dir=None):
        self._headless = headless
        self.user_data_dir = user_data_dir
        self.closed = False
        FakeBrowserController.created.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        self.closed = True


@pytest.fixture(autouse=True)
def reset_fake_browser():
    FakeBrowserController.created = []


@pytest.mark.asyncio
async def test_browser_manager_reuses_browser_for_same_session(tmp_path, monkeypatch):
    import app.core.browser

    monkeypatch.setattr(app.core.browser, "BrowserController", FakeBrowserController)
    runtime = FakeRuntime(tmp_path)
    manager = BrowserManager(settings=runtime, get_session_workspace=runtime.get_session_workspace)

    first = await manager.get_browser("s1")
    second = await manager.get_browser("s1")

    assert first is second
    assert first._headless is True
    assert len(FakeBrowserController.created) == 1


@pytest.mark.asyncio
async def test_browser_manager_restarts_when_headless_mode_changes(tmp_path, monkeypatch):
    import app.core.browser

    monkeypatch.setattr(app.core.browser, "BrowserController", FakeBrowserController)
    runtime = FakeRuntime(tmp_path)
    manager = BrowserManager(settings=runtime, get_session_workspace=runtime.get_session_workspace)

    first = await manager.get_browser("s1", headless=True)
    second = await manager.get_browser("s1", headless=False)

    assert first.closed is True
    assert second is not first
    assert second._headless is False


@pytest.mark.asyncio
async def test_browser_manager_evicts_oldest_browser(tmp_path, monkeypatch):
    import app.core.browser

    monkeypatch.setattr(app.core.browser, "BrowserController", FakeBrowserController)
    runtime = FakeRuntime(tmp_path)
    runtime.max_instances = 1
    manager = BrowserManager(settings=runtime, get_session_workspace=runtime.get_session_workspace)

    first = await manager.get_browser("old")
    await manager.get_browser("new")

    assert first.closed is True
    assert "old" not in manager._browsers
    assert "new" in manager._browsers


@pytest.mark.asyncio
async def test_browser_manager_cleans_stale_browsers(tmp_path, monkeypatch):
    import app.core.browser

    monkeypatch.setattr(app.core.browser, "BrowserController", FakeBrowserController)
    runtime = FakeRuntime(tmp_path)
    runtime.ttl = 1
    manager = BrowserManager(settings=runtime, get_session_workspace=runtime.get_session_workspace)

    browser = await manager.get_browser("stale")
    manager._browsers["stale"]["last_active"] = time.time() - 10

    await manager.cleanup_stale_browsers()

    assert browser.closed is True
    assert manager._browsers == {}
