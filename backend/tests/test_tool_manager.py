import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelRetry, SkipToolExecution

from app.core.config import Settings
from app.core.runtime import FerrymanRuntime
from app.core.tool_manager import (
    FerrymanToolValidationCapability,
    ToolManager,
    summarize_tool_input_value,
)
from app.core.toolkits.base import Toolkit
from app.core.toolkits.email import EmailToolkit
from app.models.events import ToolPhase


class DummyToolkit(Toolkit):
    @staticmethod
    def get_tools():
        async def dummy_tool(ctx, arg1: str):
            if arg1 == "fail":
                raise ValueError("Intentional error")
            return f"Processed {arg1}"

        return [dummy_tool]


class RetryToolkit(Toolkit):
    @staticmethod
    def get_tools():
        async def retry_tool(ctx):
            raise ModelRetry("bad arguments")

        return [retry_tool]


def parse_tool_return(result):
    return json.loads(getattr(result, "return_value", result))


def test_summarize_tool_input_value_redacts_and_omits_large_content():
    assert summarize_tool_input_value("api_key", "secret") == {"_summary": "redacted"}
    assert summarize_tool_input_value("content", "abc") == {"_summary": "omitted", "length": 3}
    assert summarize_tool_input_value("payload", b"abc") == {"_summary": "binary", "length": 3}


@pytest.mark.asyncio
async def test_tool_validation_capability_normalizes_json_string_array_args():
    capability = FerrymanToolValidationCapability()
    tool_def = SimpleNamespace(
        parameters_json_schema={
            "type": "object",
            "properties": {
                "attachments": {
                    "anyOf": [
                        {"type": "array", "items": {"type": "object"}},
                        {"type": "null"},
                    ],
                },
            },
        },
    )
    args = {
        "attachments": '[{"filename": "report.png", "path": "report.png"}]',
    }

    normalized = await capability.before_tool_validate(
        SimpleNamespace(),
        call=SimpleNamespace(tool_name="send_email"),
        tool_def=tool_def,
        args=args,
    )

    assert normalized == {
        "attachments": [
            {"filename": "report.png", "path": "report.png"},
        ],
    }


@pytest.mark.asyncio
async def test_tool_validation_capability_normalizes_with_real_send_email_schema():
    capability = FerrymanToolValidationCapability()
    agent = Agent("test")
    ToolManager().register_toolkit(agent, EmailToolkit)
    tool_def = agent._function_toolset.tools["send_email"].function_schema
    args = {
        "to": ["user@example.com"],
        "subject": "Report",
        "text": "See attached.",
        "attachments": '[{"filename": "report.png", "path": "report.png"}]',
    }

    normalized = await capability.before_tool_validate(
        SimpleNamespace(),
        call=SimpleNamespace(tool_name="send_email"),
        tool_def=SimpleNamespace(parameters_json_schema=tool_def.json_schema),
        args=args,
    )

    assert normalized["attachments"] == [
        {"filename": "report.png", "path": "report.png"},
    ]
    assert normalized["to"] == ["user@example.com"]


@pytest.mark.asyncio
async def test_tool_validation_capability_returns_tool_error_for_validation_failures():
    capability = FerrymanToolValidationCapability()
    args = await capability.on_tool_validate_error(
        SimpleNamespace(),
        call=SimpleNamespace(tool_name="send_email"),
        tool_def=SimpleNamespace(parameters_json_schema={}),
        args={"attachments": "not-json"},
        error=ModelRetry("attachments must be an array"),
    )

    with pytest.raises(SkipToolExecution) as exc_info:
        await capability.before_tool_execute(
            SimpleNamespace(),
            call=SimpleNamespace(tool_name="send_email"),
            tool_def=SimpleNamespace(parameters_json_schema={}),
            args=args,
        )

    payload = parse_tool_return(exc_info.value.result)
    assert payload["status"] == "error"
    assert payload["tool_name"] == "send_email"
    assert payload["error"]["type"] == "tool_validation_error"
    assert payload["error"]["retryable"] is True
    assert payload["error"]["message"] == "attachments must be an array"


@pytest.mark.asyncio
async def test_tool_manager_registers_wrapped_tool_and_emits_events(tmp_path):
    runtime = FerrymanRuntime(Settings(root_dir=tmp_path))
    manager = ToolManager()
    agent = Agent("test")
    agent.tool = MagicMock()

    manager.register_toolkit(agent, DummyToolkit)
    registered_tool = agent.tool.call_args[0][0]

    mock_emit = AsyncMock()
    ctx = SimpleNamespace(
        deps=runtime.create_agent_deps(session_id="sess", emit_event_cb=mock_emit),
    )

    result = await registered_tool(ctx, arg1="ok")
    payload = parse_tool_return(result)

    assert payload["status"] == "success"
    assert payload["tool_name"] == "dummy_tool"
    assert payload["data"] == "Processed ok"
    assert mock_emit.call_args_list[0][0][0].payload.phase == ToolPhase.START
    assert mock_emit.call_args_list[0][0][0].payload.input == {"arg1": "ok"}
    assert mock_emit.call_args_list[1][0][0].payload.phase == ToolPhase.COMPLETE


@pytest.mark.asyncio
async def test_tool_manager_soft_fails_model_retry_on_last_attempt(tmp_path):
    runtime = FerrymanRuntime(Settings(root_dir=tmp_path))
    manager = ToolManager()
    agent = Agent("test")
    agent.tool = MagicMock()

    manager.register_toolkit(agent, RetryToolkit)
    registered_tool = agent.tool.call_args[0][0]
    ctx = SimpleNamespace(
        deps=runtime.create_agent_deps(session_id="sess", emit_event_cb=AsyncMock()),
        last_attempt=True,
    )

    result = await registered_tool(ctx)
    payload = parse_tool_return(result)

    assert payload["status"] == "error"
    assert payload["tool_name"] == "retry_tool"
    assert payload["error"]["type"] == "model_retry_exhausted"
