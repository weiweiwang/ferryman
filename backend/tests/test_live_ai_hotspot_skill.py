import asyncio
import logging
import os
import sys
from pathlib import Path

import pytest
import shortuuid

# Add backend to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.config import get_settings
from app.core.kernel import FerrymanKernel


class InMemoryLogHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.mark.asyncio
async def test_live_ai_hotspot_skill_stable_sources_only():
    settings = get_settings()
    assert settings.get_provider_llm_config("gemini").get("api_key"), "Gemini API key is not configured."

    instruction = """
请使用 ai-hotspot-miner skill 生成一份 AI 热点报告。

本次验证范围请只使用稳定公开来源：
- Hacker News
- GitHub Trending
- 一个公开科技媒体 AI 页面

本次不要访问 Reddit、X、微信，以降低 HITL 干扰。

硬性要求：
1. 必须实际使用 ai-hotspot-miner skill，而不是跳过 skill 自己总结。
2. 必须实际调用浏览器工具访问网页。
3. 最终把报告保存到当前 session workspace 的 reports 目录。
4. 最终回复里给出报告路径。
5. Top Hotspots 里不允许出现 “Hacker News signal” / “GitHub Trending signal” / “TechCrunch AI signal” 这类占位标题。
6. 输出语言用中文。
""".strip()

    kernel = FerrymanKernel(settings)
    kernel.scan_skills()
    assert "ai-hotspot-miner" in kernel.skills, "Bundled ai-hotspot-miner skill was not discovered."

    last_result = None
    last_session_id = None
    tool_events: list[dict] = []
    log_records: list[logging.LogRecord] = []
    result = None

    for attempt in range(2):
        session_id = f"live-ai-hotspot-{shortuuid.uuid()}"
        current_tool_events: list[dict] = []

        async def emit_event_cb(event) -> None:
            current_tool_events.append(event.model_dump(mode="json"))

        skill_logger = logging.getLogger("app.core.toolkits.skill")
        log_handler = InMemoryLogHandler()
        skill_logger.addHandler(log_handler)
        skill_logger.setLevel(logging.INFO)

        try:
            current_result = await asyncio.wait_for(
                kernel.run_master_agent(instruction, session_id, emit_event_cb=emit_event_cb),
                timeout=420,
            )
        finally:
            await kernel.close_browser(session_id)
            skill_logger.removeHandler(log_handler)

        if isinstance(current_result, dict):
            result = current_result
            last_session_id = session_id
            tool_events = current_tool_events
            log_records = log_handler.records[:]
            break

        last_result = current_result
        last_session_id = session_id
        tool_events = current_tool_events
        log_records = log_handler.records[:]

        if "Server disconnected without sending a response." not in str(current_result):
            break

    if not isinstance(result, dict):
        pytest.fail(f"Live run did not complete successfully after retry: {last_result}")

    assert result["event"] == "chat_final"

    skill_tool_started = any(
        event.get("event") == "tool_activity"
        and event.get("payload", {}).get("tool_name") == "run_skill"
        and event.get("payload", {}).get("phase") == "start"
        for event in tool_events
    )
    assert skill_tool_started, "Master agent did not trigger run_skill."

    exact_skill_logged = any(
        "Executing skill 'ai-hotspot-miner'" in str(record.msg) or "Executing skill 'ai-hotspot-miner'" in record.getMessage()
        for record in log_records
    )
    assert exact_skill_logged, "Did not observe ai-hotspot-miner execution log."

    browser_tools_started = [
        event.get("payload", {}).get("tool_name")
        for event in tool_events
        if event.get("event") == "tool_activity"
        and event.get("payload", {}).get("phase") == "start"
        and str(event.get("payload", {}).get("tool_name", "")).startswith("browser_")
    ]
    assert browser_tools_started, "No browser tool usage was observed."

    workspace = kernel.get_session_workspace(last_session_id)
    report_dir = workspace / "reports"
    report_files = sorted(report_dir.glob("ai-hotspot-report-*.md"))
    if not report_files:
        report_files = sorted(report_dir.glob("ai_hotspot_report_*.md"))
    assert report_files, f"No report file found in workspace reports dir: {report_dir}"

    report_text = report_files[-1].read_text(encoding="utf-8")
    assert "Top Hotspots" in report_text, "Report is missing Top Hotspots section."

    banned_titles = [
        "Hacker News signal",
        "GitHub Trending signal",
        "TechCrunch AI signal",
    ]
    for banned in banned_titles:
        assert banned not in report_text, f"Report still contains placeholder hotspot title: {banned}"

    final_text = result["payload"]["messages"][0]["content"]
    assert str(report_files[-1]) in final_text, "Final response did not include the report path."
