import pytest
import asyncio
import logging
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from pydantic_ai.models.function import FunctionModel
from pydantic_ai.messages import ModelResponse, ToolCallPart, TextPart
from pydantic_ai import Agent
from pydantic_ai.usage import RunUsage

from app.core.config import Settings
from app.core.kernel import FerrymanKernel
from app.core.deps import AgentDeps
from app.core.toolkits.skill import SkillToolkit
from app.models.events import FerrymanEventEnvelope, EventNamespace, ToolPhase, ToolActivityPayload
from app.models.schemas import Usage


logger = logging.getLogger(__name__)

TEST_ROOT = Path("/tmp/ferryman_execution_test")
TEST_USER_SKILLS = TEST_ROOT / "user" / "skills"
TEST_BUNDLED_SKILLS = TEST_ROOT / "bundled" / "skills"


@pytest.fixture(autouse=True)
def setup_test_environment(monkeypatch):
    if TEST_ROOT.exists():
        shutil.rmtree(TEST_ROOT)

    TEST_USER_SKILLS.mkdir(parents=True, exist_ok=True)
    TEST_BUNDLED_SKILLS.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FERRYMAN_BUNDLED_SKILLS_DIR", str(TEST_BUNDLED_SKILLS))

    yield

    if TEST_ROOT.exists():
        shutil.rmtree(TEST_ROOT)


def create_test_settings() -> Settings:
    return Settings(root_dir=TEST_ROOT)


def create_mock_skill(name: str, desc: str, directory: Path):
    skill_dir = directory / name
    skill_dir.mkdir(parents=True)
    skill_md = skill_dir / "SKILL.md"
    content = f"""---
name: {name}
description: {desc}
version: 1.0.0
---
# Mock SOP
"""
    skill_md.write_text(content, encoding="utf-8")


# --- test_agent_closure.py ---
@pytest.mark.asyncio
async def test_agent_execution_closure(monkeypatch):
    """
    Verifies the full 'Closure' of a MasterAgent instruction using FunctionModel to simulate turns.
    """
    mock_settings = create_test_settings()
    kernel = FerrymanKernel(settings=mock_settings)
    
    from pydantic_ai.models.gemini import GeminiModel
    from pydantic_ai.models.openai import OpenAIModel
    from pydantic_ai.models.anthropic import AnthropicModel
    monkeypatch.setattr("pydantic_ai.models.gemini.GeminiModel.__init__", lambda *args, **kwargs: None)
    monkeypatch.setattr("pydantic_ai.models.openai.OpenAIModel.__init__", lambda *args, **kwargs: None)
    monkeypatch.setattr("pydantic_ai.models.anthropic.AnthropicModel.__init__", lambda *args, **kwargs: None)
    
    async def mock_agent_logic(messages, info):
        if len(messages) <= 1:
            return ModelResponse(parts=[
                ToolCallPart(tool_name="list_files", args={"directory": "."}, tool_call_id="call_001")
            ])
        else:
            return ModelResponse(parts=[
                TextPart(content="I see the following files: mock_file.txt. Execution completed successfully. OK.")
            ])

    mock_model = FunctionModel(mock_agent_logic)
    
    def mock_get_master_agent(session_id: str):
        return Agent(model=mock_model, system_prompt="You are a test agent.")
        
    monkeypatch.setattr(kernel, "_get_master_agent", mock_get_master_agent)

    result = await kernel.run_master_agent("Help me list files", session_id="test_session")
    
    payload_messages = result.get("payload", {}).get("messages", [])
    assert len(payload_messages) > 0, "Agent failed to return messages"
    
    response_content = payload_messages[-1].get("content", "")
    assert "successfully" in response_content
    assert "OK" in response_content


# --- test_kernel.py (Execution Flow Mocked) ---
@pytest.mark.asyncio
async def test_run_master_agent_mocked(monkeypatch):
    """
    Test Master Agent execution flow with completely mocked result.
    """
    class MockUsage:
        def __init__(self):
            self.input_tokens = 10
            self.output_tokens = 20
            self.total_tokens = 30
            
    class MockMessage:
        def __init__(self, content):
            self.content = content
            
    class MockResponse(MockMessage):
        pass

    class MockResult:
        def __init__(self, data):
            self.data = data
            self.output = data
            
        def usage(self):
            return MockUsage()
            
        def new_messages(self):
            return [MockResponse(self.data)]

    class MockAgent:
        async def run(self, instruction, deps=None, message_history=None, usage_limits=None):
            return MockResult("Master Agent executed: " + instruction)

    def mock_get_master_agent(session_id: str):
        return MockAgent()

    kernel = FerrymanKernel(create_test_settings())
    monkeypatch.setattr(kernel, "_get_master_agent", mock_get_master_agent)
    
    response = await kernel.run_master_agent("Please list files", "test-session")
    
    assert "Please list files" in response["payload"]["messages"][0]["content"]


# --- test_prompt_and_usage_limits.py ---
def test_runtime_context_moves_to_user_prompt():
    kernel = FerrymanKernel(create_test_settings())
    session_id = "test-session"

    system_prompt = kernel._build_system_prompt(session_id)
    augmented_instruction = kernel.build_runtime_augmented_instruction("Inspect files", session_id)

    assert "Host OS:" not in system_prompt
    assert "Root Dir:" not in system_prompt
    assert "Session Workspace:" not in system_prompt

    assert "Host OS:" in augmented_instruction
    assert "Root Dir:" in augmented_instruction
    assert "Session Workspace:" in augmented_instruction
    assert "Current Date:" in augmented_instruction
    assert "Time Zone:" in augmented_instruction
    assert "Inspect files" in augmented_instruction


@pytest.mark.asyncio
async def test_skill_run_uses_shared_usage_and_request_limit(monkeypatch):
    create_mock_skill("target_skill", "Test skill", TEST_USER_SKILLS)
    kernel = FerrymanKernel(create_test_settings())
    kernel.scan_skills()
    
    def settings_get(key: str, default=None):
        if key == "system.llm.request_limit":
            return 42
        return Settings.get(key, default)

    monkeypatch.setattr(type(kernel._settings), "get", staticmethod(settings_get))

    captured = {}

    class MockSkillResult:
        output = "skill-ok"

        @staticmethod
        def usage():
            return Usage(input_tokens=1, output_tokens=2, total_tokens=3)

    class MockSkillAgent:
        async def run(self, instruction, **kwargs):
            captured["instruction"] = instruction
            captured["kwargs"] = kwargs
            return MockSkillResult()

    monkeypatch.setattr(kernel, "build_skill_agent", lambda skill_name: MockSkillAgent())

    shared_usage = RunUsage()
    ctx = SimpleNamespace(
        deps=AgentDeps(kernel=kernel, session_id="test-session", emit_event_cb=AsyncMock()),
        usage=shared_usage,
    )

    result = await SkillToolkit.run_skill(ctx, "target_skill", "Do the skill work")

    assert result == "skill-ok"
    assert captured["kwargs"]["usage"] is shared_usage
    assert captured["kwargs"]["usage_limits"].request_limit == 42
    assert "Session Workspace:" in captured["instruction"]
    assert "Do the skill work" in captured["instruction"]
    assert captured["kwargs"]["deps"].emit_event_cb is ctx.deps.emit_event_cb


# --- test_agent_events.py ---
@pytest.mark.asyncio
async def test_agent_deps_emit_tool_event():
    mock_cb = AsyncMock()
    
    deps = AgentDeps(
        kernel=None,
        session_id="test-session",
        emit_event_cb=mock_cb
    )

    await deps.emit_tool_event(
        run_id="xyz",
        tool_name="test_tool",
        phase="complete",
        duration_ms=450
    )

    mock_cb.assert_awaited_once()
    event_env: FerrymanEventEnvelope = mock_cb.call_args[0][0]
    
    assert event_env.namespace == EventNamespace.AGENT
    assert event_env.event == "tool_activity"
    assert event_env.session_id == "test-session"
    assert isinstance(event_env.payload, ToolActivityPayload)
    assert event_env.payload.run_id == "xyz"
    assert event_env.payload.tool_name == "test_tool"
    assert event_env.payload.phase == ToolPhase.COMPLETE
    assert event_env.payload.duration_ms == 450


class DummyToolkit:
    @staticmethod
    def get_tools():
        async def dummy_tool(ctx, arg1: str):
            if arg1 == "fail":
                raise ValueError("Intentional error")
            return f"Processed {arg1}"
        return [dummy_tool]


class MultiToolDummyToolkit:
    @staticmethod
    def get_tools():
        async def first_tool(ctx):
            return "first"

        async def second_tool(ctx):
            return "second"

        return [first_tool, second_tool]

@pytest.mark.asyncio
async def test_kernel_register_toolkit_wrapper():
    kernel = FerrymanKernel(settings=create_test_settings())
    agent = Agent('test')
    
    import unittest.mock
    agent.tool = unittest.mock.MagicMock()
    
    kernel._register_toolkit(agent, DummyToolkit)
    registered_tool = agent.tool.call_args[0][0]
    
    mock_emit = AsyncMock()
    deps = AgentDeps(kernel=kernel, session_id="sess", emit_event_cb=mock_emit)

    class MockContext:
        def __init__(self, d):
            self.deps = d
            
    ctx = MockContext(deps)
    
    res = await registered_tool(ctx, arg1="ok")
    assert res == "Processed ok"
    
    assert mock_emit.call_count == 2
    evt_start = mock_emit.call_args_list[0][0][0]
    assert evt_start.payload.phase == ToolPhase.START
    assert evt_start.payload.input == {"arg1": "ok"}
    
    evt_end = mock_emit.call_args_list[1][0][0]
    assert evt_end.payload.phase == ToolPhase.COMPLETE
    assert evt_end.payload.duration_ms is not None
    
    mock_emit.reset_mock()
    with pytest.raises(ValueError):
        await registered_tool(ctx, arg1="fail")
        
    assert mock_emit.call_count == 2
    assert mock_emit.call_args_list[1][0][0].payload.phase == ToolPhase.ERROR


@pytest.mark.asyncio
async def test_kernel_register_toolkit_preserves_each_tool_binding():
    kernel = FerrymanKernel(settings=create_test_settings())
    agent = Agent('test')

    import unittest.mock
    agent.tool = unittest.mock.MagicMock()

    kernel._register_toolkit(agent, MultiToolDummyToolkit)

    first_registered = agent.tool.call_args_list[0][0][0]
    second_registered = agent.tool.call_args_list[1][0][0]

    class MockContext:
        def __init__(self):
            self.deps = AgentDeps(kernel=kernel, session_id="sess")

    ctx = MockContext()

    assert await first_registered(ctx) == "first"
    assert await second_registered(ctx) == "second"
    assert first_registered.__name__ == "first_tool"
    assert second_registered.__name__ == "second_tool"
