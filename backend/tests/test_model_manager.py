import pytest

from app.core.config import Settings
from app.core.model_manager import LLMConfigurationError, ModelManager


def test_model_manager_raises_clear_error_without_active_model(tmp_path):
    manager = ModelManager(Settings(root_dir=tmp_path))

    with pytest.raises(LLMConfigurationError, match="No active model"):
        manager.create_active_model()


def test_model_manager_raises_clear_error_for_missing_api_key(tmp_path):
    settings = Settings(root_dir=tmp_path)
    settings.set("system.llm.active_model", "gemini:gemini-test", category="system")
    manager = ModelManager(settings)

    with pytest.raises(LLMConfigurationError, match="missing API Key"):
        manager.create_active_model()


def test_model_manager_raises_when_provider_init_fails(tmp_path, monkeypatch):
    settings = Settings(root_dir=tmp_path)
    settings.set("system.llm.active_model", "kimi:kimi-test", category="system")
    settings.set("llm.kimi", {"api_key": "test-key"}, category="llm")

    class BrokenOpenAI:
        def __init__(self, **_kwargs):
            raise RuntimeError("boom")

    import openai

    monkeypatch.setattr(openai, "AsyncOpenAI", BrokenOpenAI)

    with pytest.raises(LLMConfigurationError, match="Failed to initialize active model"):
        ModelManager(settings).create_active_model()


def test_model_routing_default_threshold_is_80(tmp_path):
    manager = ModelManager(Settings(root_dir=tmp_path))

    assert manager.get_model_routing_config()["classifier_threshold"] == 80
