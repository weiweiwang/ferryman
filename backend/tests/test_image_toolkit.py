import base64
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic_ai.exceptions import ModelRetry

from app.core.config import Settings
from app.core.runtime import FerrymanRuntime
from app.core.toolkits.image import ImageToolkit
from app.core.tool_activity_payload import summarize_tool_input_value


def make_context(tmp_path: Path, session_id: str = "image-session"):
    settings = Settings(root_dir=tmp_path / "ferryman")
    runtime = FerrymanRuntime(settings=settings)
    deps = runtime.create_agent_deps(session_id=session_id, run_id="run-image-toolkit-test")
    return SimpleNamespace(deps=deps)


class FakeImageResult:
    def __init__(self, payload: dict):
        self.payload = payload

    def model_dump(self):
        return self.payload


def image_payload(*, quality: str = "low", output_format: str = "png") -> dict:
    return {
        "created": 1770000000,
        "data": [
            {
                "b64_json": base64.b64encode(b"fake-image-bytes").decode("ascii"),
            }
        ],
        "quality": quality,
        "size": "1024x1024",
        "output_format": output_format,
        "usage": {"total_tokens": 12},
    }


@pytest.mark.asyncio
async def test_generate_image_uses_azure_client_for_azure_base_url(monkeypatch, tmp_path):
    captured = {}

    class FakeImages:
        def generate(self, **kwargs):
            captured["generate_kwargs"] = kwargs
            return FakeImageResult(image_payload())

    class FakeAzureOpenAI:
        def __init__(self, **kwargs):
            captured["client_type"] = "azure"
            captured["client_kwargs"] = kwargs
            self.images = FakeImages()

    monkeypatch.setattr("openai.AzureOpenAI", FakeAzureOpenAI)

    ctx = make_context(tmp_path)
    result = await ImageToolkit.generate_image(
        ctx,
        api_key="test-key",
        base_url="https://example.azure.com/",
        prompt="A quiet ferry terminal at sunrise",
    )

    assert captured["client_type"] == "azure"
    assert captured["client_kwargs"] == {
        "api_key": "test-key",
        "azure_endpoint": "https://example.azure.com/",
        "api_version": "2025-01-01-preview",
    }
    assert captured["generate_kwargs"] == {
        "model": "gpt-image-2",
        "prompt": "A quiet ferry terminal at sunrise",
        "size": "1024x1024",
        "quality": "low",
        "output_format": "png",
        "output_compression": 100,
        "n": 1,
    }
    assert "provider" not in result
    assert "base_url_type" not in result
    assert "api_version" not in result
    assert result["quality"] == "low"
    assert result["usage"] == {"total_tokens": 12}
    saved_path = Path(result["images"][0]["path"])
    assert saved_path.name.startswith("image-")
    assert saved_path.read_bytes() == b"fake-image-bytes"
    assert saved_path.is_relative_to(ctx.deps.workspace_dir)


@pytest.mark.asyncio
async def test_generate_image_uses_openai_client_for_non_azure_base_url(monkeypatch, tmp_path):
    captured = {}

    class FakeImages:
        def generate(self, **kwargs):
            captured["generate_kwargs"] = kwargs
            return FakeImageResult(image_payload(output_format="webp"))

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured["client_type"] = "openai"
            captured["client_kwargs"] = kwargs
            self.images = FakeImages()

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)

    ctx = make_context(tmp_path)
    result = await ImageToolkit.generate_image(
        ctx,
        api_key="test-key",
        base_url="https://router.example.com/v1",
        prompt="A compact app icon",
        output_format="webp",
        output_path="assets/icon.webp",
    )

    assert captured["client_type"] == "openai"
    assert captured["client_kwargs"] == {
        "api_key": "test-key",
        "base_url": "https://router.example.com/v1",
    }
    assert captured["generate_kwargs"]["quality"] == "low"
    assert captured["generate_kwargs"]["output_format"] == "webp"
    assert "provider" not in result
    assert "base_url_type" not in result
    assert "api_version" not in result
    saved_path = Path(result["images"][0]["path"])
    assert saved_path.name == "icon.webp"
    assert saved_path.read_bytes() == b"fake-image-bytes"


@pytest.mark.asyncio
async def test_generate_image_rejects_output_path_escape(tmp_path):
    ctx = make_context(tmp_path)

    with pytest.raises(ModelRetry, match="Invalid output_path"):
        await ImageToolkit.generate_image(
            ctx,
            api_key="test-key",
            base_url="https://example.azure.com/",
            prompt="A ferry",
            output_path="../outside.png",
        )


def test_sensitive_image_tool_inputs_are_redacted_from_activity_summary():
    assert summarize_tool_input_value("api_key", "super-secret") == {"_summary": "redacted"}
    assert summarize_tool_input_value("base_url", "https://example.azure.com/") == {
        "_summary": "redacted"
    }
    assert summarize_tool_input_value("access_token", "tok") == {"_summary": "redacted"}
    assert summarize_tool_input_value("prompt", "hello") == {"_summary": "omitted", "length": 5}


def test_full_azure_generation_url_is_reduced_to_resource_root(monkeypatch):
    captured = {}

    class FakeImages:
        def generate(self, **kwargs):
            captured["generate_kwargs"] = kwargs
            return FakeImageResult(image_payload())

    class FakeAzureOpenAI:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs
            self.images = FakeImages()

    monkeypatch.setattr("openai.AzureOpenAI", FakeAzureOpenAI)

    result = ImageToolkit._generate_image(
        {
            "api_key": "test-key",
            "base_url": (
                "https://example.cognitiveservices.azure.com/openai/deployments/"
                "custom-image-deployment/images/generations?api-version=2024-02-01"
            ),
            "api_version": "2025-01-01-preview",
            "model": "gpt-image-2",
            "prompt": "A ferry",
            "size": "1024x1024",
            "quality": "low",
            "output_format": "png",
            "output_compression": 100,
            "n": 1,
        }
    )

    assert result["quality"] == "low"
    assert captured["client_kwargs"] == {
        "api_key": "test-key",
        "azure_endpoint": "https://example.cognitiveservices.azure.com/",
        "api_version": "2025-01-01-preview",
    }
    assert captured["generate_kwargs"]["model"] == "gpt-image-2"


@pytest.mark.asyncio
async def test_default_output_path_is_unique(monkeypatch, tmp_path):
    class FakeImages:
        def generate(self, **kwargs):
            return FakeImageResult(image_payload())

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.images = FakeImages()

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)

    ctx = make_context(tmp_path)
    first = await ImageToolkit.generate_image(
        ctx,
        api_key="test-key",
        base_url="https://router.example.com/v1",
        prompt="A ferry",
    )
    second = await ImageToolkit.generate_image(
        ctx,
        api_key="test-key",
        base_url="https://router.example.com/v1",
        prompt="A ferry",
    )

    assert first["images"][0]["path"] != second["images"][0]["path"]
