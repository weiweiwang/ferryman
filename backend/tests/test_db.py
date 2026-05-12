import json
from datetime import datetime, timezone

from sqlalchemy import text

from app.core.db import (
    MODEL_ROUTING_THRESHOLD_MIGRATION_KEY,
    UTC_DATETIME_MIGRATION_KEY,
    migrate_datetime_columns_to_explicit_utc_strings,
    migrate_model_routing_threshold_default,
)


def test_utc_datetime_migration_runs_once_and_records_marker(session):
    migrate_datetime_columns_to_explicit_utc_strings()
    migrate_datetime_columns_to_explicit_utc_strings()
    session.expire_all()

    marker_rows = session.execute(
        text("SELECT key, value FROM app_configs WHERE key = :key"),
        {"key": UTC_DATETIME_MIGRATION_KEY},
    ).all()
    assert marker_rows == [(UTC_DATETIME_MIGRATION_KEY, json.dumps(True))]


def test_model_routing_threshold_migration_updates_legacy_default(session):
    legacy_config = {
        "enabled": True,
        "classifier_model": "gemini:gemini-3.1-flash-lite-preview",
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
