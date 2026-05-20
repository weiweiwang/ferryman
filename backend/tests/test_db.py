import json
from datetime import datetime, timezone

from sqlalchemy import text

from app.core.db import (
    DOUBAO_PROVIDER_REMOVAL_MIGRATION_KEY,
    MODEL_ROUTING_CLASSIFIER_MODEL_MIGRATION_KEY,
    MODEL_ROUTING_FLASH_DEFAULT_MIGRATION_KEY,
    MODEL_ROUTING_THRESHOLD_MIGRATION_KEY,
    UTC_DATETIME_MIGRATION_KEY,
    migrate_datetime_columns_to_utc_storage,
    migrate_model_routing_classifier_model_default,
    migrate_model_routing_flash_default,
    migrate_model_routing_threshold_default,
    migrate_remove_doubao_provider_config,
)


def test_utc_datetime_migration_runs_once_and_records_marker(session):
    migrate_datetime_columns_to_utc_storage()
    migrate_datetime_columns_to_utc_storage()
    session.expire_all()

    marker_rows = session.execute(
        text("SELECT key, value FROM app_configs WHERE key = :key"),
        {"key": UTC_DATETIME_MIGRATION_KEY},
    ).all()
    assert marker_rows == [(UTC_DATETIME_MIGRATION_KEY, json.dumps(True))]


def test_model_routing_threshold_migration_updates_legacy_default(session):
    legacy_config = {
        "enabled": True,
        "classifier_model": "gemini:gemini-3.1-flash-lite",
        "flash_model": "gemini:gemini-3-flash-preview",
        "default_model": "system.llm.active_model",
        "classifier_threshold": 50,
        "classifier_timeout_seconds": 8,
    }
    session.execute(
        text(
            """
            INSERT INTO app_configs (key, value, category, metadata, updated_at)
            VALUES (:key, :value, :category, :metadata, :updated_at)
            """
        ),
        {
            "key": "system.llm.routing",
            "value": json.dumps(legacy_config),
            "category": "system",
            "metadata": json.dumps({}),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    session.commit()

    migrate_model_routing_threshold_default()
    migrate_model_routing_threshold_default()
    session.expire_all()

    routing_value = session.execute(
        text("SELECT value FROM app_configs WHERE key = :key"),
        {"key": "system.llm.routing"},
    ).scalar_one()
    assert json.loads(routing_value)["classifier_threshold"] == 80

    marker_rows = session.execute(
        text("SELECT key, value FROM app_configs WHERE key = :key"),
        {"key": MODEL_ROUTING_THRESHOLD_MIGRATION_KEY},
    ).all()
    assert marker_rows == [(MODEL_ROUTING_THRESHOLD_MIGRATION_KEY, json.dumps(True))]


def test_model_routing_flash_migration_updates_legacy_default(session):
    legacy_config = {
        "enabled": True,
        "classifier_model": "gemini:gemini-3.1-flash-lite",
        "flash_model": "gemini:gemini-3-flash-preview",
        "default_model": "system.llm.active_model",
        "classifier_threshold": 80,
        "classifier_timeout_seconds": 8,
    }
    session.execute(
        text(
            """
            INSERT INTO app_configs (key, value, category, metadata, updated_at)
            VALUES (:key, :value, :category, :metadata, :updated_at)
            """
        ),
        {
            "key": "system.llm.routing",
            "value": json.dumps(legacy_config),
            "category": "system",
            "metadata": json.dumps({}),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    session.commit()

    migrate_model_routing_flash_default()
    migrate_model_routing_flash_default()
    session.expire_all()

    routing_value = session.execute(
        text("SELECT value FROM app_configs WHERE key = :key"),
        {"key": "system.llm.routing"},
    ).scalar_one()
    routing_config = json.loads(routing_value)
    assert routing_config["flash_model"] == "deepseek:deepseek-v4-flash"
    assert routing_config["flash_fallback_model"] == "gemini:gemini-3-flash-preview"

    marker_rows = session.execute(
        text("SELECT key, value FROM app_configs WHERE key = :key"),
        {"key": MODEL_ROUTING_FLASH_DEFAULT_MIGRATION_KEY},
    ).all()
    assert marker_rows == [(MODEL_ROUTING_FLASH_DEFAULT_MIGRATION_KEY, json.dumps(True))]


def test_model_routing_classifier_model_migration_updates_legacy_preview_model(session):
    legacy_config = {
        "enabled": True,
        "classifier_model": "gemini:gemini-3.1-flash-lite-preview",
        "flash_model": "deepseek:deepseek-v4-flash",
        "flash_fallback_model": "gemini:gemini-3-flash-preview",
        "default_model": "system.llm.active_model",
        "classifier_threshold": 80,
        "classifier_timeout_seconds": 8,
    }
    session.execute(
        text(
            """
            INSERT INTO app_configs (key, value, category, metadata, updated_at)
            VALUES (:key, :value, :category, :metadata, :updated_at)
            """
        ),
        {
            "key": "system.llm.routing",
            "value": json.dumps(legacy_config),
            "category": "system",
            "metadata": json.dumps({}),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    session.commit()

    migrate_model_routing_classifier_model_default()
    migrate_model_routing_classifier_model_default()
    session.expire_all()

    routing_value = session.execute(
        text("SELECT value FROM app_configs WHERE key = :key"),
        {"key": "system.llm.routing"},
    ).scalar_one()
    routing_config = json.loads(routing_value)
    assert routing_config["classifier_model"] == "gemini:gemini-3.1-flash-lite"
    assert routing_config["flash_model"] == "deepseek:deepseek-v4-flash"

    marker_rows = session.execute(
        text("SELECT key, value FROM app_configs WHERE key = :key"),
        {"key": MODEL_ROUTING_CLASSIFIER_MODEL_MIGRATION_KEY},
    ).all()
    assert marker_rows == [(MODEL_ROUTING_CLASSIFIER_MODEL_MIGRATION_KEY, json.dumps(True))]


def test_remove_doubao_provider_config_migration_deletes_config_and_active_model(session):
    rows = [
        ("llm.doubao", {"api_key": "sk-doubao"}, "llm"),
        ("system.llm.active_model", "doubao:doubao-seed-2-0-pro-260215", "system"),
        ("llm.openai", {"api_key": "sk-openai"}, "llm"),
    ]
    for key, value, category in rows:
        session.execute(
            text(
                """
                INSERT INTO app_configs (key, value, category, metadata, updated_at)
                VALUES (:key, :value, :category, :metadata, :updated_at)
                """
            ),
            {
                "key": key,
                "value": json.dumps(value),
                "category": category,
                "metadata": json.dumps({}),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    session.commit()

    migrate_remove_doubao_provider_config()
    migrate_remove_doubao_provider_config()
    session.expire_all()

    removed_keys = session.execute(
        text("SELECT key FROM app_configs WHERE key IN (:doubao_key, :active_key)"),
        {
            "doubao_key": "llm.doubao",
            "active_key": "system.llm.active_model",
        },
    ).all()
    assert removed_keys == []

    openai_value = session.execute(
        text("SELECT value FROM app_configs WHERE key = :key"),
        {"key": "llm.openai"},
    ).scalar_one()
    assert json.loads(openai_value) == {"api_key": "sk-openai"}

    marker_rows = session.execute(
        text("SELECT key, value FROM app_configs WHERE key = :key"),
        {"key": DOUBAO_PROVIDER_REMOVAL_MIGRATION_KEY},
    ).all()
    assert marker_rows == [(DOUBAO_PROVIDER_REMOVAL_MIGRATION_KEY, json.dumps(True))]
