import json
import pytest
import asyncio
import logging
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from pydantic_ai.models.function import FunctionModel
from pydantic_ai.messages import (
    BinaryImage,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    ToolCallPart,
    TextPart,
    ToolReturn,
    ToolReturnPart,
)
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.usage import RunUsage
from sqlmodel import select

from app.core.browser import BrowserActionError
from app.core.config import Settings
from app.core.db import get_session
from app.core.kernel import FerrymanKernel, LLMConfigurationError
from app.core.deps import AgentDeps
from app.core.toolkits.skill import SkillToolkit
from app.core.toolkits.web import WebToolkit
from app.models.database import Message, Session
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


def parse_tool_payload(raw: str) -> dict:
    return json.loads(raw)


def assert_success_tool_payload(raw: str, tool_name: str, expected_data):
    payload = parse_tool_payload(raw)
    assert payload["tool_name"] == tool_name
    assert payload["status"] == "success"
    assert payload["error"] is None
    assert payload["data"] == expected_data
    return payload


def assert_error_tool_payload(
    raw: str,
    tool_name: str,
    *,
    error_type: str,
    message: str,
):
    payload = parse_tool_payload(raw)
    assert payload["tool_name"] == tool_name
    assert payload["status"] == "error"
    assert payload["data"] is None
    assert payload["error"] == {
        "type": error_type,
        "message": message,
        "retryable": False,
    }
    return payload


def test_init_llm_model_uses_openai_provider_for_kimi(monkeypatch):
    settings = create_test_settings()
    monkeypatch.setattr(Settings, "get_active_model_id", lambda self: "kimi:kimi-k2.5")
    monkeypatch.setattr(Settings, "get_provider_llm_config", lambda self, provider: {"api_key": "sk-test"})

    captured = {}

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs
            captured["client_instance"] = self

    class FakeOpenAIProvider:
        def __init__(self, **kwargs):
            captured["provider_kwargs"] = kwargs

    def fake_openai_chat_model(model_name, provider):
        captured["model_name"] = model_name
        captured["provider"] = provider
        return "kimi-model"

    monkeypatch.setattr("openai.AsyncOpenAI", FakeAsyncOpenAI)
    monkeypatch.setattr("pydantic_ai.models.openai.OpenAIChatModel", fake_openai_chat_model)
    monkeypatch.setattr("pydantic_ai.providers.openai.OpenAIProvider", FakeOpenAIProvider)

    kernel = FerrymanKernel(settings=settings)

    assert kernel._init_llm_model() == "kimi-model"
    assert captured["model_name"] == "kimi-k2.5"
    assert isinstance(captured["provider"], FakeOpenAIProvider)
    assert captured["client_kwargs"] == {
        "api_key": "sk-test",
        "base_url": "https://api.moonshot.cn/v1",
    }
    assert captured["provider_kwargs"] == {"openai_client": captured["client_instance"]}


def test_init_llm_model_supports_custom_kimi_base_url(monkeypatch):
    settings = create_test_settings()
    monkeypatch.setattr(Settings, "get_active_model_id", lambda self: "kimi:kimi-k2.5")
    monkeypatch.setattr(
        Settings,
        "get_provider_llm_config",
        lambda self, provider: {"api_key": "sk-test", "base_url": "https://proxy.example.com/v1"},
    )

    captured = {}

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs
            captured["client_instance"] = self

    class FakeOpenAIProvider:
        def __init__(self, **kwargs):
            captured["provider_kwargs"] = kwargs

    def fake_openai_chat_model(model_name, provider):
        captured["model_name"] = model_name
        captured["provider"] = provider
        return "kimi-model"

    monkeypatch.setattr("openai.AsyncOpenAI", FakeAsyncOpenAI)
    monkeypatch.setattr("pydantic_ai.models.openai.OpenAIChatModel", fake_openai_chat_model)
    monkeypatch.setattr("pydantic_ai.providers.openai.OpenAIProvider", FakeOpenAIProvider)

    kernel = FerrymanKernel(settings=settings)

    assert kernel._init_llm_model() == "kimi-model"
    assert captured["client_kwargs"] == {
        "api_key": "sk-test",
        "base_url": "https://proxy.example.com/v1",
    }
    assert captured["provider_kwargs"] == {"openai_client": captured["client_instance"]}


def test_init_llm_model_uses_openai_provider_for_doubao(monkeypatch):
    settings = create_test_settings()
    monkeypatch.setattr(Settings, "get_active_model_id", lambda self: "doubao:doubao-seed-2-0-pro-260215")
    monkeypatch.setattr(Settings, "get_provider_llm_config", lambda self, provider: {"api_key": "sk-test"})

    captured = {}

    class FakeOpenAIProvider:
        def __init__(self, **kwargs):
            captured["provider_kwargs"] = kwargs

    def fake_openai_chat_model(model_name, provider):
        captured["model_name"] = model_name
        captured["provider"] = provider
        return "doubao-model"

    monkeypatch.setattr("pydantic_ai.models.openai.OpenAIChatModel", fake_openai_chat_model)
    monkeypatch.setattr("pydantic_ai.providers.openai.OpenAIProvider", FakeOpenAIProvider)

    kernel = FerrymanKernel(settings=settings)

    assert kernel._init_llm_model() == "doubao-model"
    assert captured["model_name"] == "doubao-seed-2-0-pro-260215"
    assert isinstance(captured["provider"], FakeOpenAIProvider)
    assert captured["provider_kwargs"] == {
        "api_key": "sk-test",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
    }


def test_init_llm_model_strips_trailing_v1_for_anthropic(monkeypatch):
    settings = create_test_settings()
    monkeypatch.setattr(Settings, "get_active_model_id", lambda self: "anthropic:claude-haiku-4-5-20251001")
    monkeypatch.setattr(
        Settings,
        "get_provider_llm_config",
        lambda self, provider: {
            "api_key": "sk-test",
            "base_url": "https://cc.honoursoft.cn/v1",
        },
    )

    captured = {}

    class FakeAnthropicProvider:
        def __init__(self, **kwargs):
            captured["provider_kwargs"] = kwargs

    def fake_anthropic_model(model_name, provider):
        captured["model_name"] = model_name
        captured["provider"] = provider
        return "anthropic-model"

    monkeypatch.setattr("pydantic_ai.models.anthropic.AnthropicModel", fake_anthropic_model)
    monkeypatch.setattr("pydantic_ai.providers.anthropic.AnthropicProvider", FakeAnthropicProvider)

    kernel = FerrymanKernel(settings=settings)

    assert kernel._init_llm_model() == "anthropic-model"
    assert captured["model_name"] == "claude-haiku-4-5-20251001"
    assert isinstance(captured["provider"], FakeAnthropicProvider)
    assert captured["provider_kwargs"] == {
        "api_key": "sk-test",
        "base_url": "https://cc.honoursoft.cn",
    }


def test_init_llm_model_raises_clear_error_when_gemini_api_key_missing(monkeypatch):
    settings = create_test_settings()
    monkeypatch.setattr(Settings, "get_active_model_id", lambda self: "gemini:gemini-3-flash-preview")
    monkeypatch.setattr(Settings, "get_provider_llm_config", lambda self, provider: {})

    kernel = FerrymanKernel(settings=settings)

    with pytest.raises(LLMConfigurationError, match="missing API Key"):
        kernel._init_llm_model()


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


@pytest.mark.asyncio
async def test_master_agent_can_recover_from_soft_failed_run_skill(monkeypatch):
    create_mock_skill("target_skill", "Test skill", TEST_USER_SKILLS)
    kernel = FerrymanKernel(settings=create_test_settings())
    kernel.scan_skills()

    from pydantic_ai.models.gemini import GeminiModel
    from pydantic_ai.models.openai import OpenAIModel
    from pydantic_ai.models.anthropic import AnthropicModel
    monkeypatch.setattr("pydantic_ai.models.gemini.GeminiModel.__init__", lambda *args, **kwargs: None)
    monkeypatch.setattr("pydantic_ai.models.openai.OpenAIModel.__init__", lambda *args, **kwargs: None)
    monkeypatch.setattr("pydantic_ai.models.anthropic.AnthropicModel.__init__", lambda *args, **kwargs: None)

    class FailingSkillAgent:
        async def run(self, instruction, **kwargs):
            raise RuntimeError("delegate exploded")

    monkeypatch.setattr(kernel, "build_skill_agent", lambda skill_name: FailingSkillAgent())

    async def mock_agent_logic(messages, info):
        tool_returns = [
            part
            for msg in messages
            for part in getattr(msg, "parts", [])
            if isinstance(part, ToolReturnPart) and part.tool_name == "run_skill"
        ]
        if not tool_returns:
            return ModelResponse(parts=[
                ToolCallPart(
                    tool_name="run_skill",
                    args={"skill_name": "target_skill", "instruction": "Do the skill work"},
                    tool_call_id="call_001",
                )
            ])

        payload = parse_tool_payload(tool_returns[-1].content)
        assert payload["tool_name"] == "run_skill"
        assert payload["status"] == "error"
        assert payload["error"] == {
            "type": "tool_result_error",
            "message": "delegate exploded",
            "retryable": False,
        }
        assert payload["data"]["ok"] is False
        assert payload["data"]["skill_name"] == "target_skill"
        assert payload["data"]["error"] == "delegate exploded"
        return ModelResponse(parts=[
            TextPart(content="Delegated skill failed cleanly, switching strategy.")
        ])

    mock_model = FunctionModel(mock_agent_logic)
    monkeypatch.setattr(kernel, "_init_llm_model", lambda: mock_model)

    result = await kernel.run_master_agent("Use the skill first", session_id="test_session")

    payload_messages = result.get("payload", {}).get("messages", [])
    assert len(payload_messages) > 0, "Agent failed to return messages"
    assert payload_messages[-1]["content"] == "Delegated skill failed cleanly, switching strategy."


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
            
    class MockResult:
        def __init__(self, data):
            self.data = data
            self.output = data
            
        def usage(self):
            return MockUsage()
            
        def new_messages(self):
            return [ModelResponse(parts=[TextPart(content=self.data)])]

    class MockAgent:
        async def run(self, instruction, deps=None, message_history=None, usage_limits=None):
            return MockResult("Master Agent executed: " + instruction)

    def mock_get_master_agent(session_id: str):
        return MockAgent()

    kernel = FerrymanKernel(create_test_settings())
    monkeypatch.setattr(kernel, "_get_master_agent", mock_get_master_agent)
    
    response = await kernel.run_master_agent("Please list files", "test-session")
    
    assert "Please list files" in response["payload"]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_run_master_agent_history_keeps_system_prompt_and_token_estimates(monkeypatch):
    captured = {}

    class MockUsage:
        input_tokens = 10
        output_tokens = 20
        total_tokens = 30

    class MockResult:
        output = "done"

        @staticmethod
        def usage():
            return MockUsage()

        @staticmethod
        def new_messages():
            return [ModelResponse(parts=[TextPart(content="done")])]

    class MockAgent:
        async def run(self, instruction, deps=None, message_history=None, usage_limits=None):
            captured["instruction"] = instruction
            captured["message_history"] = message_history
            return MockResult()

    kernel = FerrymanKernel(create_test_settings())
    monkeypatch.setattr(kernel, "_get_master_agent", lambda session_id: MockAgent())

    await kernel.run_master_agent("Please list files", "test-session")

    history = captured["message_history"]
    assert isinstance(history[0], ModelRequest)
    assert isinstance(history[0].parts[0], SystemPromptPart)
    assert "You are a personal assistant running inside **Ferryman**." in history[0].parts[0].content

    with get_session() as db_session:
        messages = list(
            db_session.exec(
                select(Message)
                .where(Message.session_id == "test-session")
                .order_by(Message.created_at)  # type: ignore[arg-type]
            ).all()
        )

    assert [message.role for message in messages] == ["user", "assistant"]
    assert messages[0].token_estimate > 0
    assert messages[1].token_estimate > 0


def test_get_session_messages_includes_summary_and_only_tail_messages():
    kernel = FerrymanKernel(create_test_settings())
    session_id = "session-with-summary"
    cutoff = datetime(2026, 4, 16, 12, 0, tzinfo=timezone.utc)

    with get_session() as db_session:
        db_session.add(
            Session(
                id=session_id,
                title="",
                memory={
                    "schema_version": 1,
                    "compaction": {
                        "summary": "compressed history",
                        "cutoff_created_at": "2026-04-16T12:00:00Z",
                        "updated_at": "2026-04-16T12:05:00Z",
                    },
                },
            )
        )
        db_session.add(
            Message(
                session_id=session_id,
                role="user",
                content="old user",
                type="text",
                token_estimate=5,
                created_at=cutoff - timedelta(minutes=2),
            )
        )
        db_session.add(
            Message(
                session_id=session_id,
                role="assistant",
                content="old assistant",
                type="text",
                token_estimate=5,
                created_at=cutoff - timedelta(minutes=1),
            )
        )
        db_session.add(
            Message(
                session_id=session_id,
                role="user",
                content="new user",
                type="text",
                token_estimate=5,
                created_at=cutoff + timedelta(minutes=1),
            )
        )
        db_session.add(
            Message(
                session_id=session_id,
                role="assistant",
                content="new assistant",
                type="text",
                token_estimate=5,
                created_at=cutoff + timedelta(minutes=2),
            )
        )
        db_session.commit()

    history = kernel._get_session_messages(session_id)

    assert isinstance(history[0], ModelRequest)
    assert isinstance(history[0].parts[0], SystemPromptPart)
    assert isinstance(history[1], ModelResponse)
    assert isinstance(history[1].parts[0], TextPart)
    assert "[CONTEXT COMPACTION" in history[1].parts[0].content
    assert "compressed history" in history[1].parts[0].content

    rendered_tail = [
        message.parts[0].content
        for message in history[2:]
    ]
    assert rendered_tail == ["new user", "new assistant"]


def test_get_session_messages_respects_microsecond_cutoff():
    kernel = FerrymanKernel(create_test_settings())
    session_id = "session-with-microsecond-cutoff"
    cutoff = datetime(2026, 4, 16, 12, 0, 0, 123456, tzinfo=timezone.utc)

    with get_session() as db_session:
        db_session.add(
            Session(
                id=session_id,
                title="",
                memory={
                    "schema_version": 1,
                    "compaction": {
                        "summary": "compressed history",
                        "cutoff_created_at": kernel._format_utc_timestamp(cutoff),
                        "updated_at": "2026-04-16T12:05:00Z",
                    },
                },
            )
        )
        db_session.add(
            Message(
                session_id=session_id,
                role="assistant",
                content="already compacted",
                type="text",
                token_estimate=5,
                created_at=cutoff,
            )
        )
        db_session.add(
            Message(
                session_id=session_id,
                role="user",
                content="same-second new user",
                type="text",
                token_estimate=5,
                created_at=cutoff + timedelta(microseconds=1),
            )
        )
        db_session.commit()

    history = kernel._get_session_messages(session_id)

    rendered_tail = [message.parts[0].content for message in history[2:]]
    assert rendered_tail == ["same-second new user"]


@pytest.mark.asyncio
async def test_run_master_agent_compacts_after_current_turn(monkeypatch):
    captured = {}
    session_id = "compaction-session"
    first_turn_time = datetime(2026, 4, 16, 12, 2, tzinfo=timezone.utc)

    class MasterUsage:
        input_tokens = 11
        output_tokens = 12
        total_tokens = 23

    class MasterResult:
        output = "post-compaction reply"

        @staticmethod
        def usage():
            return MasterUsage()

        @staticmethod
        def new_messages():
            return [ModelResponse(parts=[TextPart(content="post-compaction reply")])]

    class MasterAgent:
        async def run(self, instruction, deps=None, message_history=None, usage_limits=None):
            captured["message_history"] = message_history
            return MasterResult()

    class CompactionUsage:
        input_tokens = 3
        output_tokens = 4
        total_tokens = 7

    class CompactionResult:
        output = "## Current Goal\nkeep going\n## Completed\nold work\n## Current State\nstate\n## Unresolved Issues\nnone\n## Pending Work\nnext\n## Exact Identifiers\nid\n## User Preferences and Constraints\npref"

        @staticmethod
        def usage():
            return CompactionUsage()

    class CompactionAgent:
        async def run(self, instruction):
            captured["compaction_input"] = instruction
            return CompactionResult()

    kernel = FerrymanKernel(create_test_settings())
    monkeypatch.setattr(kernel, "_get_master_agent", lambda current_session_id: MasterAgent())
    monkeypatch.setattr(kernel, "_get_compaction_agent", lambda: CompactionAgent())
    monkeypatch.setattr(
        kernel,
        "get_setting",
        lambda key, default=None: 10 if key == "system.llm.compaction_threshold_tokens" else default,
    )

    with get_session() as db_session:
        db_session.add(Session(id=session_id, title=""))
        db_session.add(
            Message(
                session_id=session_id,
                role="user",
                content="first user",
                type="text",
                token_estimate=6,
                created_at=first_turn_time - timedelta(minutes=2),
            )
        )
        db_session.add(
            Message(
                session_id=session_id,
                role="assistant",
                content="first assistant",
                type="text",
                token_estimate=6,
                created_at=first_turn_time,
            )
        )
        db_session.commit()

    await kernel.run_master_agent("follow-up", session_id)

    history = captured["message_history"]
    rendered_history = [message.parts[0].content for message in history[1:]]
    assert rendered_history == ["first user", "first assistant"]
    assert "follow-up" in captured["compaction_input"]
    assert "post-compaction reply" in captured["compaction_input"]

    with get_session() as db_session:
        session_obj = db_session.get(Session, session_id)
        assert session_obj is not None
        assert session_obj.memory["compaction"]["summary"].startswith("## Current Goal")
        assert session_obj.memory["compaction"]["cutoff_created_at"] is not None
        assert "guard_until" not in session_obj.memory["compaction"]


@pytest.mark.asyncio
async def test_run_master_agent_skips_failed_compaction_and_sets_guard(monkeypatch):
    captured = {"compaction_calls": 0}
    session_id = "compaction-failure-session"

    class MasterUsage:
        input_tokens = 5
        output_tokens = 7
        total_tokens = 12

    class MasterResult:
        output = "normal reply"

        @staticmethod
        def usage():
            return MasterUsage()

        @staticmethod
        def new_messages():
            return [ModelResponse(parts=[TextPart(content="normal reply")])]

    class MasterAgent:
        async def run(self, instruction, deps=None, message_history=None, usage_limits=None):
            captured["message_history"] = message_history
            return MasterResult()

    class FailingCompactionAgent:
        async def run(self, instruction):
            captured["compaction_calls"] += 1
            raise RuntimeError("compaction backend unavailable")

    kernel = FerrymanKernel(create_test_settings())
    monkeypatch.setattr(kernel, "_get_master_agent", lambda current_session_id: MasterAgent())
    monkeypatch.setattr(kernel, "_get_compaction_agent", lambda: FailingCompactionAgent())
    monkeypatch.setattr(
        kernel,
        "get_setting",
        lambda key, default=None: (
            10 if key == "system.llm.compaction_threshold_tokens"
            else 60 if key == "system.llm.compaction_guard_seconds"
            else default
        ),
    )

    with get_session() as db_session:
        db_session.add(Session(id=session_id, title=""))
        db_session.add(
            Message(
                session_id=session_id,
                role="user",
                content="older user",
                type="text",
                token_estimate=6,
                created_at=datetime(2026, 4, 16, 12, 0, tzinfo=timezone.utc),
            )
        )
        db_session.add(
            Message(
                session_id=session_id,
                role="assistant",
                content="older assistant",
                type="text",
                token_estimate=6,
                created_at=datetime(2026, 4, 16, 12, 1, tzinfo=timezone.utc),
            )
        )
        db_session.commit()

    response = await kernel.run_master_agent("fresh request", session_id)

    assert response["payload"]["messages"][0]["content"] == "normal reply"
    assert captured["compaction_calls"] == 1

    await kernel._maybe_compact_session(session_id)
    assert captured["compaction_calls"] == 1

    with get_session() as db_session:
        session_obj = db_session.get(Session, session_id)
        assert session_obj is not None
        assert session_obj.memory["compaction"]["guard_until"] is not None
        assert "summary" not in session_obj.memory["compaction"]

        messages = list(
            db_session.exec(
                select(Message)
                .where(Message.session_id == session_id)
                .order_by(Message.created_at)  # type: ignore[arg-type]
            ).all()
        )

    assert set(message.content for message in messages) == {
        "older user",
        "older assistant",
        "fresh request",
        "normal reply",
    }
    assert not any(message.content.startswith("Run failed:") for message in messages)


@pytest.mark.asyncio
async def test_run_master_agent_backfills_legacy_zero_token_estimates_for_compaction(monkeypatch):
    captured = {"compaction_calls": 0}
    session_id = "compaction-legacy-zero-estimates"

    class MasterUsage:
        input_tokens = 5
        output_tokens = 5
        total_tokens = 10

    class MasterResult:
        output = "ok"

        @staticmethod
        def usage():
            return MasterUsage()

        @staticmethod
        def new_messages():
            return [ModelResponse(parts=[TextPart(content="ok")])]

    class MasterAgent:
        async def run(self, instruction, deps=None, message_history=None, usage_limits=None):
            return MasterResult()

    class CompactionUsage:
        input_tokens = 2
        output_tokens = 3
        total_tokens = 5

    class CompactionResult:
        output = "## Current Goal\ncontinue\n## Completed\nlegacy\n## Current State\nstate\n## Unresolved Issues\nnone\n## Pending Work\nnext\n## Exact Identifiers\nid\n## User Preferences and Constraints\npref"

        @staticmethod
        def usage():
            return CompactionUsage()

    class CompactionAgent:
        async def run(self, instruction):
            captured["compaction_calls"] += 1
            return CompactionResult()

    kernel = FerrymanKernel(create_test_settings())
    monkeypatch.setattr(kernel, "_get_master_agent", lambda current_session_id: MasterAgent())
    monkeypatch.setattr(kernel, "_get_compaction_agent", lambda: CompactionAgent())
    monkeypatch.setattr(
        kernel,
        "get_setting",
        lambda key, default=None: 20 if key == "system.llm.compaction_threshold_tokens" else default,
    )

    with get_session() as db_session:
        db_session.add(Session(id=session_id, title=""))
        db_session.add(
            Message(
                session_id=session_id,
                role="user",
                content="legacy user message " * 8,
                type="text",
                token_estimate=0,
                created_at=datetime(2026, 4, 16, 12, 0, tzinfo=timezone.utc),
            )
        )
        db_session.add(
            Message(
                session_id=session_id,
                role="assistant",
                content="legacy assistant message " * 8,
                type="text",
                token_estimate=0,
                created_at=datetime(2026, 4, 16, 12, 1, tzinfo=timezone.utc),
            )
        )
        db_session.commit()

    await kernel.run_master_agent("hi", session_id)

    assert captured["compaction_calls"] == 1

    with get_session() as db_session:
        legacy_messages = list(
            db_session.exec(
                select(Message)
                .where(Message.session_id == session_id)
                .where(Message.content.like("legacy%"))
                .order_by(Message.created_at)  # type: ignore[arg-type]
            ).all()
        )
        session_obj = db_session.get(Session, session_id)

    assert [message.token_estimate for message in legacy_messages] == sorted(
        [message.token_estimate for message in legacy_messages]
    )
    assert all(message.token_estimate > 0 for message in legacy_messages)
    assert session_obj is not None
    assert session_obj.memory["compaction"]["summary"].startswith("## Current Goal")


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


@pytest.mark.asyncio
async def test_skill_run_missing_skill_requests_retry():
    kernel = FerrymanKernel(create_test_settings())
    ctx = SimpleNamespace(
        deps=AgentDeps(kernel=kernel, session_id="test-session", emit_event_cb=AsyncMock()),
        usage=RunUsage(),
    )

    with pytest.raises(ModelRetry, match="Skill 'missing-skill' not found."):
        await SkillToolkit.run_skill(ctx, "missing-skill", "Do the skill work")


@pytest.mark.asyncio
async def test_skill_run_returns_soft_failure_payload_when_delegate_fails(monkeypatch):
    create_mock_skill("target_skill", "Test skill", TEST_USER_SKILLS)
    kernel = FerrymanKernel(create_test_settings())
    kernel.scan_skills()

    class MockSkillAgent:
        async def run(self, instruction, **kwargs):
            raise RuntimeError("delegate exploded")

    monkeypatch.setattr(kernel, "build_skill_agent", lambda skill_name: MockSkillAgent())

    ctx = SimpleNamespace(
        deps=AgentDeps(kernel=kernel, session_id="test-session", emit_event_cb=AsyncMock()),
        usage=RunUsage(),
    )

    result = await SkillToolkit.run_skill(ctx, "target_skill", "Do the skill work")

    assert result == {
        "ok": False,
        "skill_name": "target_skill",
        "error": "delegate exploded",
    }


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
    assert isinstance(event_env.payload.event_id, str)
    assert event_env.payload.event_id
    assert event_env.payload.seq == 1
    assert event_env.payload.tool_name == "test_tool"
    assert event_env.payload.phase == ToolPhase.COMPLETE
    assert event_env.payload.duration_ms == 450


@pytest.mark.asyncio
async def test_agent_deps_emit_tool_event_increments_seq():
    mock_cb = AsyncMock()

    deps = AgentDeps(
        kernel=None,
        session_id="test-session",
        emit_event_cb=mock_cb
    )

    await deps.emit_tool_event(run_id="xyz", tool_name="first_tool", phase="start")
    await deps.emit_tool_event(run_id="xyz", tool_name="second_tool", phase="complete")

    first_event: FerrymanEventEnvelope = mock_cb.await_args_list[0].args[0]
    second_event: FerrymanEventEnvelope = mock_cb.await_args_list[1].args[0]

    assert first_event.payload.seq == 1
    assert second_event.payload.seq == 2
    assert first_event.payload.event_id != second_event.payload.event_id


class DummyToolkit:
    @staticmethod
    def get_tools():
        async def dummy_tool(ctx, arg1: str):
            if arg1 == "fail":
                raise ValueError("Intentional error")
            if arg1 == "json-text":
                return '{"alpha": 1}'
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


class FileSummaryDummyToolkit:
    @staticmethod
    def get_tools():
        async def write_file(ctx, file_path: str, content: str):
            return f"Wrote {file_path} ({len(content)})"

        return [write_file]


class SoftFailBrowserToolkit:
    @staticmethod
    def get_tools():
        async def browser_navigate(ctx):
            raise BrowserActionError("Failed to navigate: boom")

        return [browser_navigate]


class HardFailBrowserToolkit:
    @staticmethod
    def get_tools():
        async def browser_screenshot(ctx):
            raise BrowserActionError("Failed to take screenshot: boom")

        return [browser_screenshot]


class RetryDummyToolkit:
    @staticmethod
    def get_tools():
        async def retry_tool(ctx):
            raise ModelRetry("bad arguments")

        return [retry_tool]


class ImageDummyToolkit:
    @staticmethod
    def get_tools():
        async def browser_screenshot(ctx):
            return BinaryImage(b"img-bytes", media_type="image/png", identifier="shot-1")

        return [browser_screenshot]

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
    assert_success_tool_payload(res, "dummy_tool", "Processed ok")
    
    assert mock_emit.call_count == 2
    evt_start = mock_emit.call_args_list[0][0][0]
    assert evt_start.payload.phase == ToolPhase.START
    assert evt_start.payload.input == {"arg1": "ok"}
    
    evt_end = mock_emit.call_args_list[1][0][0]
    assert evt_end.payload.phase == ToolPhase.COMPLETE
    assert evt_end.payload.duration_ms is not None
    
    mock_emit.reset_mock()
    error_res = await registered_tool(ctx, arg1="fail")
    assert_error_tool_payload(
        error_res,
        "dummy_tool",
        error_type="ValueError",
        message="Intentional error",
    )

    assert mock_emit.call_count == 2
    assert mock_emit.call_args_list[1][0][0].payload.phase == ToolPhase.ERROR

    json_text_res = await registered_tool(ctx, arg1="json-text")
    assert_success_tool_payload(json_text_res, "dummy_tool", '{"alpha": 1}')


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

    assert_success_tool_payload(await first_registered(ctx), "first_tool", "first")
    assert_success_tool_payload(await second_registered(ctx), "second_tool", "second")
    assert first_registered.__name__ == "first_tool"
    assert second_registered.__name__ == "second_tool"


@pytest.mark.asyncio
async def test_kernel_register_toolkit_preserves_file_path_when_input_is_large():
    kernel = FerrymanKernel(settings=create_test_settings())
    agent = Agent('test')

    import unittest.mock
    agent.tool = unittest.mock.MagicMock()

    kernel._register_toolkit(agent, FileSummaryDummyToolkit)
    registered_tool = agent.tool.call_args[0][0]

    mock_emit = AsyncMock()
    deps = AgentDeps(kernel=kernel, session_id="sess", emit_event_cb=mock_emit)

    class MockContext:
        def __init__(self, d):
            self.deps = d

    ctx = MockContext(deps)

    long_content = "A" * 5000
    res = await registered_tool(ctx, "reports/output.md", long_content)
    assert_success_tool_payload(res, "write_file", "Wrote reports/output.md (5000)")
    evt_start = mock_emit.call_args_list[0][0][0]
    assert evt_start.payload.phase == ToolPhase.START
    assert evt_start.payload.input["path"].endswith("/workspaces/sess/reports/output.md")
    assert evt_start.payload.input["content"] == {"_summary": "omitted", "length": 5000}


@pytest.mark.asyncio
async def test_kernel_register_toolkit_retries_browser_action_error_before_last_attempt():
    kernel = FerrymanKernel(settings=create_test_settings())
    agent = Agent('test')

    import unittest.mock
    agent.tool = unittest.mock.MagicMock()

    kernel._register_toolkit(agent, SoftFailBrowserToolkit)
    registered_tool = agent.tool.call_args[0][0]

    mock_emit = AsyncMock()
    deps = AgentDeps(kernel=kernel, session_id="sess", emit_event_cb=mock_emit)

    class MockContext:
        def __init__(self, d):
            self.deps = d
            self.last_attempt = False

    ctx = MockContext(deps)

    with pytest.raises(ModelRetry, match="Failed to navigate: boom"):
        await registered_tool(ctx)

    assert mock_emit.call_args_list[1][0][0].payload.phase == ToolPhase.ERROR


@pytest.mark.asyncio
async def test_kernel_register_toolkit_soft_fails_browser_action_error_on_last_attempt():
    kernel = FerrymanKernel(settings=create_test_settings())
    agent = Agent('test')

    import unittest.mock
    agent.tool = unittest.mock.MagicMock()

    kernel._register_toolkit(agent, SoftFailBrowserToolkit)
    registered_tool = agent.tool.call_args[0][0]

    mock_emit = AsyncMock()
    deps = AgentDeps(kernel=kernel, session_id="sess", emit_event_cb=mock_emit)

    class MockContext:
        def __init__(self, d):
            self.deps = d
            self.last_attempt = True

    ctx = MockContext(deps)

    result = await registered_tool(ctx)

    assert_error_tool_payload(
        result,
        "browser_navigate",
        error_type="browser_action_error",
        message="Failed to navigate: boom",
    )
    assert mock_emit.call_args_list[1][0][0].payload.phase == ToolPhase.ERROR


@pytest.mark.asyncio
async def test_kernel_register_toolkit_soft_fails_browser_screenshot_on_last_attempt():
    kernel = FerrymanKernel(settings=create_test_settings())
    agent = Agent('test')

    import unittest.mock
    agent.tool = unittest.mock.MagicMock()

    kernel._register_toolkit(agent, HardFailBrowserToolkit)
    registered_tool = agent.tool.call_args[0][0]

    mock_emit = AsyncMock()
    deps = AgentDeps(kernel=kernel, session_id="sess", emit_event_cb=mock_emit)

    class MockContext:
        def __init__(self, d):
            self.deps = d
            self.last_attempt = True

    ctx = MockContext(deps)

    result = await registered_tool(ctx)
    assert_error_tool_payload(
        result,
        "browser_screenshot",
        error_type="browser_action_error",
        message="Failed to take screenshot: boom",
    )


@pytest.mark.asyncio
async def test_kernel_register_toolkit_soft_fails_when_browser_boot_fails(monkeypatch):
    kernel = FerrymanKernel(settings=create_test_settings())
    agent = Agent('test')

    import unittest.mock
    agent.tool = unittest.mock.MagicMock()

    kernel._register_toolkit(agent, WebToolkit)
    registered_tool = agent.tool.call_args_list[0][0][0]

    async def mock_get_browser(session_id, headless=None):
        raise RuntimeError("Chrome runtime is unavailable.")

    monkeypatch.setattr(kernel, "get_browser", mock_get_browser)

    mock_emit = AsyncMock()
    deps = AgentDeps(kernel=kernel, session_id="sess", emit_event_cb=mock_emit)

    class MockContext:
        def __init__(self, d):
            self.deps = d
            self.last_attempt = True

    ctx = MockContext(deps)

    result = await registered_tool(ctx, "https://example.com")

    assert_error_tool_payload(
        result,
        "browser_navigate",
        error_type="browser_action_error",
        message="Chrome runtime is unavailable.",
    )


@pytest.mark.asyncio
async def test_kernel_register_toolkit_soft_fails_model_retry_on_last_attempt():
    kernel = FerrymanKernel(settings=create_test_settings())
    agent = Agent('test')

    import unittest.mock
    agent.tool = unittest.mock.MagicMock()

    kernel._register_toolkit(agent, RetryDummyToolkit)
    registered_tool = agent.tool.call_args[0][0]

    mock_emit = AsyncMock()
    deps = AgentDeps(kernel=kernel, session_id="sess", emit_event_cb=mock_emit)

    class MockContext:
        def __init__(self, d):
            self.deps = d
            self.last_attempt = True

    result = await registered_tool(MockContext(deps))
    assert_error_tool_payload(
        result,
        "retry_tool",
        error_type="model_retry_exhausted",
        message="bad arguments",
    )


@pytest.mark.asyncio
async def test_kernel_register_toolkit_wraps_binary_image_with_json_payload():
    kernel = FerrymanKernel(settings=create_test_settings())
    agent = Agent('test')

    import unittest.mock
    agent.tool = unittest.mock.MagicMock()

    kernel._register_toolkit(agent, ImageDummyToolkit)
    registered_tool = agent.tool.call_args[0][0]

    deps = AgentDeps(kernel=kernel, session_id="sess", emit_event_cb=AsyncMock())

    class MockContext:
        def __init__(self, d):
            self.deps = d

    result = await registered_tool(MockContext(deps))

    assert isinstance(result, ToolReturn)
    payload = parse_tool_payload(result.return_value)
    assert payload["tool_name"] == "browser_screenshot"
    assert payload["status"] == "success"
    assert payload["data"] == {
        "kind": "binary_image",
        "media_type": "image/png",
        "identifier": "shot-1",
    }
    assert result.content and isinstance(result.content[0], BinaryImage)
