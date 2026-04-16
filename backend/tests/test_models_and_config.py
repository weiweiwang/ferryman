from datetime import datetime, timezone
from json import JSONDecodeError
from urllib.error import HTTPError

import pytest
from sqlmodel import select

from app.models.database import Session, Message, Task, AppConfig
from app.models.schemas import SessionModel, MessageModel, TaskModel
from app.core.config import ModelListEndpointUnavailable, Settings as config

from app.models.events import (
    FerrymanEventEnvelope,
    EventNamespace,
    ToolActivityPayload,
    ToolPhase,
    ChatFinalPayload,
    RefreshPayload,
    EntityAction,
    DataEntity
)


def test_app_config_crud(session):
    """Test AppConfig database operations."""
    app_config = AppConfig(key="test.key", value={"foo": "bar"}, category="test")
    session.add(app_config)
    session.commit()
    
    statement = select(AppConfig).where(AppConfig.key == "test.key")
    result = session.exec(statement).first()
    assert result is not None
    assert result.value == {"foo": "bar"}
    assert result.category == "test"


def test_session_message_relationship(session):
    """Test creating a session and associated messages."""
    new_session = Session(title="Test Session")
    session.add(new_session)
    session.commit()
    session.refresh(new_session)
    
    msg = Message(
        session_id=new_session.id,
        role="user",
        content="Hello",
        type="text"
    )
    session.add(msg)
    session.commit()
    
    statement = select(Message).where(Message.session_id == new_session.id)
    results = session.exec(statement).all()
    assert len(results) == 1
    assert results[0].content == "Hello"


def test_pydantic_schema_validation():
    """Test Pydantic model validation and transformation."""
    data = {
        "id": "test-uuid",
        "session_id": "session-uuid",
        "role": "assistant",
        "content": "Hi",
        "type": "text",
        "created_at": datetime.now(timezone.utc)
    }
    model = MessageModel(**data)
    assert model.role == "assistant"
    assert model.content == "Hi"


def test_event_models_serialization():
    """Test that event models can be created and serialized properly."""
    tool_payload = ToolActivityPayload(
        run_id="run-1",
        tool_name="navigate",
        phase=ToolPhase.START,
        input={"url": "example.com"}
    )
    env = FerrymanEventEnvelope(
        namespace=EventNamespace.AGENT,
        event="tool_activity",
        session_id="session-1",
        payload=tool_payload
    )
    
    dumped = env.model_dump(mode="json")
    assert dumped["namespace"] == "agent"
    assert dumped["payload"]["phase"] == "start"
    assert dumped["payload"]["input"]["url"] == "example.com"
    assert "ts" in dumped

    chat_payload = ChatFinalPayload(
        run_id="run-2",
        messages=[{"role": "assistant", "content": "Done"}],
        usage={"input_tokens": 10, "output_tokens": 5}
    )
    env = FerrymanEventEnvelope(
        namespace=EventNamespace.AGENT,
        event="chat_final",
        payload=chat_payload
    )
    dumped = env.model_dump(mode="json")
    assert dumped["payload"]["messages"][0]["content"] == "Done"

    refresh_payload = RefreshPayload(
        entity=DataEntity.TASK,
        action=EntityAction.UPDATED,
        entity_id="task-123"
    )
    env = FerrymanEventEnvelope(
        namespace=EventNamespace.DATA,
        event="refresh",
        payload=refresh_payload
    )
    dumped = env.model_dump(mode="json")
    assert dumped["payload"]["entity"] == "task"


def test_config_registry_persistence(session):
    """Test config registry sets and gets via the database."""
    test_key = "registry.test.key"
    test_val = {"enabled": True, "count": 42}
    
    config.set(test_key, test_val, category="test")
    retrieved = config.get(test_key)
    assert retrieved == test_val
    
    from app.core.db import get_session
    with get_session() as db_session:
         statement = select(AppConfig).where(AppConfig.key == test_key)
         record = db_session.exec(statement).first()
         assert record is not None
         assert record.value == test_val


def test_config_list_by_category():
    """Test filtering configurations by category."""
    config.set("cat.1", "val1", category="c1")
    config.set("cat.2", "val2", category="c1")
    config.set("cat.3", "val3", category="c2")
    
    c1_list = config.list_by_category("c1")
    assert len(c1_list) >= 2
    keys = [item.key for item in c1_list]
    assert "cat.1" in keys
    assert "cat.2" in keys
    assert "cat.3" not in keys


def test_available_models_include_qwen_and_dynamic_custom_model():
    """Configured providers should be fetched online and custom models remain selectable."""
    config.set("llm.openai", {"api_key": "sk-openai"}, category="llm")
    config.set("llm.qwen", {"api_key": "sk-qwen"}, category="llm")
    config.set("llm.kimi", {"api_key": "sk-kimi"}, category="llm")
    config.set("llm.doubao", {"api_key": "sk-doubao"}, category="llm")
    config.set(
        "llm.custom",
        {"api_key": "sk-custom", "base_url": "https://custom.example.com/v1", "model": "my-custom-model"},
        category="llm",
    )
    config.set("system.llm.active_model", "qwen:qwen-plus", category="system")

    original_fetcher = config._fetch_provider_models
    original_probe = config._probe_openai_compatible_chat_model

    def fake_fetcher(provider: str, api_key: str, base_url: str, list_mode: str):
        if provider == "openai":
            return ["gpt-4o", "text-embedding-3-large"]
        if provider == "qwen":
            raise ModelListEndpointUnavailable("HTTP 404")
        if provider == "kimi":
            return ["kimi-k2.5", "kimi-k2-thinking"]
        if provider == "doubao":
            return ["doubao-seed-2-0-pro-260215", "doubao-seed-2-0-lite-260215"]
        return []

    def fake_probe(api_key: str, base_url: str, model: str):
        assert api_key == "sk-custom"
        assert base_url == "https://custom.example.com/v1"
        assert model == "my-custom-model"

    config._fetch_provider_models = staticmethod(fake_fetcher)
    config._probe_openai_compatible_chat_model = staticmethod(fake_probe)
    try:
        models = config.get_available_models()
    finally:
        config._fetch_provider_models = original_fetcher
        config._probe_openai_compatible_chat_model = original_probe

    assert "openai" in models
    assert "gemini" not in models
    assert models["openai"] == ["gpt-4o", "text-embedding-3-large"]
    assert "qwen" not in models
    assert "kimi" in models
    assert "doubao" in models
    assert "custom" in models
    assert models["kimi"] == ["kimi-k2.5", "kimi-k2-thinking"]
    assert models["doubao"] == ["doubao-seed-2-0-pro-260215", "doubao-seed-2-0-lite-260215"]
    assert models["custom"] == ["my-custom-model"]


def test_available_models_include_openai_anthropic_and_gemini_when_configured():
    config.set("llm.openai", {"api_key": "sk-openai"}, category="llm")
    config.set("llm.anthropic", {"api_key": "sk-anthropic"}, category="llm")
    config.set("llm.gemini", {"api_key": "sk-gemini"}, category="llm")
    config.set("system.llm.active_model", "openai:gpt-4o", category="system")

    original_fetcher = config._fetch_provider_models

    def fake_fetcher(provider: str, api_key: str, base_url: str, list_mode: str):
        if provider == "openai":
            return ["gpt-4o", "text-embedding-3-large"]
        if provider == "anthropic":
            return ["claude-sonnet-4-5", "claude-opus-4-1"]
        if provider == "gemini":
            return ["gemini-3.1-pro-preview", "gemini-3.1-flash-preview"]
        return []

    config._fetch_provider_models = staticmethod(fake_fetcher)
    try:
        models = config.get_available_models()
    finally:
        config._fetch_provider_models = original_fetcher

    assert models["openai"] == ["gpt-4o", "text-embedding-3-large"]
    assert models["anthropic"] == ["claude-sonnet-4-5", "claude-opus-4-1"]
    assert models["gemini"] == ["gemini-3.1-pro-preview", "gemini-3.1-flash-preview"]


def test_get_available_models_hides_unconfigured_providers():
    config.set("llm.openai", {"api_key": "sk-openai"}, category="llm")
    config.set("llm.anthropic", {"api_key": ""}, category="llm")
    config.set("llm.gemini", {"api_key": ""}, category="llm")

    original_fetcher = config._fetch_provider_models

    def fake_fetcher(provider: str, api_key: str, base_url: str, list_mode: str):
        if provider == "openai":
            return ["gpt-4o"]
        return ["should-not-appear"]

    config._fetch_provider_models = staticmethod(fake_fetcher)
    try:
        models = config.get_available_models()
    finally:
        config._fetch_provider_models = original_fetcher

    assert models == {"openai": ["gpt-4o"]}


def test_get_available_models_does_not_fallback_on_fetch_error():
    config.set("llm.kimi", {"api_key": "bad-key"}, category="llm")

    original_fetcher = config._fetch_provider_models

    def fake_fetcher(provider: str, api_key: str, base_url: str, list_mode: str):
        raise RuntimeError("HTTP 401 Unauthorized")

    config._fetch_provider_models = staticmethod(fake_fetcher)
    try:
        models = config.get_available_models()
    finally:
        config._fetch_provider_models = original_fetcher

    assert "kimi" not in models


def test_get_available_models_hides_provider_on_transient_fetch_error():
    config.set("llm.gemini", {"api_key": "sk-gemini"}, category="llm")

    original_fetcher = config._fetch_provider_models

    def fake_fetcher(provider: str, api_key: str, base_url: str, list_mode: str):
        raise TimeoutError("The handshake operation timed out")

    config._fetch_provider_models = staticmethod(fake_fetcher)
    try:
        models = config.get_available_models()
    finally:
        config._fetch_provider_models = original_fetcher

    assert "gemini" not in models


def test_get_available_models_hides_custom_provider_when_fetch_fails():
    config.set(
        "llm.custom",
        {"api_key": "sk-custom", "base_url": "https://custom.example.com/v1", "model": "my-custom-model"},
        category="llm",
    )

    original_probe = config._probe_openai_compatible_chat_model

    def fake_probe(api_key: str, base_url: str, model: str):
        raise RuntimeError("HTTP 500 Internal Server Error")

    config._probe_openai_compatible_chat_model = staticmethod(fake_probe)
    try:
        models = config.get_available_models()
    finally:
        config._probe_openai_compatible_chat_model = original_probe

    assert "custom" not in models


def test_validate_provider_config_returns_error_when_fetch_fails(monkeypatch):
    def fake_fetcher(provider: str, api_key: str, base_url: str, list_mode: str):
        raise RuntimeError("HTTP 401 Unauthorized")

    monkeypatch.setattr(config, "_fetch_provider_models", staticmethod(fake_fetcher))

    message = config.validate_provider_config("openai", "bad-key")

    assert message == "API key validation failed: HTTP 401 Unauthorized"


def test_validate_provider_config_allows_empty_api_key():
    assert config.validate_provider_config("openai", "") is None


def test_validate_provider_config_requires_model_for_custom():
    assert config.validate_provider_config("custom", "sk-custom", "https://custom.example.com/v1", "") == "Model is required."


def test_validate_provider_config_probes_custom_chat_model(monkeypatch):
    captured = {}

    def fake_probe(api_key: str, base_url: str, model: str):
        captured["api_key"] = api_key
        captured["base_url"] = base_url
        captured["model"] = model

    monkeypatch.setattr(config, "_probe_openai_compatible_chat_model", staticmethod(fake_probe))

    assert config.validate_provider_config("custom", "sk-custom", "https://custom.example.com/v1", "my-custom-model") is None
    assert captured == {
        "api_key": "sk-custom",
        "base_url": "https://custom.example.com/v1",
        "model": "my-custom-model",
    }


def test_get_active_model_id_returns_none_when_unset():
    assert config().get_active_model_id() is None


def test_get_model_readiness_reports_no_runnable_model_when_unconfigured():
    readiness = config().get_model_readiness()

    assert readiness == {
        "ready": False,
        "active_model": None,
        "issue": {"code": "no_runnable_model"},
    }


def test_get_model_readiness_reports_invalid_active_model_when_selection_missing():
    config.set("llm.openai", {"api_key": "sk-openai"}, category="llm")

    readiness = config().get_model_readiness()

    assert readiness == {
        "ready": False,
        "active_model": None,
        "issue": {"code": "active_model_invalid"},
    }


def test_get_model_readiness_reports_missing_api_key_for_selected_provider():
    config.set("system.llm.active_model", "gemini:gemini-3-flash-preview", category="system")

    readiness = config().get_model_readiness()

    assert readiness == {
        "ready": False,
        "active_model": "gemini:gemini-3-flash-preview",
        "issue": {
            "code": "missing_api_key",
            "provider": "gemini",
            "missing": ["api_key"],
        },
    }


def test_get_model_readiness_reports_ready_for_configured_active_model():
    config.set("llm.openai", {"api_key": "sk-openai"}, category="llm")
    config.set("system.llm.active_model", "openai:gpt-4o", category="system")

    readiness = config().get_model_readiness()

    assert readiness == {
        "ready": True,
        "active_model": "openai:gpt-4o",
        "issue": None,
    }


def test_fetch_provider_models_routes_to_provider_specific_fetchers(monkeypatch):
    monkeypatch.setattr(config, "_fetch_anthropic_models", staticmethod(lambda api_key, base_url: ["claude-sonnet-4-5"]))
    monkeypatch.setattr(config, "_fetch_gemini_models", staticmethod(lambda api_key, base_url: ["gemini-3.1-pro-preview"]))
    monkeypatch.setattr(
        config,
        "_fetch_openai_compatible_models",
            staticmethod(
                lambda api_key, base_url: [
                    "gpt-4o",
                    "gpt-5.4-mini-2026-03-17",
                    "gpt-5.4-nano-2026-03-17",
                    "gpt-5.4-audio-preview-2026-03-17",
                    "kimi-k2.5",
                    "moonshot-v1-8k-vision-preview",
                    "doubao-seed-2-0-pro-260215",
                    "doubao-seed-1-6-251015",
                    "doubao-seed-2-0-code-preview-260215",
                "doubao-seedream-4-0-250828",
            ]
        ),
    )

    assert config._fetch_provider_models(
        "anthropic",
        "sk-a",
        "https://api.anthropic.com/v1",
        "anthropic",
    ) == ["claude-sonnet-4-5"]
    assert config._fetch_provider_models(
        "gemini",
        "sk-g",
        "https://generativelanguage.googleapis.com",
        "gemini",
    ) == ["gemini-3.1-pro-preview"]
    assert config._fetch_provider_models(
        "openai",
        "sk-o",
        "https://api.openai.com/v1",
        "openai_compatible",
    ) == ["gpt-5.4-mini-2026-03-17", "gpt-5.4-nano-2026-03-17"]
    assert config._fetch_provider_models(
        "kimi",
        "sk-k",
        "https://api.moonshot.cn/v1",
        "openai_compatible",
    ) == ["kimi-k2.5"]
    assert config._fetch_provider_models(
        "doubao",
        "sk-d",
        "https://ark.cn-beijing.volces.com/api/v3",
        "openai_compatible",
    ) == ["doubao-seed-2-0-pro-260215", "doubao-seed-2-0-code-preview-260215"]
def test_fetch_provider_models_marks_missing_models_endpoint_as_unavailable(monkeypatch):
    def raise_not_found(api_key: str, base_url: str):
        raise HTTPError(base_url, 404, "Not Found", hdrs=None, fp=None)

    monkeypatch.setattr(config, "_fetch_openai_compatible_models", staticmethod(raise_not_found))

    with pytest.raises(ModelListEndpointUnavailable):
        config._fetch_provider_models(
            "qwen",
            "sk-qwen",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "openai_compatible",
        )


def test_fetch_anthropic_models_falls_back_to_bearer_auth(monkeypatch):
    attempts = []

    def fake_http_get_json(url: str, headers=None, query=None):
        attempts.append(headers or {})
        if headers and headers.get("x-api-key"):
            raise HTTPError(url, 401, "Unauthorized", hdrs=None, fp=None)
        return {"data": [{"id": "claude-sonnet-4-6"}]}

    monkeypatch.setattr(config, "_http_get_json", staticmethod(fake_http_get_json))

    assert config._fetch_anthropic_models("sk-anthropic", "https://proxy.example.com/v1") == ["claude-sonnet-4-6"]
    assert attempts == [
        {
            "x-api-key": "sk-anthropic",
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        {
            "Authorization": "Bearer sk-anthropic",
            "Content-Type": "application/json",
        },
    ]


def test_fetch_anthropic_models_marks_non_json_response_as_unavailable(monkeypatch):
    def fake_http_get_json(url: str, headers=None, query=None):
        raise JSONDecodeError("Expecting value", "", 0)

    monkeypatch.setattr(config, "_http_get_json", staticmethod(fake_http_get_json))

    with pytest.raises(ModelListEndpointUnavailable):
        config._fetch_anthropic_models("sk-anthropic", "https://proxy.example.com/v1")


def test_probe_openai_compatible_chat_model_uses_chat_completions_endpoint(monkeypatch):
    captured = {}

    def fake_http_post_json(url: str, payload=None, headers=None, query=None):
        captured["url"] = url
        captured["payload"] = payload
        captured["headers"] = headers
        captured["query"] = query
        return {"id": "chatcmpl-test"}

    monkeypatch.setattr(config, "_http_post_json", staticmethod(fake_http_post_json))

    config._probe_openai_compatible_chat_model(
        "sk-custom",
        "https://custom.example.com/v1",
        "my-custom-model",
    )

    assert captured == {
        "url": "https://custom.example.com/v1/chat/completions",
        "payload": {
            "model": "my-custom-model",
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
            "temperature": 0,
        },
        "headers": {
            "Authorization": "Bearer sk-custom",
            "Content-Type": "application/json",
        },
        "query": None,
    }


def test_filter_chat_model_ids_excludes_non_chat_entries():
    filtered = config._filter_chat_model_ids([
        "gpt-4o",
        "text-embedding-3-large",
        "whisper-1",
        "claude-sonnet-4-5",
    ])

    assert filtered == ["gpt-4o", "claude-sonnet-4-5"]


def test_filter_gemini_models_keeps_only_llm_entries():
    filtered = config._filter_gemini_models([
        {
            "name": "models/gemini-2.0-flash-001",
            "baseModelId": "gemini-2.0-flash",
            "supportedGenerationMethods": ["generateContent"],
        },
        {
            "name": "models/gemini-2.0-flash-lite-001",
            "baseModelId": "",
            "supportedGenerationMethods": ["generateContent"],
        },
        {
            "name": "models/gemini-2.5-flash-native-audio-preview-09-2025",
            "baseModelId": "gemini-2.5-flash-native-audio-preview-09-2025",
            "supportedGenerationMethods": ["generateContent"],
        },
        {
            "name": "models/gemini-3.1-pro-preview",
            "baseModelId": "gemini-3.1-pro-preview",
            "supportedGenerationMethods": ["generateContent"],
        },
        {
            "name": "models/veo-3.1-fast-generate-preview",
            "baseModelId": "veo-3.1-fast-generate-preview",
            "supportedGenerationMethods": ["generateContent"],
        },
        {
            "name": "models/text-embedding-004",
            "baseModelId": "text-embedding-004",
            "supportedGenerationMethods": ["embedContent"],
        },
        {
            "name": "models/gemini-3.1-flash-live-preview",
            "baseModelId": "gemini-3.1-flash-live-preview",
            "supportedGenerationMethods": ["generateContent"],
        },
    ])

    assert filtered == ["gemini-2.0-flash", "gemini-3.1-pro-preview"]


def test_filter_qwen_models_keeps_only_qwen_family_entries():
    filtered = config._filter_qwen_models([
        "MiniMax-M2.1",
        "deepseek-v3.1",
        "glm-4.7",
        "kimi-k2.5",
        "qwen3.6-plus-2026-04-02",
        "qwen3.6-plus",
        "qwen3.5-omni-plus-2026-03-15",
        "qwen3.5-omni-plus",
        "qwen3.5-omni-flash",
        "qwen3.5-flash",
        "qwen3.5-plus",
        "qwen3.5-397b-a17b",
        "qwen3-max",
        "qwen-plus",
        "qwen-max",
        "qwen-max-0107",
        "qwen-max-0428",
        "qwen-max-0919",
        "qwen-max-1201",
        "qwen-plus-2025-05-15",
        "qwen-max-2025-01-25",
        "qwen-vl-max",
        "qwen-omni-turbo",
        "qwen-omni-turbo-0119",
        "qwen3-32b",
        "qwen-coder-plus",
    ])

    assert filtered == [
        "qwen3.6-plus",
        "qwen3.5-plus",
        "qwen3.5-omni-plus",
        "qwen3.5-flash",
        "qwen3.5-omni-flash",
        "qwen3-max",
    ]


def test_filter_kimi_models_keeps_latest_supported_chat_family():
    filtered = config._filter_kimi_models([
        "kimi-k2.5",
        "kimi-k2-thinking",
        "kimi-k2-thinking-turbo",
        "kimi-k2-0905-preview",
        "kimi-latest",
        "kimi-thinking-preview",
        "moonshot-v1-8k",
        "moonshot-v1-32k-vision-preview",
        "text-embedding-v1",
        "qwen-plus",
    ])

    assert filtered == [
        "kimi-k2.5",
    ]


def test_filter_doubao_models_keeps_latest_supported_chat_family():
    filtered = config._filter_doubao_models([
        "doubao-seed-2-0-code-preview-260215",
        "doubao-seed-1-6-251015",
        "doubao-seed-2-1-mini-260415",
        "doubao-seed-2-0-pro-260215",
        "doubao-seed-2-1-pro-260415",
        "doubao-seed-2-0-lite-260215",
        "doubao-seed-2-1-lite-260415",
        "doubao-seedream-4-0-250828",
        "doubao-seed-2-0-mini-260215",
        "doubao-embedding-text-240715",
        "doubao-seed-2-1-code-preview-260415",
        "doubao-seed-2-0-pro-260215",
        "kimi-k2.5",
        "ep-20260414-example",
    ])

    assert filtered == [
        "doubao-seed-2-1-pro-260415",
        "doubao-seed-2-1-lite-260415",
        "doubao-seed-2-1-mini-260415",
        "doubao-seed-2-1-code-preview-260415",
    ]
