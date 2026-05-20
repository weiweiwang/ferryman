from __future__ import annotations

import logging

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, SystemPromptPart, TextPart, ToolReturnPart, UserPromptPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RequestUsage

from app.core.config import Settings
from app.core.agent_manager import AgentManager
from app.core.model_manager import LLMConfigurationError, ModelManager
from app.core.model_routing import ModelRouter, ModelUsageTracker, RoutingContext, RoutingModel


def function_model(name: str, text: str, usage: RequestUsage) -> FunctionModel:
    async def model_logic(_messages, _info):
        return ModelResponse(
            parts=[TextPart(content=text)],
            model_name=name,
            usage=usage,
        )

    return FunctionModel(model_logic, model_name=name)


@pytest.mark.asyncio
async def test_routing_model_keeps_agent_usage_to_final_request(tmp_path, monkeypatch, caplog):
    settings = Settings(root_dir=tmp_path)
    settings.set("system.llm.active_model", "openai:gpt-test", category="system")
    settings.set(
        "system.llm.routing",
        {
            "enabled": True,
            "classifier_model": "gemini:gemini-3.1-flash-lite",
            "flash_model": "gemini:gemini-3-flash-preview",
            "default_model": "system.llm.active_model",
            "classifier_threshold": 80,
            "classifier_timeout_seconds": 8,
        },
        category="system",
    )
    manager = ModelManager(settings)

    classifier = function_model(
        "gemini-3.1-flash-lite",
        '{"classifier_reasoning":"Routine task.","classifier_score":34}',
        RequestUsage(input_tokens=10, output_tokens=2),
    )
    flash = function_model(
        "gemini-3-flash-preview",
        "done",
        RequestUsage(input_tokens=100, output_tokens=25),
    )

    def create_model(model_id: str):
        resolved = manager.resolve_model_id(model_id)
        if resolved == "gemini:gemini-3.1-flash-lite":
            return classifier
        if resolved == "gemini:gemini-3-flash-preview":
            return flash
        return function_model("gpt-test", "default", RequestUsage(input_tokens=999, output_tokens=999))

    monkeypatch.setattr(manager, "create_model", create_model)
    monkeypatch.setattr(manager, "create_active_model", lambda: create_model("system.llm.active_model"))
    usage_tracker = ModelUsageTracker()

    routing_model = RoutingModel(
        model_manager=manager,
        router=ModelRouter(manager),
        routing_context=RoutingContext(
            session_id="s1",
            run_id="r1",
            scope="master",
            usage_tracker=usage_tracker,
        ),
    )

    caplog.set_level(logging.INFO, logger="app.core.model_routing")
    response = await routing_model.request(
        [ModelRequest(parts=[UserPromptPart(content="format this list")])],
        None,
        ModelRequestParameters(),
    )

    assert response.model_name == "gemini-3-flash-preview"
    assert response.usage.input_tokens == 100
    assert response.usage.output_tokens == 25
    assert response.usage.total_tokens == 125

    route_records = [
        record.msg["message"]
        for record in caplog.records
        if isinstance(record.msg, dict)
        and isinstance(record.msg.get("message"), dict)
        and record.msg["message"].get("event") == "model_route"
    ]
    assert len(route_records) == 1
    route_event = route_records[0]
    assert route_event["classifier"]["score"] == 34
    assert route_event["route"]["selected_route"] == "flash"
    assert route_event["route"]["final_model"] == "gemini:gemini-3-flash-preview"
    assert route_event["usage"]["classifier"] == {
        "input_tokens": 10,
        "output_tokens": 2,
        "total_tokens": 12,
    }
    assert route_event["usage"]["request"] == {
        "input_tokens": 100,
        "output_tokens": 25,
        "total_tokens": 125,
    }
    assert usage_tracker.snapshot() == {
        "version": 1,
        "request": {
            "total": {"input_tokens": 100, "output_tokens": 25, "total_tokens": 125},
            "by_model": {
                "gemini:gemini-3-flash-preview": {
                    "input_tokens": 100,
                    "output_tokens": 25,
                    "total_tokens": 125,
                    "request_count": 1,
                }
            },
        },
        "classifier": {
            "model": "gemini:gemini-3.1-flash-lite",
            "input_tokens": 10,
            "output_tokens": 2,
            "total_tokens": 12,
            "request_count": 1,
        },
    }


@pytest.mark.asyncio
async def test_routing_model_disabled_uses_wrapped_active_model_without_classifier(
    tmp_path,
    monkeypatch,
    caplog,
):
    settings = Settings(root_dir=tmp_path)
    settings.set("system.llm.active_model", "openai:gpt-test", category="system")
    settings.set("system.llm.routing", {"enabled": False}, category="system")
    manager = ModelManager(settings)
    active = function_model(
        "gpt-test",
        "active",
        RequestUsage(input_tokens=7, output_tokens=3),
    )

    create_model_calls: list[str] = []

    def create_model(model_id: str):
        create_model_calls.append(model_id)
        return active

    monkeypatch.setattr(manager, "create_model", create_model)
    monkeypatch.setattr(manager, "create_active_model", lambda: active)
    usage_tracker = ModelUsageTracker()

    routing_model = RoutingModel(
        model_manager=manager,
        router=ModelRouter(manager),
        routing_context=RoutingContext(
            session_id="s1",
            run_id="r1",
            scope="master",
            usage_tracker=usage_tracker,
        ),
    )

    caplog.set_level(logging.INFO, logger="app.core.model_routing")
    response = await routing_model.request(
        [ModelRequest(parts=[UserPromptPart(content="hello")])],
        None,
        ModelRequestParameters(),
    )

    assert response.model_name == "gpt-test"
    assert response.usage.input_tokens == 7
    assert create_model_calls == []
    usage_snapshot = usage_tracker.snapshot()
    assert usage_snapshot["request"] == {
        "total": {"input_tokens": 7, "output_tokens": 3, "total_tokens": 10},
        "by_model": {
            "openai:gpt-test": {
                "input_tokens": 7,
                "output_tokens": 3,
                "total_tokens": 10,
                "request_count": 1,
            }
        },
    }
    assert "classifier" not in usage_snapshot
    assert not [
        record
        for record in caplog.records
        if isinstance(record.msg, dict)
        and isinstance(record.msg.get("message"), dict)
        and record.msg["message"].get("event") == "model_route"
    ]


@pytest.mark.asyncio
async def test_router_uses_gemini_flash_fallback_when_deepseek_flash_unavailable(tmp_path, monkeypatch):
    settings = Settings(root_dir=tmp_path)
    settings.set("system.llm.active_model", "openai:gpt-test", category="system")
    settings.set(
        "system.llm.routing",
        {
            "enabled": True,
            "classifier_model": "gemini:gemini-3.1-flash-lite",
            "flash_model": "deepseek:deepseek-v4-flash",
            "flash_fallback_model": "gemini:gemini-3-flash-preview",
            "default_model": "system.llm.active_model",
            "classifier_threshold": 80,
            "classifier_timeout_seconds": 8,
        },
        category="system",
    )
    manager = ModelManager(settings)
    classifier = function_model(
        "gemini-3.1-flash-lite",
        '{"classifier_reasoning":"Routine task.","classifier_score":34}',
        RequestUsage(input_tokens=10, output_tokens=2),
    )
    gemini_flash = function_model(
        "gemini-3-flash-preview",
        "done",
        RequestUsage(input_tokens=100, output_tokens=25),
    )

    def create_model(model_id: str):
        resolved = manager.resolve_model_id(model_id)
        if resolved == "gemini:gemini-3.1-flash-lite":
            return classifier
        if resolved == "deepseek:deepseek-v4-flash":
            raise LLMConfigurationError("DeepSeek is missing API Key.")
        if resolved == "gemini:gemini-3-flash-preview":
            return gemini_flash
        return function_model("gpt-test", "default", RequestUsage(input_tokens=999, output_tokens=999))

    monkeypatch.setattr(manager, "create_model", create_model)

    decision = await ModelRouter(manager).route(
        messages=[ModelRequest(parts=[UserPromptPart(content="format this list")])],
        context=RoutingContext(session_id="s1", run_id="r1"),
    )

    assert decision.selected_route == "flash"
    assert decision.model_id == "gemini:gemini-3-flash-preview"
    assert decision.flash_fallback_model_id == "gemini:gemini-3-flash-preview"


@pytest.mark.asyncio
async def test_router_uses_active_model_when_all_flash_models_unavailable(tmp_path, monkeypatch):
    settings = Settings(root_dir=tmp_path)
    settings.set("system.llm.active_model", "openai:gpt-test", category="system")
    settings.set(
        "system.llm.routing",
        {
            "enabled": True,
            "classifier_model": "gemini:gemini-3.1-flash-lite",
            "flash_model": "deepseek:deepseek-v4-flash",
            "flash_fallback_model": "gemini:gemini-3-flash-preview",
            "default_model": "system.llm.active_model",
            "classifier_threshold": 80,
            "classifier_timeout_seconds": 8,
        },
        category="system",
    )
    manager = ModelManager(settings)
    classifier = function_model(
        "gemini-3.1-flash-lite",
        '{"classifier_reasoning":"Routine task.","classifier_score":34}',
        RequestUsage(input_tokens=10, output_tokens=2),
    )

    def create_model(model_id: str):
        resolved = manager.resolve_model_id(model_id)
        if resolved == "gemini:gemini-3.1-flash-lite":
            return classifier
        if resolved in {"deepseek:deepseek-v4-flash", "gemini:gemini-3-flash-preview"}:
            raise LLMConfigurationError(f"{resolved} is not configured.")
        return function_model("gpt-test", "default", RequestUsage(input_tokens=999, output_tokens=999))

    monkeypatch.setattr(manager, "create_model", create_model)

    decision = await ModelRouter(manager).route(
        messages=[ModelRequest(parts=[UserPromptPart(content="format this list")])],
        context=RoutingContext(session_id="s1", run_id="r1"),
    )

    assert decision.selected_route == "default"
    assert decision.model_id == "openai:gpt-test"
    assert decision.classifier_score == 34


@pytest.mark.asyncio
async def test_router_uses_active_model_when_classifier_unavailable(tmp_path, monkeypatch):
    settings = Settings(root_dir=tmp_path)
    settings.set("system.llm.active_model", "openai:gpt-test", category="system")
    settings.set(
        "system.llm.routing",
        {
            "enabled": True,
            "classifier_model": "gemini:gemini-3.1-flash-lite",
            "flash_model": "deepseek:deepseek-v4-flash",
            "flash_fallback_model": "gemini:gemini-3-flash-preview",
            "default_model": "system.llm.active_model",
            "classifier_threshold": 80,
            "classifier_timeout_seconds": 8,
        },
        category="system",
    )
    manager = ModelManager(settings)

    def create_model(model_id: str):
        resolved = manager.resolve_model_id(model_id)
        if resolved == "gemini:gemini-3.1-flash-lite":
            raise LLMConfigurationError("Gemini Lite is not configured.")
        return function_model("gpt-test", "default", RequestUsage(input_tokens=999, output_tokens=999))

    monkeypatch.setattr(manager, "create_model", create_model)

    decision = await ModelRouter(manager).route(
        messages=[ModelRequest(parts=[UserPromptPart(content="format this list")])],
        context=RoutingContext(session_id="s1", run_id="r1"),
    )

    assert decision.selected_route == "default"
    assert decision.model_id == "openai:gpt-test"
    assert decision.classifier_score is None


def test_agent_manager_builds_routing_context_with_session_and_run_ids(tmp_path):
    settings = Settings(root_dir=tmp_path)
    settings.set("system.llm.active_model", "openai:gpt-test", category="system")
    model_manager = ModelManager(settings)
    active_model = function_model("gpt-test", "active", RequestUsage(input_tokens=1, output_tokens=1))
    model_manager.create_active_model = lambda: active_model

    class ToolManager:
        @staticmethod
        def get_capabilities():
            return []

        @staticmethod
        def register_skill_toolkits(_agent):
            return None

        @staticmethod
        def register_master_toolkits(_agent):
            return None

    class PromptBuilder:
        @staticmethod
        def build_skill_system_prompt(skill_name: str) -> str:
            return f"skill:{skill_name}"

        @staticmethod
        def build_system_prompt(session_id: str) -> str:
            return f"session:{session_id}"

    manager = AgentManager(
        settings=settings,
        model_manager=model_manager,
        tool_manager=ToolManager(),
        prompt_builder=PromptBuilder(),
        session_manager=object(),
        context_manager=object(),
    )

    master_agent = manager.build_master_agent("session-1", run_id="run-1")
    skill_agent = manager.build_skill_agent(
        "seo-keyword-research",
        session_id="session-1",
        run_id="run-1",
    )

    assert master_agent.model._routing_context == RoutingContext(
        session_id="session-1",
        run_id="run-1",
        scope="master",
    )
    assert skill_agent.model._routing_context == RoutingContext(
        session_id="session-1",
        run_id="run-1",
        scope="skill",
        skill_name="seo-keyword-research",
    )


def test_classifier_input_filters_leading_system_prompt_and_keeps_current_request(tmp_path):
    settings = Settings(root_dir=tmp_path)
    manager = ModelManager(settings)
    router = ModelRouter(manager)
    long_tool_output = "stock report " * 1000
    messages = [
        ModelRequest(parts=[
            SystemPromptPart(content="You are Ferryman. " * 300),
            UserPromptPart(content="Analyze 中国建材."),
        ]),
        ModelRequest(parts=[
            ToolReturnPart(
                tool_name="run_skill",
                content=long_tool_output,
                tool_call_id="call-1",
            )
        ]),
        ModelRequest(parts=[UserPromptPart(content="Write the final answer.")]),
    ]

    classifier_messages = router._build_classifier_messages(messages)

    assert len(classifier_messages) == 4
    assert isinstance(classifier_messages[0], ModelRequest)
    assert isinstance(classifier_messages[0].parts[0], SystemPromptPart)
    assert "Task Routing AI" in classifier_messages[0].parts[0].content
    assert "# Decision" not in classifier_messages[0].parts[0].content
    assert "classifier_score <" not in classifier_messages[0].parts[0].content
    assert isinstance(classifier_messages[1], ModelRequest)
    assert isinstance(classifier_messages[2], ModelRequest)
    assert isinstance(classifier_messages[3], ModelRequest)
    assert isinstance(classifier_messages[1].parts[0], UserPromptPart)
    assert isinstance(classifier_messages[2].parts[0], ToolReturnPart)
    assert isinstance(classifier_messages[3].parts[0], UserPromptPart)
    first_context = classifier_messages[1].parts[0].content
    tool_context = classifier_messages[2].parts[0].content
    final_context = classifier_messages[3].parts[0].content
    assert "Analyze 中国建材." in first_context
    assert "You are Ferryman." not in first_context
    assert "[truncated original_chars=" in tool_context
    assert len(tool_context) <= 2048
    assert tool_context != long_tool_output
    assert classifier_messages[2].parts[0].tool_name == "run_skill"
    assert "Write the final answer." in final_context


def test_classifier_input_keeps_last_8_non_system_messages(tmp_path):
    settings = Settings(root_dir=tmp_path)
    manager = ModelManager(settings)
    router = ModelRouter(manager)
    messages = [ModelRequest(parts=[SystemPromptPart(content="business system")])]
    messages.extend(
        ModelRequest(parts=[UserPromptPart(content=f"message {index}")])
        for index in range(10)
    )

    classifier_messages = router._build_classifier_messages(messages)

    assert len(classifier_messages) == 9
    assert classifier_messages[0].parts[0].content.startswith("You are a specialized Task Routing AI.")
    assert "Find three non-consensus AI products" in classifier_messages[0].parts[0].content
    assert "Filesystem deletion carries data-loss risk" in classifier_messages[0].parts[0].content
    assert [
        f"message {index}" in message.parts[0].content
        for index, message in zip(range(2, 10), classifier_messages[1:])
    ] == [True] * 8


def test_classifier_input_keeps_single_message_without_system_prompt(tmp_path):
    settings = Settings(root_dir=tmp_path)
    manager = ModelManager(settings)
    router = ModelRouter(manager)
    message = ModelRequest(parts=[UserPromptPart(content="format this list")])

    classifier_messages = router._build_classifier_messages([message])

    assert len(classifier_messages) == 2
    assert "format this list" in classifier_messages[1].parts[0].content


def test_classifier_input_filters_system_prompt_from_all_recent_messages(tmp_path):
    settings = Settings(root_dir=tmp_path)
    manager = ModelManager(settings)
    router = ModelRouter(manager)
    messages = [
        ModelRequest(parts=[UserPromptPart(content="first user")]),
        ModelRequest(parts=[
            SystemPromptPart(content="late system"),
            UserPromptPart(content="late user"),
        ]),
        ModelRequest(parts=[SystemPromptPart(content="system only")]),
        ModelResponse(parts=[TextPart(content="assistant reply")]),
    ]

    classifier_messages = router._build_classifier_messages(messages)

    assert len(classifier_messages) == 4
    assert "first user" in classifier_messages[1].parts[0].content
    assert "late user" in classifier_messages[2].parts[0].content
    assert "late system" not in classifier_messages[2].parts[0].content
    assert "assistant reply" in classifier_messages[3].parts[0].content
    assert all(
        not isinstance(part, SystemPromptPart)
        for message in classifier_messages[1:]
        if isinstance(message, ModelRequest)
        for part in message.parts
    )


def test_classifier_input_preserves_instructions_with_message_limit(tmp_path):
    settings = Settings(root_dir=tmp_path)
    manager = ModelManager(settings)
    router = ModelRouter(manager)
    message = ModelRequest(
        parts=[UserPromptPart(content="Current short request.")],
        instructions="Important routing instruction. " * 200,
    )

    classifier_messages = router._build_classifier_messages([message])
    sanitized_message = classifier_messages[1]
    assert isinstance(sanitized_message, ModelRequest)
    context = sanitized_message.parts[0].content
    instructions = sanitized_message.instructions

    assert len(context) <= 2048
    assert instructions is not None
    assert len(instructions) <= 2048
    assert "Important routing instruction." in instructions
    assert "Current short request." in context
    assert "[truncated original_chars=" in instructions
