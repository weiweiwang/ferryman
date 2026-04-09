import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    log_level: str = "DEBUG"

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

    # --- Runtime Registry Methods (Database Persistent) ---
    # Note: Using local imports inside methods to avoid circular dependencies with db.py

    @staticmethod
    def get(key: str, default: Any = None) -> Any:
        """Retrieves a configuration value from the database."""
        from sqlmodel import select
        from app.models.database import AppConfig
        from app.core.db import get_session

        with get_session() as session:
            statement = select(AppConfig).where(AppConfig.key == key)
            record = session.exec(statement).first()
            return record.value if record else default

    @staticmethod
    def set(key: str, value: Any, category: str = "general", metadata: Optional[Dict] = None) -> Any:
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

    def get_provider_llm_config(self, provider: str) -> Dict[str, Any]:
        """Consolidated fetcher for provider-specific LLM settings."""
        # Database stores structure like {"api_key": "...", "base_url": "..."}
        raw = self.get(f"llm.{provider}", {})

        # Explicitly filter for PydanticAI Provider supported keys
        valid_keys = {"api_key", "base_url"}

        config = {}
        for k in valid_keys:
            val = raw.get(k)
            # Only pass values that are non-empty strings (after stripping)
            # This allows PydanticAI to use defaults if the field is empty in Ferryman
            if val and str(val).strip():
                config[k] = val

        return config

    def get_active_model_id(self) -> str:
        """Returns the globally active model identifier."""
        return self.get("system.llm.active_model", "gemini:gemini-3-flash-preview")

    @staticmethod
    def list_by_category(category: str) -> List[Any]:
        """Lists all configurations in a given category."""
        from sqlmodel import select
        from app.models.database import AppConfig
        from app.core.db import get_session

        with get_session() as session:
            statement = select(AppConfig).where(AppConfig.category == category)
            return list(session.exec(statement).all())

    @staticmethod
    def get_available_models() -> Dict[str, List[str]]:
        """Returns a registry of modern LLM models by provider."""
        return {
            "gemini": [
                "gemini-3.1-pro-preview",
                "gemini-3.1-flash-lite-preview",
                "gemini-3-flash-preview",
                "gemini-2.5-pro",
                "gemini-2.5-flash",
            ],
            "openai": [
                "gpt-5.4-pro",
                "gpt-5.4-thinking",
                "gpt-5.3-instant",
                "gpt-5.3-codex",
                "gpt-4o",
                "gpt-4o-mini",
            ],
            "anthropic": [
                "claude-opus-4.6",
                "claude-sonnet-4.6",
                "claude-haiku-4.5",
                "claude-3-5-sonnet-latest",
            ]
        }


@lru_cache()
def get_settings() -> Settings:
    """获取应用配置实例（单例模式）"""
    return Settings()
