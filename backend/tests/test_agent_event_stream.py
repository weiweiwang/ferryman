from unittest.mock import AsyncMock

import pytest
from pydantic_ai import FunctionToolCallEvent, FunctionToolResultEvent
from pydantic_ai.messages import RetryPromptPart, ToolCallPart

from app.core.agent_event_stream import emit_agent_stream_event
from app.core.config import Settings
from app.core.runtime import FerrymanRuntime
from app.models.events import ToolPhase


@pytest.mark.asyncio
async def test_agent_event_stream_emits_retry_prompt_error_output(tmp_path):
    runtime = FerrymanRuntime(Settings(root_dir=tmp_path))
    mock_emit = AsyncMock()
    deps = runtime.create_agent_deps(
        session_id="s-retry-event",
        run_id="run-retry-event",
        emit_event_cb=mock_emit,
    )
    tool_start_times: dict[str, float] = {}

    await emit_agent_stream_event(
        deps,
        FunctionToolCallEvent(
            part=ToolCallPart(
                tool_name="run_skill_script",
                args={"script_name": "missing.py"},
                tool_call_id="call-retry",
            )
        ),
        tool_start_times=tool_start_times,
    )
    await emit_agent_stream_event(
        deps,
        FunctionToolResultEvent(
            RetryPromptPart(
                "Script not found: missing.py",
                tool_name="run_skill_script",
                tool_call_id="call-retry",
            )
        ),
        tool_start_times=tool_start_times,
    )

    assert mock_emit.await_count == 2
    error_event = mock_emit.await_args_list[1].args[0]
    assert error_event.payload.run_id == "run-retry-event"
    assert error_event.payload.tool_name == "run_skill_script"
    assert error_event.payload.phase == ToolPhase.ERROR
    assert error_event.payload.output == "Script not found: missing.py"
    assert error_event.payload.duration_ms is not None
