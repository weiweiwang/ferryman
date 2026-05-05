from __future__ import annotations

import asyncio

from jsonrpcserver import Success, method

from app.core.config import get_settings


@method
async def get_llm_configs(context):
    """Return consolidated API configurations for supported providers."""
    providers = get_settings().get_llm_provider_catalog()

    results = []
    for provider, metadata in providers.items():
        stored_config: dict[str, str] = get_settings().get(f"llm.{provider}", {})

        results.append({
            "provider": provider,
            "api_key": stored_config.get("api_key", ""),
            "base_url": stored_config.get("base_url", ""),
            "model": stored_config.get("model", ""),
            "metadata": {
                "label": metadata.get("label", provider.capitalize()),
                "placeholder_base_url": metadata.get("placeholder_base_url", ""),
                "placeholder_model": metadata.get("placeholder_model", ""),
                "supports_model": bool(metadata.get("supports_model", False)),
            }
        })

    return Success(results)


@method
async def set_llm_config(
    context,
    provider: str,
    api_key: str = None,
    base_url: str = None,
    model: str = None,
):
    """Update the consolidated config object for a provider."""
    key = f"llm.{provider}"
    current_config = get_settings().get(key, {})

    if api_key is not None:
        current_config["api_key"] = api_key
    if base_url is not None:
        current_config["base_url"] = base_url.strip() if base_url.strip() else ""
    if model is not None and provider == "custom":
        current_config["model"] = model.strip() if model.strip() else ""

    validation_error = await asyncio.to_thread(
        get_settings().validate_provider_config,
        provider,
        current_config.get("api_key", ""),
        current_config.get("base_url", ""),
        current_config.get("model", ""),
    )
    if validation_error:
        return Success({"status": "error", "message": validation_error})

    get_settings().set(key, current_config, category="llm")
    return Success({"status": "success"})


@method
async def get_active_model(context):
    """Return the currently active model identifier."""
    return Success(get_settings().get_active_model_id())


@method
async def get_model_readiness(context):
    """Return whether Ferryman has a usable active model for chat."""
    return Success(get_settings().get_model_readiness())


@method
async def set_active_model(context, model: str):
    """Update the active model globally."""
    get_settings().set("system.llm.active_model", model, category="system")
    return Success({"status": "success"})


@method
async def get_available_models(context):
    """Return the mapped candidate models for the UI select."""
    return Success(await asyncio.to_thread(get_settings().get_available_models))

