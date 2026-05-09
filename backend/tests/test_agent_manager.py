import json
from unittest.mock import AsyncMock

import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import DeltaToolCall
from pydantic_ai.models.function import FunctionModel
from sqlmodel import select

from app.core.config import Settings
from app.core.runtime import FerrymanRuntime
from app.models.database import Message, Session
from app.models.events import ToolPhase
from app.models.schemas import Usage


class MockAgentResult:
    output = "agent-ok"

    @staticmethod
    def usage():
        return Usage(input_tokens=10, output_tokens=20, total_tokens=30)

    @staticmethod
    def new_messages():
        return [ModelResponse(parts=[TextPart(content="agent-ok")])]


class MockAgent:
    def __init__(self):
        self.calls = []

    async def run(self, instruction, **kwargs):
        self.calls.append((instruction, kwargs))
        return MockAgentResult()


class FailingAgent:
    async def run(self, instruction, **kwargs):
        cause = ValueError(
            "1 validation error for send_email\n"
            "attachments\n"
            "  Input should be a valid array [type=list_type, input_type=str]"
        )
        error = RuntimeError("Tool 'send_email' exceeded max retries count of 1")
        raise error from cause


def streaming_function_model(model_logic):
    async def stream_logic(messages, info):
        response = await model_logic(messages, info)
        for index, part in enumerate(response.parts):
            if isinstance(part, ToolCallPart):
                args = part.args if isinstance(part.args, str) else json.dumps(part.args)
                yield {
                    index: DeltaToolCall(
                        name=part.tool_name,
                        json_args=args,
                        tool_call_id=part.tool_call_id,
                    )
                }
            elif isinstance(part, TextPart):
                yield part.content

    return FunctionModel(stream_function=stream_logic)


def test_prompt_builder_builds_runtime_augmented_instruction(tmp_path):
    runtime = FerrymanRuntime(Settings(root_dir=tmp_path))

    instruction = runtime.prompt_builder.build_runtime_augmented_instruction("Build SEO matrix", "s1")

    assert "Runtime Context:" in instruction
    assert "Session Workspace:" in instruction
    assert "Build SEO matrix" in instruction


@pytest.mark.asyncio
async def test_agent_manager_run_master_agent_persists_success(session, tmp_path, monkeypatch):
    runtime = FerrymanRuntime(Settings(root_dir=tmp_path))
    mock_agent = MockAgent()
    monkeypatch.setattr(runtime.agent_manager, "get_master_agent", lambda session_id: mock_agent)
    monkeypatch.setattr(runtime.context_manager, "maybe_compact_session", AsyncMock())

    response = await runtime.agent_manager.run_master_agent(
        "hello",
        "s1",
        run_id="run-agent-success-1",
        deps=runtime.create_agent_deps(session_id="s1", run_id="run-agent-success-1"),
    )

    assert response["payload"]["messages"][0]["content"] == "agent-ok"
    assert response["payload"]["usage"] == {
        "input_tokens": 10,
        "output_tokens": 20,
        "total_tokens": 30,
    }

    db_session = session.get(Session, "s1")
    assert db_session is not None
    assert db_session.input_tokens == 10
    assert db_session.output_tokens == 20

    messages = session.exec(
        select(Message).where(Message.session_id == "s1").order_by(Message.created_at)
    ).all()
    assert [message.role for message in messages] == ["user", "assistant"]
    assert messages[0].metadata_["run"]["id"] == "run-agent-success-1"
    assert messages[1].metadata_["run"]["id"] == "run-agent-success-1"
    assert messages[0].metadata_["run"]["status"] == "success"
    assert messages[1].content == "agent-ok"
    runtime.context_manager.maybe_compact_session.assert_awaited_once_with("s1")
    assert mock_agent.calls
    assert "hello" in mock_agent.calls[0][0]
    assert mock_agent.calls[0][1]["usage_limits"].request_limit == 100


@pytest.mark.asyncio
async def test_agent_manager_run_master_agent_includes_exception_cause(session, tmp_path, monkeypatch):
    runtime = FerrymanRuntime(Settings(root_dir=tmp_path))
    monkeypatch.setattr(runtime.agent_manager, "get_master_agent", lambda session_id: FailingAgent())

    response = await runtime.agent_manager.run_master_agent(
        "send the report",
        "s-cause",
        run_id="run-agent-fail-1",
        deps=runtime.create_agent_deps(session_id="s-cause", run_id="run-agent-fail-1"),
    )

    assistant_message = response["payload"]["messages"][0]
    content = assistant_message["content"]
    assert assistant_message["metadata"]["run"]["status"] == "failed"
    assert "Tool 'send_email' exceeded max retries count of 1" in content
    assert "Cause: 1 validation error for send_email" in content
    assert "attachments" in content
    assert "Input should be a valid array" in content

    messages = session.exec(
        select(Message).where(Message.session_id == "s-cause").order_by(Message.created_at)
    ).all()
    assert messages[-1].metadata_["run"]["status"] == "failed"
    assert "Cause: 1 validation error for send_email" in messages[-1].content


@pytest.mark.asyncio
async def test_agent_manager_continues_after_tool_argument_validation_error(
    session,
    tmp_path,
    monkeypatch,
):
    runtime = FerrymanRuntime(Settings(root_dir=tmp_path))
    call_count = 0

    async def model_logic(messages, info):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return ModelResponse(parts=[
                ToolCallPart(
                    tool_name="send_email",
                    args={
                        "to": ["user@example.com"],
                        "subject": "Report",
                        "text": "See attached.",
                        "attachments": "not-json",
                    },
                    tool_call_id="call_001",
                )
            ])
        return ModelResponse(parts=[
            TextPart(content="The report is ready, but the email was not sent.")
        ])

    monkeypatch.setattr(
        runtime.model_manager,
        "create_active_model",
        lambda: streaming_function_model(model_logic),
    )

    response = await runtime.agent_manager.run_master_agent(
        "send the report",
        "s-validation",
        run_id="run-agent-validation-1",
        deps=runtime.create_agent_deps(session_id="s-validation", run_id="run-agent-validation-1"),
    )

    assistant_message = response["payload"]["messages"][0]
    assert assistant_message["metadata"]["run"]["status"] == "success"
    assert assistant_message["content"] == "The report is ready, but the email was not sent."
    assert call_count == 2

    messages = session.exec(
        select(Message).where(Message.session_id == "s-validation").order_by(Message.created_at)
    ).all()
    assert messages[-1].metadata_["run"]["status"] == "success"
    assert not messages[-1].content.startswith("Run failed:")


@pytest.mark.asyncio
async def test_agent_manager_emits_tool_activity_from_pydantic_event_stream(
    session,
    tmp_path,
    monkeypatch,
):
    runtime = FerrymanRuntime(Settings(root_dir=tmp_path))
    call_count = 0
    mock_emit = AsyncMock()

    async def model_logic(messages, info):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return ModelResponse(parts=[
                ToolCallPart(
                    tool_name="list_files",
                    args={"directory": "."},
                    tool_call_id="call_001",
                )
            ])
        return ModelResponse(parts=[TextPart(content="Listed files.")])

    monkeypatch.setattr(
        runtime.model_manager,
        "create_active_model",
        lambda: streaming_function_model(model_logic),
    )

    response = await runtime.agent_manager.run_master_agent(
        "list files",
        "s-events",
        run_id="run-agent-events-1",
        deps=runtime.create_agent_deps(
            session_id="s-events",
            run_id="run-agent-events-1",
            emit_event_cb=mock_emit,
        ),
    )

    assert response["payload"]["messages"][0]["content"] == "Listed files."
    assert call_count == 2
    assert mock_emit.await_count == 2

    start_event = mock_emit.await_args_list[0].args[0]
    complete_event = mock_emit.await_args_list[1].args[0]
    assert start_event.payload.run_id == "run-agent-events-1"
    assert start_event.payload.tool_name == "list_files"
    assert start_event.payload.phase == ToolPhase.START
    assert start_event.payload.input["path"].endswith("/workspaces/s-events")
    assert complete_event.payload.run_id == "run-agent-events-1"
    assert complete_event.payload.tool_name == "list_files"
    assert complete_event.payload.phase == ToolPhase.COMPLETE
    assert complete_event.payload.duration_ms is not None
    assert complete_event.payload.output
    assert "list_files" in complete_event.payload.output


@pytest.mark.asyncio
async def test_agent_manager_emits_tool_error_from_pydantic_event_stream(
    session,
    tmp_path,
    monkeypatch,
):
    runtime = FerrymanRuntime(Settings(root_dir=tmp_path))
    call_count = 0
    mock_emit = AsyncMock()

    async def model_logic(messages, info):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return ModelResponse(parts=[
                ToolCallPart(
                    tool_name="send_email",
                    args={
                        "to": ["user@example.com"],
                        "subject": "Report",
                        "text": "See attached.",
                        "attachments": "not-json",
                    },
                    tool_call_id="call_001",
                )
            ])
        return ModelResponse(parts=[
            TextPart(content="The email was not sent.")
        ])

    monkeypatch.setattr(
        runtime.model_manager,
        "create_active_model",
        lambda: streaming_function_model(model_logic),
    )

    response = await runtime.agent_manager.run_master_agent(
        "send email",
        "s-event-error",
        run_id="run-agent-events-error-1",
        deps=runtime.create_agent_deps(
            session_id="s-event-error",
            run_id="run-agent-events-error-1",
            emit_event_cb=mock_emit,
        ),
    )

    assert response["payload"]["messages"][0]["content"] == "The email was not sent."
    assert mock_emit.await_count == 2

    start_event = mock_emit.await_args_list[0].args[0]
    error_event = mock_emit.await_args_list[1].args[0]
    assert start_event.payload.phase == ToolPhase.START
    assert start_event.payload.input["text"] == {"_summary": "omitted", "length": 13}
    assert error_event.payload.run_id == "run-agent-events-error-1"
    assert error_event.payload.tool_name == "send_email"
    assert error_event.payload.phase == ToolPhase.ERROR
    assert "attachments" in error_event.payload.output
    assert "valid" in error_event.payload.output
