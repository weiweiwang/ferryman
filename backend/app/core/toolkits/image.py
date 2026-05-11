from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import shortuuid
from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.tools import RunContext

from app.core.deps import AgentDeps
from app.core.toolkits.base import Toolkit
from app.core.toolkits.file import FileToolkit

ImageRequestParams = dict[str, str | int]


class ImageToolkit(Toolkit):
    """Generate images through an OpenAI-compatible Images API."""

    @staticmethod
    def get_tools():
        return [ImageToolkit.generate_image]

    @staticmethod
    def _require_non_empty(field_name: str, value: str | None) -> str:
        normalized = (value or "").strip()
        if not normalized:
            raise ModelRetry(f"{field_name} must not be empty.")
        return normalized

    @staticmethod
    def _normalize_output_format(output_format: str) -> str:
        normalized = ImageToolkit._require_non_empty("output_format", output_format).lower()
        allowed_formats = {"png", "jpeg", "webp"}
        if normalized not in allowed_formats:
            raise ModelRetry(f"output_format must be one of: {', '.join(sorted(allowed_formats))}.")
        return normalized

    @staticmethod
    def _resolve_output_paths(
        ctx: RunContext[AgentDeps],
        output_path: str | None,
        image_count: int,
        output_format: str,
    ) -> list[Path]:
        if image_count < 1:
            raise ModelRetry("n must be at least 1.")

        if output_path and output_path.strip():
            normalized_path = output_path.strip()
        else:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            image_id = shortuuid.uuid()
            normalized_path = f"generated/image-{timestamp}-{image_id}.{output_format}"

        try:
            first_path = FileToolkit.resolve_session_path(
                ctx.deps,
                normalized_path,
            )
        except ValueError:
            raise ModelRetry(f"Invalid output_path: {normalized_path}")

        if image_count == 1:
            return [first_path]

        suffix = first_path.suffix or f".{output_format}"
        stem = first_path.stem
        parent = first_path.parent
        return [parent / f"{stem}-{index + 1}{suffix}" for index in range(image_count)]

    @staticmethod
    def _build_client(api_key: str, base_url: str, api_version: str):
        if ".azure.com" in base_url:
            from openai import AzureOpenAI

            return AzureOpenAI(
                api_key=api_key,
                azure_endpoint=base_url,
                api_version=api_version,
            )

        from openai import OpenAI

        return OpenAI(api_key=api_key, base_url=base_url)

    @staticmethod
    def _normalize_request_params(params: ImageRequestParams) -> ImageRequestParams:
        base_url = str(params["base_url"])
        if ".azure.com" not in base_url:
            return params

        parsed = urlparse(base_url)
        if not parsed.scheme or not parsed.netloc:
            return params

        params["base_url"] = urlunparse((parsed.scheme, parsed.netloc, "/", "", "", ""))
        return params

    @staticmethod
    def _generate_image(params: ImageRequestParams) -> dict[str, object]:
        params = ImageToolkit._normalize_request_params(params)
        api_key = str(params.pop("api_key"))
        base_url = str(params.pop("base_url"))
        api_version = str(params.pop("api_version"))
        client = ImageToolkit._build_client(api_key, base_url, api_version)
        result = client.images.generate(**params)
        return result.model_dump()

    @staticmethod
    async def generate_image(
        ctx: RunContext[AgentDeps],
        api_key: str,
        base_url: str,
        prompt: str,
        model: str = "gpt-image-2",
        api_version: str = "2025-01-01-preview",
        size: str | None = None,
        quality: str = "low",
        output_format: str = "png",
        n: int = 1,
        output_path: str | None = None,
    ) -> dict[str, object]:
        """Generate images through OpenAI-compatible `client.images.generate`.

        Pass `api_key` and `base_url` at call time. When `base_url` contains
        `.azure.com`, the tool uses `AzureOpenAI` with `api_version`; otherwise
        it uses `OpenAI(base_url=...)`. `quality` defaults to `low` to control
        cost and reduce accidental overuse. If provided, `size` must use the
        OpenAI Images API format `"<width>x<height>"`, for example
        `"1024x1024"` or `"2560x1088"`; when omitted, no `size` parameter is
        sent and the provider default applies. Generated images are saved
        inside the current session workspace.
        """
        normalized_api_key = ImageToolkit._require_non_empty("api_key", api_key)
        normalized_base_url = ImageToolkit._require_non_empty("base_url", base_url)
        normalized_prompt = ImageToolkit._require_non_empty("prompt", prompt)
        normalized_model = ImageToolkit._require_non_empty("model", model)
        normalized_api_version = ImageToolkit._require_non_empty("api_version", api_version)
        normalized_size = size.strip() if isinstance(size, str) and size.strip() else None
        normalized_quality = ImageToolkit._require_non_empty("quality", quality)
        normalized_output_format = ImageToolkit._normalize_output_format(output_format)

        if n < 1:
            raise ModelRetry("n must be at least 1.")
        if n > 4:
            raise ModelRetry("n must not exceed 4.")

        output_paths = ImageToolkit._resolve_output_paths(
            ctx,
            output_path,
            n,
            normalized_output_format,
        )

        request_params: ImageRequestParams = {
            "api_key": normalized_api_key,
            "base_url": normalized_base_url,
            "api_version": normalized_api_version,
            "model": normalized_model,
            "prompt": normalized_prompt,
            "quality": normalized_quality,
            "output_format": normalized_output_format,
            "n": n,
        }
        if normalized_size:
            request_params["size"] = normalized_size

        result = await asyncio.to_thread(ImageToolkit._generate_image, request_params)
        images = result.get("data") or []
        if not isinstance(images, list) or not images:
            raise ModelRetry("Image generation response did not include image data.")
        if len(images) > len(output_paths):
            output_paths = ImageToolkit._resolve_output_paths(
                ctx,
                output_path,
                len(images),
                normalized_output_format,
            )

        saved_images: list[dict[str, object]] = []
        for index, image in enumerate(images):
            if not isinstance(image, dict):
                raise ModelRetry("Image generation response included an invalid image item.")
            b64_json = image.get("b64_json")
            if not isinstance(b64_json, str) or not b64_json:
                raise ModelRetry("Image generation response did not include b64_json data.")

            try:
                image_bytes = base64.b64decode(b64_json, validate=True)
            except Exception as exc:
                raise ModelRetry("Image generation response included invalid base64 image data.") from exc

            target_path = output_paths[index]
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(image_bytes)
            saved_images.append(
                {
                    "path": str(target_path),
                    "bytes": len(image_bytes),
                }
            )

        return {
            "model": normalized_model,
            "size": result.get("size") or normalized_size,
            "quality": result.get("quality") or normalized_quality,
            "output_format": result.get("output_format") or normalized_output_format,
            "image_count": len(saved_images),
            "images": saved_images,
            "usage": result.get("usage"),
        }
