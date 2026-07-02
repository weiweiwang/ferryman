from __future__ import annotations

import json
import logging
import os
import sys
from functools import lru_cache
from json import JSONDecodeError
from pathlib import Path
from typing import TYPE_CHECKING, Optional, TypeVar, overload

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from app.models.database import AppConfigModel

logger = logging.getLogger(__name__)
T = TypeVar("T")


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
    model_pricing_refresh_enabled: bool = Field(
        default=True,
        validation_alias="FERRYMAN_MODEL_PRICING_REFRESH_ENABLED",
    )
    llm_request_limit: int = Field(
        default=200,
        validation_alias=AliasChoices("FERRYMAN_LLM_REQUEST_LIMIT", "LLM_REQUEST_LIMIT"),
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
        return payload if isinstance(payload, dict) else {}

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
        from app.models.database import AppConfigModel
        from app.core.db import get_session

        with get_session() as session:
            statement = select(AppConfigModel).where(AppConfigModel.key == key)
            record = session.exec(statement).first()
            return record.value if record else default

    @staticmethod
    def set(
        key: str,
        value: object,
        category: str = "general",
        metadata: Optional[dict[str, object]] = None,
    ) -> "AppConfigModel":
        """Sets a configuration value in the database."""
        from datetime import datetime, timezone
        from sqlmodel import select
        from app.models.database import AppConfigModel
        from app.core.db import get_session

        with get_session() as session:
            statement = select(AppConfigModel).where(AppConfigModel.key == key)
            record = session.exec(statement).first()

            if record:
                record.value = value
                record.category = category
                if metadata:
                    record.metadata_.update(metadata)
                record.updated_at = datetime.now(timezone.utc)
            else:
                record = AppConfigModel(
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

    @staticmethod
    def list_by_category(category: str) -> list["AppConfigModel"]:
        """List persisted configuration values by category."""
        from sqlmodel import select
        from app.models.database import AppConfigModel
        from app.core.db import get_session

        with get_session() as session:
            statement = select(AppConfigModel).where(AppConfigModel.category == category)
            return list(session.exec(statement).all())


@lru_cache()
def get_settings() -> Settings:
    """获取应用配置实例（单例模式）"""
    return Settings()
