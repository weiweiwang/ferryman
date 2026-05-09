"""Map PydanticAI stream events into Ferryman agent websocket events."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterable, Callable

from pydantic_ai import AgentStreamEvent, FunctionToolCallEvent, FunctionToolResultEvent
from pydantic_ai.messages import RetryPromptPart, ToolReturnPart

from app.core.deps import AgentDeps
from app.core.tool_activity_payload import build_tool_activity_input, compact_tool_event_text


def build_agent_event_stream_handler(deps: AgentDeps) -> Callable:
    tool_start_times: dict[str, float] = {}

    async def event_stream_handler(ctx, event_stream: AsyncIterable[AgentStreamEvent]) -> None:
        async for event in event_stream:
            await emit_agent_stream_event(
                deps,
                event,
                tool_start_times=tool_start_times,
            )

    return event_stream_handler


async def emit_agent_stream_event(
    deps: AgentDeps,
    event: AgentStreamEvent,
    *,
    tool_start_times: dict[str, float] | None = None,
) -> None:
    if isinstance(event, FunctionToolCallEvent):
        tool_start_times = tool_start_times if tool_start_times is not None else {}
        tool_start_times[event.part.tool_call_id] = time.perf_counter()
        await deps.emit_tool_event(
            run_id=deps.run_id,
            tool_name=event.part.tool_name,
            phase="start",
            input=build_tool_activity_input(
                deps,
                tool_name=event.part.tool_name,
                args=event.part.args,
            ),
        )
        return

    if isinstance(event, FunctionToolResultEvent):
        result = event.result
        tool_name = getattr(result, "tool_name", None)
        if not tool_name:
            return

        kwargs: dict[str, object] = {}
        tool_call_id = getattr(result, "tool_call_id", None)
        if tool_call_id and tool_start_times is not None:
            started_at = tool_start_times.pop(tool_call_id, None)
            if started_at is not None:
                kwargs["duration_ms"] = int((time.perf_counter() - started_at) * 1000)

        output = _tool_result_output(result)
        if output is not None:
            kwargs["output"] = output

        await deps.emit_tool_event(
            run_id=deps.run_id,
            tool_name=tool_name,
            phase=_tool_result_phase(result),
            **kwargs,
        )


def _tool_result_phase(result: ToolReturnPart | RetryPromptPart) -> str:
    if isinstance(result, RetryPromptPart):
        return "error"

    payload = _parse_tool_return_content(result.content)
    if isinstance(payload, dict) and payload.get("status") == "error":
        return "error"

    return "complete"


def _tool_result_output(result: ToolReturnPart | RetryPromptPart) -> str | None:
    if isinstance(result, RetryPromptPart):
        return compact_tool_event_text(result.content)

    payload = _parse_tool_return_content(result.content)
    if isinstance(payload, dict):
        status = payload.get("status")
        error = payload.get("error")
        data = payload.get("data")
        summary = payload.get("summary")

        if status == "error":
            error_message = (
                error.get("message")
                if isinstance(error, dict)
                else str(error)
                if error
                else None
            )
            if error_message and error_message not in {"Tool reported failure."}:
                return compact_tool_event_text(error_message)
            return (
                compact_tool_event_text(data)
                or compact_tool_event_text(error_message)
                or compact_tool_event_text(summary)
            )

        return compact_tool_event_text(data) or compact_tool_event_text(summary)

    return compact_tool_event_text(result.content)


def _parse_tool_return_content(content: object) -> object:
    if isinstance(content, str):
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return None
    return None
