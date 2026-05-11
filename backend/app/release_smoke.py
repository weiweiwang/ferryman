from __future__ import annotations

import asyncio
import json
import os
import re
import socket
import sqlite3
from pathlib import Path
from types import MethodType, SimpleNamespace

import uvicorn
import websockets
from justext.utils import get_stoplist, get_stoplists
from pydantic_ai import Agent
from pydantic_ai.usage import RequestUsage, Usage

from app.core.browser import BrowserController
from app.core.config import get_settings
from app.core.runtime import FerrymanRuntime
from app.main import DEFAULT_FERRYMAN_BEARER_TOKEN, app as fastapi_app
from app.core.toolkits.command import CommandToolkit
from app.core.toolkits.file import FileToolkit
from app.core.toolkits.skill import SkillToolkit
from app.core.toolkits.task import TaskToolkit
from app.core.toolkits.web import WebToolkit


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _coerce_json_object(value: str | dict, *, label: str) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return json.loads(value)
    raise RuntimeError(f"{label} returned unsupported payload type: {type(value).__name__}")


def _write_smoke_skill(skill_dir: Path, name: str) -> None:
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "scripts").mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        (
            "---\n"
            f"name: {name}\n"
            "description: Bundle smoke test skill\n"
            "version: 1.0.0\n"
            "author: Ferryman\n"
            "created: 2026-04-14\n"
            "updated: 2026-04-14\n"
            "---\n\n"
            "# Bundle Smoke Skill\n"
        ),
        encoding="utf-8",
    )
    (skill_dir / "scripts" / "echo.py").write_text(
        (
            "import importlib.util\n"
            "import json\n\n"
            "required_modules = ['requests', 'frontmatter', 'yfinance', 'pandas', 'numpy', 'PIL']\n"
            "missing_modules = [name for name in required_modules if importlib.util.find_spec(name) is None]\n"
            "if missing_modules:\n"
            "    raise RuntimeError(f'Missing bundled skill runtime modules: {missing_modules}')\n"
            "print(json.dumps({'ok': True, 'source': 'bundle-smoke-script', 'modules': required_modules}))\n"
        ),
        encoding="utf-8",
    )


def _write_smoke_page(target: Path) -> None:
    target.write_text(
        """<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Ferryman Bundle Smoke</title>
  </head>
  <body>
    <main>
      <h1>Bundle smoke article</h1>
      <p>
        Ferryman bundle smoke validation checks that packaged browser tools can navigate,
        inspect page structure, distill readable content, and interact with form controls
        after the desktop release build is assembled.
      </p>
      <label for="name">Name</label>
      <input id="name" type="text" placeholder="Your name" />
      <button id="confirm" onclick="document.getElementById('status').innerText = 'Confirmed: ' + document.getElementById('name').value;">
        Confirm
      </button>
      <div id="status">Pending</div>
    </main>
  </body>
</html>
""",
        encoding="utf-8",
    )


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _release_online_mode() -> str:
    return (os.environ.get("FERRYMAN_RELEASE_SMOKE_ONLINE", "auto") or "auto").strip().lower()


def _load_local_gemini_config() -> dict[str, str] | None:
    db_path = Path.home() / ".ferryman" / "user" / "ferryman.db"
    if not db_path.exists():
        return None

    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "select value from app_configs where key = ?",
            ("llm.gemini",),
        ).fetchone()

    if not row or not row[0]:
        return None

    raw = json.loads(row[0]) if isinstance(row[0], str) else row[0]
    api_key = str(raw.get("api_key", "")).strip()
    base_url = str(raw.get("base_url", "")).strip()
    if not api_key:
        return None

    return {
        "api_key": api_key,
        "base_url": base_url,
        "model": "gemini-3-flash-preview",
    }


async def _rpc_call(websocket, method: str, params: dict[str, object] | None = None, request_id: int = 1) -> dict[str, object]:
    await websocket.send(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "method": method,
                "params": params or {},
                "id": request_id,
            }
        )
    )
    return json.loads(await websocket.recv())


async def _run_websocket_smoke(report: dict[str, object]) -> None:
    port = _pick_free_port()
    server = uvicorn.Server(
        uvicorn.Config(
            fastapi_app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
            access_log=False,
        )
    )
    server_task = asyncio.create_task(server.serve())
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.05)
        _require(server.started, "Embedded websocket smoke server did not start.")

        uri = f"ws://127.0.0.1:{port}/ws?access_token={DEFAULT_FERRYMAN_BEARER_TOKEN}"
        async with websockets.connect(uri) as websocket:
            ping = await _rpc_call(websocket, "ping", request_id=1)
            _require(ping.get("result") == "pong", f"Unexpected ping response: {ping}")

            skills = await _rpc_call(websocket, "list_skills", request_id=2)
            skill_names = [item["name"] for item in skills.get("result", [])]
            _require("bundle-smoke-skill" in skill_names, f"Bundled smoke skill missing from list_skills: {skill_names}")

            browser_status = await _rpc_call(websocket, "get_browser_runtime_status", request_id=3)
            runtime = browser_status.get("result", {})
            _require(runtime.get("available") is True, f"Unexpected browser runtime status via websocket: {browser_status}")

        report["checks"].append({"name": "websocket_rpc"})
    finally:
        server.should_exit = True
        await asyncio.wait_for(server_task, timeout=10)


async def _run_live_web_smoke(base_ctx, report: dict[str, object]) -> None:
    navigate_result = await WebToolkit.browser_navigate(base_ctx, "https://example.com/")
    _require(navigate_result.get("status") == "success", f"Live browser_navigate failed: {navigate_result}")
    _require(navigate_result.get("url") == "https://example.com/", f"Live browser_navigate URL mismatch: {navigate_result}")
    live_snapshot = await WebToolkit.browser_aria_snapshot(base_ctx)
    _require("Example Domain" in live_snapshot, f"Live aria snapshot missing expected content: {live_snapshot[:200]}")
    live_distilled = await WebToolkit.browser_get_distilled_dom(base_ctx)
    _require("documentation examples" in live_distilled.lower(), f"Live distilled DOM missing expected content: {live_distilled[:200]}")
    live_screenshot = await WebToolkit.browser_screenshot(base_ctx)
    _require(bool(getattr(live_screenshot, "data", b"")), "Live browser_screenshot returned empty image data.")
    report["checks"].append({"name": "web_live"})


async def _run_live_gemini_smoke(report: dict[str, object]) -> None:
    config = _load_local_gemini_config()
    _require(config is not None, "Local Gemini config was not found in ~/.ferryman/user/ferryman.db.")

    from pydantic_ai.models.google import GoogleModel
    from pydantic_ai.providers.google import GoogleProvider

    provider_kwargs = {"api_key": config["api_key"]}
    if config["base_url"]:
        provider_kwargs["base_url"] = config["base_url"]

    agent = Agent(
        model=GoogleModel(config["model"], provider=GoogleProvider(**provider_kwargs)),
        system_prompt="Reply with exactly OK.",
    )
    result = await agent.run("Reply with exactly OK.")
    output = str(result.output).strip()
    _require(output.upper().startswith("OK"), f"Unexpected Gemini live smoke output: {output!r}")
    report["checks"].append({"name": "gemini_live", "model": config["model"]})


async def run_bundle_smoke_test() -> dict[str, object]:
    settings = get_settings()
    runtime = FerrymanRuntime(settings)
    session_id = "bundle-smoke"
    workspace = runtime.get_session_workspace(session_id)
    base_ctx = SimpleNamespace(
        deps=runtime.create_agent_deps(session_id=session_id, run_id="run-release-smoke-base"),
        usage=Usage(),
    )
    report: dict[str, object] = {"root_dir": str(settings.root_dir), "checks": []}
    scheduler_started = False

    try:
        await runtime.schedule_manager.start()
        scheduler_started = True

        runtime.skill_manager.scan_skills()
        report["checks"].append({"name": "scan_skills", "count": len(runtime.skill_manager.skills)})
        _require(bool(runtime.skill_manager.skills), "No skills were loaded from the bundled skill directories.")
        _require("bundle-smoke-skill" in runtime.skill_manager.skills, "Bundled smoke skill was not staged into the release assets.")

        stoplists = get_stoplists()
        _require(bool(stoplists), "jusText stoplists were not found in the bundled runtime.")
        english_stoplist = get_stoplist("English")
        _require(bool(english_stoplist), "jusText English stoplist could not be loaded from the bundle.")
        report["checks"].append({"name": "justext_stoplists", "count": len(stoplists)})

        write_result = await FileToolkit.write_file(base_ctx, "notes/hello.txt", "bundle smoke")
        _require("Successfully wrote" in write_result, f"Unexpected write_file result: {write_result}")
        read_result = await FileToolkit.read_file(base_ctx, "notes/hello.txt")
        _require(read_result == "bundle smoke", f"Unexpected read_file result: {read_result!r}")
        list_result = await FileToolkit.list_files(base_ctx, "notes")
        _require("hello.txt" in list_result, f"list_files did not include hello.txt: {list_result}")
        report["checks"].append({"name": "file_tools"})

        task_result = await TaskToolkit.create_task(
            base_ctx,
            title="Bundle smoke task",
            instruction="Verify packaged task persistence.",
            metadata={"scope": "bundle-smoke"},
        )
        task_id_match = re.search(r"ID=([^,]+)", task_result)
        _require(task_id_match is not None, f"Could not parse task id from: {task_result}")
        task_id = task_id_match.group(1)
        update_result = await TaskToolkit.update_task(base_ctx, task_id, "running", "bundle smoke running")
        _require(task_id in update_result, f"Unexpected update_task result: {update_result}")
        task_listing = await TaskToolkit.list_tasks(base_ctx, query="bundle-smoke")
        _require("Bundle smoke task" in task_listing, f"list_tasks missing bundle smoke task: {task_listing}")
        schedule_result = await TaskToolkit.create_schedule(
            base_ctx,
            name="bundle-smoke-schedule",
            cron_expression="0 * * * *",
            instruction="Verify packaged schedule persistence.",
        )
        _require("bundle-smoke-schedule" in schedule_result, f"Unexpected create_schedule result: {schedule_result}")
        schedule_listing = await TaskToolkit.list_schedules(base_ctx)
        _require("bundle-smoke-schedule" in schedule_listing, f"list_schedules missing schedule: {schedule_listing}")
        report["checks"].append({"name": "task_tools"})

        bundled_skill_ctx = SimpleNamespace(
            deps=runtime.create_agent_deps(
                session_id=session_id,
                run_id="run-release-smoke-skill",
                skill_name="bundle-smoke-skill",
            ),
            usage=Usage(),
        )
        bundled_assets = await FileToolkit.list_files(bundled_skill_ctx, "assets")
        _require("sample.txt" in bundled_assets, f"Bundled skill assets are missing: {bundled_assets}")
        bundled_asset_text = await FileToolkit.read_file(bundled_skill_ctx, "assets/sample.txt")
        _require("Ferryman bundled skill asset check." in bundled_asset_text, f"Unexpected bundled asset contents: {bundled_asset_text!r}")
        bundled_reference_text = await FileToolkit.read_file(bundled_skill_ctx, "references/sample.md")
        _require("Bundle Smoke Reference" in bundled_reference_text, f"Unexpected bundled reference contents: {bundled_reference_text!r}")
        bundled_script_result = _coerce_json_object(
            await CommandToolkit.run_skill_script(bundled_skill_ctx, "verify_bundle_resources.py"),
            label="run_skill_script(verify_bundle_resources.py)",
        )
        _require(
            bundled_script_result == {
                "asset": "Ferryman bundled skill asset check.",
                "reference": "# Bundle Smoke Reference\nFerryman bundled skill reference check.",
                "modules": ["requests", "frontmatter", "yfinance", "pandas", "numpy", "PIL"],
            },
            f"Bundled skill script returned unexpected payload: {bundled_script_result}",
        )
        report["checks"].append({"name": "bundled_skill_resources"})

        draft_skill_dir = workspace / "bundle-smoke-draft-skill"
        _write_smoke_skill(draft_skill_dir, "bundle-smoke-draft-skill")
        publish_result = _coerce_json_object(
            await SkillToolkit.publish_skill(base_ctx, "bundle-smoke-draft-skill"),
            label="publish_skill(bundle-smoke-draft-skill)",
        )
        _require(publish_result["ok"] is True, f"publish_skill failed: {publish_result}")
        _require("bundle-smoke-draft-skill" in runtime.skill_manager.skills, "Published smoke skill was not registered.")

        skill_ctx = SimpleNamespace(
            deps=runtime.create_agent_deps(
                session_id=session_id,
                run_id="run-release-smoke-draft-skill",
                skill_name="bundle-smoke-draft-skill",
            ),
            usage=Usage(),
        )
        skill_files = await FileToolkit.list_files(skill_ctx, str(runtime.skill_manager.skills["bundle-smoke-draft-skill"].path))
        _require("SKILL.md" in skill_files, f"Published skill resources not readable: {skill_files}")
        command_result = _coerce_json_object(
            await CommandToolkit.run_skill_script(skill_ctx, "echo.py"),
            label="run_skill_script(echo.py)",
        )
        _require(command_result.get("source") == "bundle-smoke-script", f"Unexpected script stdout: {command_result}")
        _require(
            command_result.get("modules") == ["requests", "frontmatter", "yfinance", "pandas", "numpy", "PIL"],
            f"Skill runtime modules were not verified: {command_result}",
        )

        original_build_skill_agent = runtime.agent_manager.build_skill_agent

        class FakeSkillResult:
            output = "bundle-smoke-skill-ran"

            @staticmethod
            def usage():
                return RequestUsage(input_tokens=1, output_tokens=1)

        class FakeSkillAgent:
            async def run(self, instruction, deps, usage, usage_limits, event_stream_handler=None):
                _require("Runtime Context:" in instruction, "Skill instruction was not runtime-augmented.")
                _require(deps.skill_name == "bundle-smoke-skill", "Skill deps did not carry the active skill name.")
                _require(usage is base_ctx.usage, "Skill usage object was not forwarded.")
                _require(event_stream_handler is not None, "Skill event stream handler was not forwarded.")
                return FakeSkillResult()

        def build_fake_skill_agent(self, skill_name, *, session_id=None, run_id=None, usage_tracker=None):
            _require(session_id == base_ctx.deps.session_id, "Skill agent did not receive the active session id.")
            _require(run_id == base_ctx.deps.run_id, "Skill agent did not receive the active run id.")
            _require(usage_tracker is base_ctx.deps.model_usage_tracker, "Skill agent did not receive the usage tracker.")
            return FakeSkillAgent()

        runtime.agent_manager.build_skill_agent = MethodType(build_fake_skill_agent, runtime.agent_manager)
        try:
            skill_run_result = await SkillToolkit.run_skill(base_ctx, "bundle-smoke-skill", "Run smoke skill")
        finally:
            runtime.agent_manager.build_skill_agent = original_build_skill_agent
        _require(skill_run_result == "bundle-smoke-skill-ran", f"run_skill returned unexpected output: {skill_run_result}")
        report["checks"].append({"name": "skill_tools"})

        browser_status = BrowserController.get_runtime_status()
        _require(browser_status["available"] is True, f"System Chrome unavailable for bundle smoke test: {browser_status}")

        smoke_page = workspace / "bundle-smoke.html"
        _write_smoke_page(smoke_page)
        navigate_result = await WebToolkit.browser_navigate(base_ctx, smoke_page.as_uri())
        _require(navigate_result.get("status") == "success", f"browser_navigate failed: {navigate_result}")
        _require(navigate_result.get("title") == "Ferryman Bundle Smoke", f"Unexpected page title: {navigate_result}")
        snapshot = await WebToolkit.browser_aria_snapshot(base_ctx)
        textbox_match = re.search(r'textbox.*\[(\d+)\]', snapshot)
        button_match = re.search(r'button.*\[(\d+)\]', snapshot)
        _require(textbox_match is not None, f"ARIA snapshot missing textbox id: {snapshot}")
        _require(button_match is not None, f"ARIA snapshot missing button id: {snapshot}")

        type_result = await WebToolkit.browser_type(base_ctx, textbox_match.group(1), "Ferryman")
        _require("Successfully typed" in type_result, f"browser_type failed: {type_result}")
        click_result = await WebToolkit.browser_click(base_ctx, button_match.group(1))
        _require("Successfully clicked" in click_result, f"browser_click failed: {click_result}")
        wait_result = await WebToolkit.browser_wait(base_ctx, 200)
        _require("Waited for 200ms." == wait_result, f"Unexpected browser_wait result: {wait_result}")
        distilled = await WebToolkit.browser_get_distilled_dom(base_ctx)
        _require("Bundle smoke article" in distilled, f"browser_get_distilled_dom failed: {distilled[:200]}")

        browser = await runtime.browser_manager.get_browser(session_id)
        page_status = await browser._page.evaluate("document.getElementById('status').innerText")
        _require(page_status == "Confirmed: Ferryman", f"Browser interaction did not update page state: {page_status}")
        screenshot = await WebToolkit.browser_screenshot(base_ctx)
        _require(bool(getattr(screenshot, "data", b"")), "browser_screenshot returned empty image data.")
        report["checks"].append({"name": "web_tools"})

        await _run_websocket_smoke(report)

        online_mode = _release_online_mode()
        if online_mode not in {"auto", "always", "never"}:
            raise RuntimeError(f"Unsupported FERRYMAN_RELEASE_SMOKE_ONLINE mode: {online_mode}")

        should_run_online = online_mode == "always"
        if online_mode == "auto":
            should_run_online = _load_local_gemini_config() is not None

        if should_run_online:
            await _run_live_web_smoke(base_ctx, report)
            await _run_live_gemini_smoke(report)

        return report
    finally:
        if scheduler_started:
            await runtime.schedule_manager.shutdown()
        await runtime.browser_manager.shutdown()


def main() -> int:
    report = asyncio.run(run_bundle_smoke_test())
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
