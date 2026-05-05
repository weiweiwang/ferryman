from __future__ import annotations

import json
import logging
import os
import re
import sys
from functools import lru_cache
from json import JSONDecodeError
from pathlib import Path
from typing import TYPE_CHECKING, Optional, TypeVar, cast, overload
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from app.models.database import AppConfig

logger = logging.getLogger(__name__)
T = TypeVar("T")


class ModelListEndpointUnavailable(RuntimeError):
    """Raised when a provider does not expose a usable models endpoint."""


class Settings(BaseSettings):
    """
    Immutable system-level configurations and path defaults.
    Values are loaded from environment variables or .env file.
    """
    model_config = SettingsConfigDict(
        env_file=os.environ.get("ENV_FILE", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True
    )

    # Base directory for all Ferryman persistence
    root_dir: Path = Field(default=Path.home() / ".ferryman", validation_alias="FERRYMAN_ROOT_DIR")
    port: int = 8000
    log_level: str = Field(
        default="DEBUG",
        validation_alias=AliasChoices("FERRYMAN_LOG_LEVEL", "LOG_LEVEL"),
    )
    resend_default_from: str = Field(
        default="noreply@ferryman.app",
        validation_alias="FERRYMAN_RESEND_DEFAULT_FROM",
    )

    @property
    def user_dir(self) -> Path:
        # This is the "Identity" folder that users can export/migrate
        return self.root_dir / "user"

    @property
    def db_path(self) -> Path:
        # DB must be inside user_dir to migrate sessions and settings
        return self.user_dir / "ferryman.db"

    @property
    def log_dir(self) -> Path:
        return self.user_dir / "logs"

    @property
    def browser_dir(self) -> Path:
        return self.user_dir / "browser"

    @property
    def user_skills_dir(self) -> Path:
        return self.user_dir / "skills"

    @property
    def bundled_skills_dir(self) -> Path:
        """Return the built-in skills directory for the current runtime."""
        env_override = os.environ.get("FERRYMAN_BUNDLED_SKILLS_DIR")
        if env_override:
            return Path(env_override).expanduser()

        repo_skills_dir = Path(__file__).resolve().parents[3] / "skills"
        if repo_skills_dir.exists():
            return repo_skills_dir

        meipass_dir = getattr(sys, "_MEIPASS", None)
        if meipass_dir:
            return Path(meipass_dir) / "skills"

        executable_path = Path(sys.executable).resolve()
        app_bundle_resources_dir = executable_path.parents[1] / "Resources" / "skills"
        if app_bundle_resources_dir.exists():
            return app_bundle_resources_dir

        return repo_skills_dir

    @property
    def skills_dir(self) -> tuple[Path, Path]:
        # Returns a tuple of (bundled, user) skill directories
        return (
            self.bundled_skills_dir,
            self.user_skills_dir,
        )

    @staticmethod
    def _runtime_defaults_path() -> Path:
        frozen_root = getattr(sys, "_MEIPASS", None)
        if frozen_root:
            return Path(frozen_root) / "app" / "assets" / "defaults" / "runtime_defaults.json"
        return Path(__file__).resolve().parents[1] / "assets" / "defaults" / "runtime_defaults.json"

    def load_packaged_runtime_defaults(self) -> dict[str, object]:
        defaults_path = self._runtime_defaults_path()
        if not defaults_path.exists():
            return {}
        try:
            payload = json.loads(defaults_path.read_text(encoding="utf-8"))
        except (OSError, JSONDecodeError) as exc:
            logger.warning(f"Could not load packaged runtime defaults from {defaults_path}: {exc}")
            return {}
        return cast(dict[str, object], payload) if isinstance(payload, dict) else {}

    def seed_runtime_defaults(self) -> None:
        """Seed packaged runtime defaults into the local SQLite config store."""
        payload = self.load_packaged_runtime_defaults()
        email_defaults = payload.get("email", {})
        resend_defaults = email_defaults.get("resend", {}) if isinstance(email_defaults, dict) else {}
        if not isinstance(resend_defaults, dict):
            resend_defaults = {}

        default_from = str(resend_defaults.get("default_from") or self.resend_default_from).strip()
        api_key = str(resend_defaults.get("api_key") or "").strip()

        if default_from and not self.get("email.resend.default_from"):
            self.set("email.resend.default_from", default_from, category="email")
        if api_key and not self.get("email.resend.api_key"):
            self.set(
                "email.resend.api_key",
                api_key,
                category="email",
                metadata={"source": "packaged_runtime_defaults"},
            )

    # --- Runtime Registry Methods (Database Persistent) ---
    # Note: Using local imports inside methods to avoid circular dependencies with db.py

    @overload
    @staticmethod
    def get(key: str) -> object | None:
        ...

    @overload
    @staticmethod
    def get(key: str, default: T) -> T:
        ...

    @staticmethod
    def get(key: str, default: object = None) -> object:
        """Retrieves a configuration value from the database."""
        from sqlmodel import select
        from app.models.database import AppConfig
        from app.core.db import get_session

        with get_session() as session:
            statement = select(AppConfig).where(AppConfig.key == key)
            record = session.exec(statement).first()
            return record.value if record else default

    @staticmethod
    def set(
        key: str,
        value: object,
        category: str = "general",
        metadata: Optional[dict[str, object]] = None,
    ) -> "AppConfig":
        """Sets a configuration value in the database."""
        from datetime import datetime, timezone
        from sqlmodel import select
        from app.models.database import AppConfig
        from app.core.db import get_session

        with get_session() as session:
            statement = select(AppConfig).where(AppConfig.key == key)
            record = session.exec(statement).first()

            if record:
                record.value = value
                record.category = category
                if metadata:
                    record.metadata_.update(metadata)
                record.updated_at = datetime.now(timezone.utc)
            else:
                record = AppConfig(
                    key=key,
                    value=value,
                    category=category,
                    metadata_=metadata or {},
                    updated_at=datetime.now(timezone.utc)
                )
                session.add(record)

            session.commit()
            session.refresh(record)
            return record

    def get_provider_llm_config(self, provider: str) -> dict[str, str]:
        """Consolidated fetcher for provider-specific LLM settings."""
        # Database stores structure like {"api_key": "...", "base_url": "..."}
        raw_value = self.get(f"llm.{provider}", {})
        raw = raw_value if isinstance(raw_value, dict) else {}

        # Explicitly filter for PydanticAI Provider supported keys
        valid_keys = {"api_key", "base_url"}

        config: dict[str, str] = {}
        for k in valid_keys:
            val = raw.get(k)
            # Only pass values that are non-empty strings (after stripping)
            # This allows PydanticAI to use defaults if the field is empty in Ferryman
            if val and str(val).strip():
                config[k] = str(val)

        return config

    @staticmethod
    def get_llm_provider_catalog() -> dict[str, dict[str, object]]:
        """Returns the provider metadata used by the settings UI and model registry."""
        return {
            "gemini": {
                "label": "Gemini",
                "placeholder_base_url": "https://generativelanguage.googleapis.com",
                "list_mode": "gemini",
                "models": [
                    "gemini-3.1-pro-preview",
                    "gemini-3.1-flash-lite-preview",
                    "gemini-3-flash-preview",
                ],
            },
            "openai": {
                "label": "OpenAI",
                "placeholder_base_url": "https://api.openai.com/v1",
                "list_mode": "openai_compatible",
                "models": [
                    "gpt-5.4-pro",
                    "gpt-5.4-thinking",
                    "gpt-5.3-instant",
                    "gpt-5.3-codex",
                    "gpt-4o",
                    "gpt-4o-mini",
                ],
            },
            "anthropic": {
                "label": "Claude",
                "placeholder_base_url": "https://api.anthropic.com/v1",
                "list_mode": "anthropic",
                "models": [
                    "claude-opus-4.6",
                    "claude-sonnet-4.6",
                    "claude-haiku-4.5",
                    "claude-3-5-sonnet-latest",
                ],
            },
            "qwen": {
                "label": "Qwen",
                "placeholder_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "list_mode": "openai_compatible",
                "models": [
                    "qwen3.6-plus",
                    "qwen-max",
                    "qwen-plus",
                    "qwen3.5-plus",
                    "qwen3.5-omni-plus",
                ],
            },
            "deepseek": {
                "label": "DeepSeek",
                "placeholder_base_url": "https://api.deepseek.com",
                "list_mode": "openai_compatible",
                "models": [
                    "deepseek-v4-pro",
                    "deepseek-v4-flash",
                ],
            },
            "kimi": {
                "label": "Kimi",
                "placeholder_base_url": "https://api.moonshot.cn/v1",
                "list_mode": "openai_compatible",
                "models": [
                    "kimi-k2.6",
                    "kimi-k2.5",
                    "kimi-k2-thinking",
                    "kimi-k2-thinking-turbo",
                    "kimi-k2-0905-preview",
                    "kimi-k2-turbo-preview",
                    "moonshot-v1-128k",
                ],
            },
            "doubao": {
                "label": "Doubao",
                "placeholder_base_url": "https://ark.cn-beijing.volces.com/api/v3",
                "list_mode": "openai_compatible",
                "models": [
                    "doubao-seed-2-0-pro-260215",
                    "doubao-seed-2-0-lite-260215",
                    "doubao-seed-2-0-mini-260215",
                    "doubao-seed-2-0-code-preview-260215",
                ],
            },
            "custom": {
                "label": "Custom",
                "placeholder_base_url": "https://api.example.com/v1",
                "placeholder_model": "your-model-name",
                "supports_model": True,
                "list_mode": "openai_compatible",
                "models": [],
            },
        }

    def get_active_model_id(self) -> Optional[str]:
        """Returns the globally active model identifier if one has been selected."""
        active_model = self.get("system.llm.active_model")
        if active_model is None:
            return None

        normalized = str(active_model).strip()
        return normalized or None

    def get_model_readiness(self) -> dict[str, object]:
        """Returns whether the chat experience has a usable active model."""
        provider_catalog = self.get_llm_provider_catalog()
        active_model_id = self.get_active_model_id()

        def load_provider_config(provider: str) -> dict[str, object]:
            raw = self.get(f"llm.{provider}", {})
            return cast(dict[str, object], raw) if isinstance(raw, dict) else {}

        configured_provider_count = 0
        for provider in provider_catalog:
            provider_config = load_provider_config(provider)
            api_key = str(provider_config.get("api_key", "")).strip()
            base_url = str(provider_config.get("base_url", "")).strip()
            if provider == "custom":
                if api_key and base_url:
                    configured_provider_count += 1
            elif api_key:
                configured_provider_count += 1

        if not active_model_id:
            issue_code = "active_model_invalid" if configured_provider_count else "no_runnable_model"
            return {
                "ready": False,
                "active_model": None,
                "issue": {"code": issue_code},
            }

        if ":" not in active_model_id:
            return {
                "ready": False,
                "active_model": active_model_id,
                "issue": {"code": "active_model_invalid"},
            }

        provider, model_name = (part.strip() for part in active_model_id.split(":", 1))
        if not provider or not model_name or provider not in provider_catalog:
            return {
                "ready": False,
                "active_model": active_model_id,
                "issue": {"code": "active_model_invalid"},
            }

        provider_config = load_provider_config(provider)
        api_key = str(provider_config.get("api_key", "")).strip()
        if not api_key:
            return {
                "ready": False,
                "active_model": active_model_id,
                "issue": {
                    "code": "missing_api_key",
                    "provider": provider,
                    "missing": ["api_key"],
                },
            }

        if provider == "custom":
            base_url = str(provider_config.get("base_url", "")).strip()
            if not base_url:
                return {
                    "ready": False,
                    "active_model": active_model_id,
                    "issue": {
                        "code": "missing_base_url",
                        "provider": provider,
                        "missing": ["base_url"],
                    },
                }
            if not model_name:
                return {
                    "ready": False,
                    "active_model": active_model_id,
                    "issue": {"code": "active_model_invalid"},
                }

        return {
            "ready": True,
            "active_model": active_model_id,
            "issue": None,
        }

    @staticmethod
    def list_by_category(category: str) -> list["AppConfig"]:
        """Lists all configurations in a given category."""
        from sqlmodel import select
        from app.models.database import AppConfig
        from app.core.db import get_session

        with get_session() as session:
            statement = select(AppConfig).where(AppConfig.category == category)
            return list(session.exec(statement).all())

    @staticmethod
    def get_available_models() -> dict[str, list[str]]:
        """Returns a registry of available models for configured providers."""
        catalog = Settings.get_llm_provider_catalog()
        available_models: dict[str, list[str]] = {}

        for provider, definition in catalog.items():
            stored_value = Settings.get(f"llm.{provider}", {})
            stored_config = stored_value if isinstance(stored_value, dict) else {}
            api_key = str(stored_config.get("api_key", "")).strip()
            stored_base_url = str(stored_config.get("base_url", "")).strip()
            default_base_url = (
                ""
                if definition.get("requires_base_url")
                else str(definition.get("placeholder_base_url", ""))
            )
            base_url = stored_base_url or default_base_url
            configured_model = str(stored_config.get("model", "")).strip()

            provider_models: list[str] = []

            if provider == "custom":
                if api_key and base_url and configured_model:
                    provider_models = [configured_model]
            elif api_key and base_url:
                try:
                    provider_models = Settings._fetch_provider_models(
                        provider=provider,
                        api_key=api_key,
                        base_url=base_url,
                        list_mode=str(definition.get("list_mode", "openai_compatible")),
                    )
                except ModelListEndpointUnavailable as exc:
                    logger.exception(f"Model list endpoint unavailable for provider {provider}: {exc}")
                    provider_models = []
                except Exception as exc:
                    logger.exception(f"Failed to fetch models for provider {provider}: {exc}")
                    provider_models = []

            deduped_models = list(dict.fromkeys(model for model in provider_models if model))
            if deduped_models:
                available_models[provider] = deduped_models

        active_model_id = Settings().get_active_model_id()
        if active_model_id and ":" in active_model_id:
            provider, model_name = active_model_id.split(":", 1)
            model_name = model_name.strip()
            if provider in available_models and model_name and model_name not in available_models[provider]:
                available_models[provider].append(model_name)

        return available_models

    @staticmethod
    def _fetch_provider_models(provider: str, api_key: str, base_url: str, list_mode: str) -> list[str]:
        try:
            if list_mode == "anthropic":
                return Settings._fetch_anthropic_models(api_key=api_key, base_url=base_url)
            if list_mode == "gemini":
                return Settings._fetch_gemini_models(api_key=api_key, base_url=base_url)
            model_ids = Settings._fetch_openai_compatible_models(api_key=api_key, base_url=base_url)
            if provider == "openai":
                return Settings._filter_openai_models(model_ids)
            if provider == "qwen":
                return Settings._filter_qwen_models(model_ids)
            if provider == "deepseek":
                return Settings._filter_deepseek_models(model_ids)
            if provider == "kimi":
                return Settings._filter_kimi_models(model_ids)
            if provider == "doubao":
                return Settings._filter_doubao_models(model_ids)
            return Settings._filter_chat_model_ids(model_ids)
        except HTTPError as exc:
            if exc.code in {404, 405, 501}:
                raise ModelListEndpointUnavailable(f"HTTP {exc.code}") from exc
            raise

    @staticmethod
    def validate_provider_config(provider: str, api_key: str, base_url: str = "", model: str = "") -> Optional[str]:
        catalog = Settings.get_llm_provider_catalog()
        definition = catalog.get(provider)
        if not definition:
            return f"Unsupported provider: {provider}"

        normalized_api_key = str(api_key or "").strip()
        normalized_base_url = str(base_url or "").strip()
        normalized_model = str(model or "").strip()

        if not normalized_api_key:
            return None

        effective_base_url = normalized_base_url or (
            "" if definition.get("requires_base_url") else str(definition.get("placeholder_base_url", ""))
        )
        if provider == "custom" and not effective_base_url:
            return "Base URL is required."
        if provider == "custom" and not normalized_model:
            return "Model is required."
        if definition.get("requires_base_url") and not effective_base_url:
            return "Base URL is required."

        try:
            if provider == "custom":
                Settings._probe_openai_compatible_chat_model(
                    api_key=normalized_api_key,
                    base_url=effective_base_url,
                    model=normalized_model,
                )
            else:
                Settings._fetch_provider_models(
                    provider=provider,
                    api_key=normalized_api_key,
                    base_url=effective_base_url,
                    list_mode=str(definition.get("list_mode", "openai_compatible")),
                )
        except ModelListEndpointUnavailable:
            return "Provider does not expose a usable models endpoint for validation."
        except HTTPError as exc:
            details = ""
            try:
                body = exc.read().decode("utf-8", errors="replace").strip()
                if body:
                    details = f" {body[:300]}"
            except Exception:
                details = ""
            return f"API key validation failed (HTTP {exc.code}).{details}".strip()
        except Exception as exc:
            return f"API key validation failed: {exc}"

        return None

    @staticmethod
    def _http_get_json(
        url: str,
        headers: Optional[dict[str, str]] = None,
        query: Optional[dict[str, str]] = None,
    ) -> dict[str, object]:
        if query:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}{urlencode(query)}"

        request = Request(url, headers=headers or {}, method="GET")
        with urlopen(request, timeout=5) as response:
            return cast(dict[str, object], json.loads(response.read().decode("utf-8")))

    @staticmethod
    def _http_post_json(
        url: str,
        payload: dict[str, object],
        headers: Optional[dict[str, str]] = None,
        query: Optional[dict[str, str]] = None,
    ) -> dict[str, object]:
        if query:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}{urlencode(query)}"

        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers or {},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            return cast(dict[str, object], json.loads(response.read().decode("utf-8")))

    @staticmethod
    def _build_openai_compatible_models_url(base_url: str) -> str:
        normalized = base_url.rstrip("/")
        return normalized if normalized.endswith("/models") else f"{normalized}/models"

    @staticmethod
    def _build_openai_compatible_chat_completions_url(base_url: str) -> str:
        normalized = base_url.rstrip("/")
        return normalized if normalized.endswith("/chat/completions") else f"{normalized}/chat/completions"

    @staticmethod
    def _build_gemini_models_url(base_url: str) -> str:
        normalized = base_url.rstrip("/")
        if normalized.endswith("/models"):
            return normalized
        if normalized.endswith("/v1beta"):
            return f"{normalized}/models"
        return f"{normalized}/v1beta/models"

    @staticmethod
    def _filter_chat_model_ids(model_ids: list[str]) -> list[str]:
        excluded_keywords = (
            "embedding",
            "embed",
            "moderation",
            "image",
            "vision-preview",
            "whisper",
            "transcribe",
            "tts",
            "speech",
            "rerank",
        )
        filtered = [
            model_id
            for model_id in model_ids
            if model_id and not any(keyword in model_id.lower() for keyword in excluded_keywords)
        ]
        return Settings._dedupe_preserve_order(filtered)

    @staticmethod
    def _dedupe_preserve_order(model_ids: list[str]) -> list[str]:
        return list(dict.fromkeys(model for model in model_ids if model))

    @staticmethod
    def _extract_numeric_version(value: str) -> tuple[int, ...]:
        match = re.search(r"(\d+(?:[.-]\d+)*)", value)
        if not match:
            return ()
        return tuple(int(part) for part in re.split(r"[.-]", match.group(1)) if part.isdigit())

    @staticmethod
    def _model_date_score(model_id: str) -> tuple[int, ...]:
        normalized = model_id.lower()
        full_date = re.search(r"(20\d{2})[-.]?(\d{2})[-.]?(\d{2})", normalized)
        if full_date:
            return tuple(int(part) for part in full_date.groups())

        short_date = re.search(r"(?<!\d)(\d{2})(\d{2})(\d{2})(?!\d)", normalized)
        if short_date:
            year, month, day = (int(part) for part in short_date.groups())
            return (2000 + year, month, day)

        return ()

    @staticmethod
    def _extract_gpt_version(model_id: str) -> tuple[int, ...]:
        normalized = model_id.lower().strip()
        match = re.match(r"gpt-(\d+)(?:\.(\d+))?", normalized)
        if not match:
            return ()

        major = int(match.group(1))
        minor = int(match.group(2)) if match.group(2) else None
        if major == 35 and minor is None:
            return (3, 5)
        if minor is None:
            return (major,)
        return (major, minor)

    @staticmethod
    def _variant_priority(model_id: str, variants: tuple[str, ...]) -> int:
        normalized = model_id.lower()
        for index, variant in enumerate(variants):
            if re.search(rf"(?:^|-){re.escape(variant)}(?:-|$)", normalized):
                return index
        return len(variants)

    @staticmethod
    def _filter_openai_models(model_ids: list[str], limit: int = 6) -> list[str]:
        excluded_keywords = (
            "audio",
            "canvas",
            "computer-use",
            "dall-e",
            "embedding",
            "image",
            "moderation",
            "realtime",
            "search",
            "speech",
            "tts",
            "transcribe",
            "vision",
            "whisper",
        )
        candidates = []
        for model_id in model_ids:
            normalized = model_id.lower().strip()
            if not normalized.startswith(("gpt-", "o")):
                continue
            if any(keyword in normalized for keyword in excluded_keywords):
                continue
            version = Settings._extract_gpt_version(normalized)
            if not version:
                continue
            candidates.append((version, Settings._model_date_score(normalized), model_id))

        if not candidates:
            return []

        latest_major = max(candidate[0][0] for candidate in candidates)
        latest_family = [
            candidate
            for candidate in candidates
            if candidate[0][0] == latest_major
        ]
        latest_family.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return Settings._dedupe_preserve_order([item[2] for item in latest_family])[:limit]

    @staticmethod
    def _has_trailing_build_or_date_variant(model_id: str) -> bool:
        normalized = model_id.lower().strip()
        return bool(
            re.search(r"-\d{3,4}$", normalized)
            or re.search(r"-\d{4}-\d{2}-\d{2}$", normalized)
        )

    @staticmethod
    def _filter_gemini_models(models: list[dict[str, object]]) -> list[str]:
        allowed_models: list[str] = []
        excluded_keywords = (
            "audio",
            "live",
            "computer-use",
            "image",
        )

        for item in models:
            if not isinstance(item, dict):
                continue

            supported_methods = {
                str(method).strip()
                for method in item.get("supportedGenerationMethods", [])
                if str(method).strip()
            }
            if "generateContent" not in supported_methods:
                continue

            model_id = str(item.get("baseModelId", "")).strip()
            if not model_id:
                model_id = str(item.get("name", "")).strip()
                if model_id.startswith("models/"):
                    model_id = model_id.split("/", 1)[1]

            normalized_model_id = model_id.lower()
            if not normalized_model_id.startswith("gemini-"):
                continue
            if any(keyword in normalized_model_id for keyword in excluded_keywords):
                continue
            if Settings._has_trailing_build_or_date_variant(normalized_model_id):
                continue

            allowed_models.append(model_id)

        return sorted(dict.fromkeys(allowed_models))

    @staticmethod
    def _filter_qwen_models(model_ids: list[str]) -> list[str]:
        excluded_keywords = (
            "embedding",
            "embed",
            "audio",
            "image",
            "vision",
            "vl",
            "tts",
            "asr",
            "rerank",
            "realtime",
            "livetranslate",
            "deep-research",
            "deep-search",
            "character",
            "math",
            "mt-",
            "coder",
        )
        product_pattern = re.compile(
            r"^qwen(?:(?P<version>\d+(?:\.\d+)?)?)?"
            r"-(?P<variant>max|plus|turbo|flash|omni-plus|omni-flash)"
            r"(?:-\d{4}-\d{2}-\d{2})?$"
        )

        candidate_by_alias: dict[str, tuple[tuple[int, ...], int, bool, tuple[int, ...], str]] = {}
        for model_id in model_ids:
            normalized = model_id.lower().strip()
            match = product_pattern.match(normalized)
            if not match:
                continue
            if any(keyword in normalized for keyword in excluded_keywords):
                continue
            family = Settings._extract_numeric_version(match.group("version") or "0")
            variant_rank = {
                "plus": 0,
                "omni-plus": 1,
                "max": 2,
                "flash": 3,
                "omni-flash": 4,
                "turbo": 5,
            }.get(match.group("variant"), 99)
            date_score = Settings._model_date_score(normalized)
            canonical = re.sub(r"-\d{4}-\d{2}-\d{2}$", "", normalized)
            has_date_suffix = bool(date_score)
            candidate = (family, variant_rank, has_date_suffix, date_score, model_id)
            existing = candidate_by_alias.get(canonical)
            if (
                existing is None
                or (existing[2] and not has_date_suffix)
                or (existing[2] == has_date_suffix and date_score > existing[3])
            ):
                candidate_by_alias[canonical] = candidate

        if not candidate_by_alias:
            return []

        candidates = list(candidate_by_alias.values())
        candidates.sort(key=lambda item: (item[0], -item[1], item[3]), reverse=True)
        return Settings._dedupe_preserve_order([item[4] for item in candidates])[:6]

    @staticmethod
    def _filter_kimi_models(model_ids: list[str]) -> list[str]:
        deprecated_models = {
            "kimi-latest",
            "kimi-thinking-preview",
        }
        excluded_keywords = (
            "embedding",
            "embed",
            "vision",
            "image",
            "audio",
            "video",
            "tts",
            "asr",
            "rerank",
        )

        candidates = []
        for model_id in model_ids:
            normalized = model_id.lower().strip()
            if not normalized or normalized in deprecated_models:
                continue
            if not normalized.startswith(("kimi-k", "moonshot-v")):
                continue
            if any(keyword in normalized for keyword in excluded_keywords):
                continue
            kimi_version = re.search(r"kimi-k(\d+(?:\.\d+)?)", normalized)
            moonshot_version = re.search(r"moonshot-v(\d+(?:\.\d+)?)", normalized)
            version_source = kimi_version or moonshot_version
            family = tuple(int(part) for part in version_source.group(1).split(".")) if version_source else ()
            candidates.append((family, Settings._model_date_score(normalized), model_id))

        if not candidates:
            return []

        latest_kimi = [candidate for candidate in candidates if candidate[2].lower().startswith("kimi-k")]
        selected = latest_kimi or candidates
        selected.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return Settings._dedupe_preserve_order([item[2] for item in selected])[:3]

    @staticmethod
    def _filter_deepseek_models(model_ids: list[str]) -> list[str]:
        preferred_order = {
            "deepseek-v4-pro": 0,
            "deepseek-v4-flash": 1,
            "deepseek-chat": 2,
            "deepseek-reasoner": 3,
        }
        excluded_keywords = (
            "embedding",
            "embed",
            "image",
            "vision",
            "audio",
            "tts",
            "asr",
            "rerank",
            "ocr",
            "distill",
        )

        candidates = []
        for model_id in model_ids:
            normalized = model_id.lower().strip()
            if not normalized.startswith("deepseek-"):
                continue
            if any(keyword in normalized for keyword in excluded_keywords):
                continue
            rank = preferred_order.get(normalized, 99)
            candidates.append((rank, Settings._model_date_score(normalized), model_id))

        candidates.sort(key=lambda item: (item[0], tuple(-part for part in item[1])))
        return Settings._dedupe_preserve_order([item[2] for item in candidates])[:4]

    @staticmethod
    def _filter_doubao_models(model_ids: list[str]) -> list[str]:
        excluded_keywords = (
            "embedding",
            "embed",
            "image",
            "seedream",
            "seededit",
            "speech",
            "tts",
            "asr",
            "audio",
            "video-generation",
            "rerank",
        )

        candidates = []
        for model_id in model_ids:
            normalized = model_id.lower().strip()
            if not normalized.startswith("doubao-seed-"):
                continue
            if any(keyword in normalized for keyword in excluded_keywords):
                continue
            match = re.match(r"doubao-seed-(\d+)-(\d+)", normalized)
            if not match:
                continue
            family = (int(match.group(1)), int(match.group(2)))
            candidates.append((
                family,
                Settings._variant_priority(normalized, ("pro", "lite", "mini", "code")),
                Settings._model_date_score(normalized),
                model_id,
            ))

        if not candidates:
            return []

        latest_family = max(candidate[0] for candidate in candidates)
        selected = [candidate for candidate in candidates if candidate[0] == latest_family]
        selected.sort(key=lambda item: (item[1], tuple(-part for part in item[2])))
        return Settings._dedupe_preserve_order([item[3] for item in selected])[:6]

    @staticmethod
    def _fetch_openai_compatible_models(api_key: str, base_url: str) -> list[str]:
        payload = Settings._http_get_json(
            Settings._build_openai_compatible_models_url(base_url),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        model_ids = []
        data = payload.get("data", [])
        for item in data if isinstance(data, list) else []:
            model_id = item.get("id") if isinstance(item, dict) else None
            if isinstance(model_id, str):
                model_ids.append(model_id.strip())
        return model_ids

    @staticmethod
    def _fetch_anthropic_models(api_key: str, base_url: str) -> list[str]:
        url = Settings._build_openai_compatible_models_url(base_url)
        fallback_headers = (
            {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        last_error: Exception | None = None

        for headers in fallback_headers:
            try:
                payload = Settings._http_get_json(url, headers=headers)
                break
            except HTTPError as exc:
                last_error = exc
                if exc.code in {401, 403}:
                    continue
                raise
            except JSONDecodeError as exc:
                last_error = exc
                continue
        else:
            if isinstance(last_error, HTTPError):
                raise last_error
            raise ModelListEndpointUnavailable("Anthropic models endpoint did not return JSON")

        model_ids = []
        data = payload.get("data", [])
        for item in data if isinstance(data, list) else []:
            model_id = item.get("id") if isinstance(item, dict) else None
            if isinstance(model_id, str):
                model_ids.append(model_id.strip())
        return Settings._filter_chat_model_ids(model_ids)

    @staticmethod
    def _fetch_gemini_models(api_key: str, base_url: str) -> list[str]:
        payload = Settings._http_get_json(
            Settings._build_gemini_models_url(base_url),
            query={"key": api_key},
        )
        models = payload.get("models", [])
        return Settings._filter_gemini_models(cast(list[dict[str, object]], models) if isinstance(models, list) else [])

    @staticmethod
    def _probe_openai_compatible_chat_model(api_key: str, base_url: str, model: str) -> None:
        Settings._http_post_json(
            Settings._build_openai_compatible_chat_completions_url(base_url),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            payload={
                "model": model,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
                "temperature": 0,
            },
        )


@lru_cache()
def get_settings() -> Settings:
    """获取应用配置实例（单例模式）"""
    return Settings()
