from __future__ import annotations

import logging
from typing import Any

from pydantic_ai.models import Model

from app.core.config import Settings

logger = logging.getLogger(__name__)


class LLMConfigurationError(RuntimeError):
    """Raised when the active model provider is not configured locally."""


class ModelManager:
    """Manage model provider configuration and LLM model construction."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def create_active_model(self) -> Model[Any]:
        """Create a model instance from the currently active model setting."""
        active_model_id = self._settings.get_active_model_id()
        if not active_model_id:
            raise LLMConfigurationError("No active model is selected. Configure a provider and choose a model first.")
        if ":" not in active_model_id:
            raise LLMConfigurationError(f"Active model `{active_model_id}` is invalid.")

        provider, model_name = active_model_id.split(":", 1)
        provider_config = self._settings.get_provider_llm_config(provider)

        api_key = provider_config.get("api_key")
        base_url = provider_config.get("base_url")
        if base_url and isinstance(base_url, str):
            base_url = base_url.strip() or None
        if api_key and isinstance(api_key, str):
            api_key = api_key.strip()

        provider_catalog = self._settings.get_llm_provider_catalog()
        if provider in {"qwen", "deepseek", "kimi", "doubao"} and not base_url:
            base_url = provider_catalog[provider]["placeholder_base_url"]
        if provider == "anthropic" and isinstance(base_url, str) and base_url.rstrip("/").endswith("/v1"):
            base_url = base_url.rstrip("/")[:-3]

        if provider not in provider_catalog:
            raise LLMConfigurationError(f"Active model provider `{provider}` is not supported.")

        missing_fields: list[str] = []
        if provider in {"gemini", "openai", "anthropic", "qwen", "deepseek", "kimi", "doubao", "custom"} and not api_key:
            missing_fields.append("API Key")
        if provider == "custom" and not base_url:
            missing_fields.append("Base URL")
        if missing_fields:
            provider_label = provider_catalog.get(provider, {}).get("label", provider)
            missing_text = " and ".join(missing_fields)
            raise LLMConfigurationError(
                f"Active model `{provider}:{model_name}` is selected, but {provider_label} is missing {missing_text}. "
                "Configure the provider in Settings or choose another model."
            )

        p_kwargs = {k: v for k, v in {"api_key": api_key, "base_url": base_url}.items() if v is not None}

        try:
            if provider in {"openai", "qwen", "deepseek", "doubao", "custom"}:
                from pydantic_ai.models.openai import OpenAIChatModel
                from pydantic_ai.providers.openai import OpenAIProvider

                return OpenAIChatModel(model_name, provider=OpenAIProvider(**p_kwargs))
            if provider == "kimi":
                from openai import AsyncOpenAI
                from pydantic_ai.models.openai import OpenAIChatModel
                from pydantic_ai.providers.openai import OpenAIProvider

                if base_url:
                    openai_client = AsyncOpenAI(base_url=base_url, api_key=api_key)
                    return OpenAIChatModel(model_name, provider=OpenAIProvider(openai_client=openai_client))
                return OpenAIChatModel(model_name, provider=OpenAIProvider(api_key=api_key))
            if provider == "anthropic":
                from pydantic_ai.models.anthropic import AnthropicModel
                from pydantic_ai.providers.anthropic import AnthropicProvider

                return AnthropicModel(model_name, provider=AnthropicProvider(**p_kwargs))
            if provider == "gemini":
                from pydantic_ai.models.google import GoogleModel
                from pydantic_ai.providers.google import GoogleProvider

                return GoogleModel(model_name, provider=GoogleProvider(**p_kwargs))
        except Exception as e:
            logger.exception(
                f"Failed to initialize active model for {provider}, exception: {e}"
            )
            raise LLMConfigurationError(
                f"Failed to initialize active model `{provider}:{model_name}`. "
                "Check the provider settings or choose another model."
            ) from e

        raise LLMConfigurationError(f"Active model provider `{provider}` is not supported.")
