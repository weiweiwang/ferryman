import json
import logging
from datetime import datetime, timezone
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import inspect
from sqlmodel import SQLModel, create_engine, Session as DBSession, text

from app.core.config import get_settings
from app.core.utc_datetime import format_utc_datetime, parse_utc_datetime

logger = logging.getLogger(__name__)

db_path = get_settings().db_path.absolute()
db_path.parent.mkdir(parents=True, exist_ok=True)


engine = create_engine(
    f"sqlite:///{db_path}",
    echo=False,
    connect_args={"check_same_thread": False}
)


UTC_DATETIME_COLUMNS: dict[str, tuple[str, ...]] = {
    "sessions": ("created_at", "updated_at"),
    "messages": ("created_at",),
    "tasks": ("created_at", "updated_at", "finished_at"),
    "schedules": ("last_run_at", "next_run_at", "created_at", "updated_at"),
    "app_configs": ("updated_at",),
}

# This key is a one-time execution marker for the specific UTC datetime backfill
# implemented in migrate_datetime_columns_to_explicit_utc_strings().
#
# IMPORTANT:
# - Reuse this key only if the migration logic is unchanged.
# - If the backfill logic changes in a way that must reprocess existing rows,
#   create a NEW key (for example, ..._v2) so the migration runs again.
# - For a different one-time migration, use a different dedicated key instead of
#   overloading this one.
UTC_DATETIME_MIGRATION_KEY = "system.utc_datetime_text_migration_v1"


def migrate_session_memory_json_payloads() -> None:
    """Normalize legacy sessions.memory values for the JSON-based schema."""
    try:
        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())
        if "sessions" not in table_names:
            return

        column_names = {column["name"] for column in inspector.get_columns("sessions")}
        if "memory" not in column_names:
            return
    except Exception as e:
        logger.exception(f"⚠️ Could not inspect sessions.memory for migration with exception: {e}")
        return

    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, memory FROM sessions WHERE memory IS NOT NULL")).fetchall()
        for row in rows:
            session_id = row[0]
            raw_memory = row[1]

            if raw_memory is None:
                continue

            if isinstance(raw_memory, dict):
                continue
            elif isinstance(raw_memory, str):
                try:
                    parsed = json.loads(raw_memory)
                except Exception:
                    parsed = None

                if isinstance(parsed, dict):
                    conn.execute(
                        text("UPDATE sessions SET memory = :memory WHERE id = :id"),
                        {
                            "id": session_id,
                            "memory": json.dumps(parsed, ensure_ascii=False),
                        },
                    )
                else:
                    conn.execute(
                        text("UPDATE sessions SET memory = NULL WHERE id = :id"),
                        {"id": session_id},
                    )
            else:
                conn.execute(
                    text("UPDATE sessions SET memory = NULL WHERE id = :id"),
                    {"id": session_id},
                )
        conn.commit()


def migrate_datetime_columns_to_explicit_utc_strings() -> None:
    """Normalize persisted datetimes to explicit ISO 8601 UTC strings."""
    # Guard this backfill with a durable marker so startup does not rescan every
    # datetime column on every launch. If you change the normalization behavior
    # and need to re-run it for already-migrated databases, bump
    # UTC_DATETIME_MIGRATION_KEY to a new value.
    try:
        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())
    except Exception as e:
        logger.exception(f"⚠️ Could not inspect datetime columns for migration with exception: {e}")
        return

    if "app_configs" in table_names:
        with engine.connect() as conn:
            migration_marker = conn.execute(
                text("SELECT 1 FROM app_configs WHERE key = :key LIMIT 1"),
                {"key": UTC_DATETIME_MIGRATION_KEY},
            ).first()
            if migration_marker:
                return

    with engine.connect() as conn:
        for table_name, column_names in UTC_DATETIME_COLUMNS.items():
            if table_name not in table_names:
                continue

            existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
            for column_name in column_names:
                if column_name not in existing_columns:
                    continue

                rows = conn.execute(
                    text(f"SELECT rowid, {column_name} FROM {table_name} WHERE {column_name} IS NOT NULL")
                ).fetchall()

                for rowid, raw_value in rows:
                    try:
                        parsed = parse_utc_datetime(raw_value)
                    except Exception as exc:
                        logger.warning(
                            f"Skipping invalid datetime during UTC normalization: "
                            f"{table_name}.{column_name}={raw_value!r} ({exc})"
                        )
                        continue

                    if parsed is None:
                        continue

                    normalized = format_utc_datetime(parsed)
                    if raw_value == normalized:
                        continue

                    conn.execute(
                        text(f"UPDATE {table_name} SET {column_name} = :value WHERE rowid = :rowid"),
                        {"value": normalized, "rowid": rowid},
                    )

        if "app_configs" in table_names:
            conn.execute(
                text(
                    """
                    INSERT OR REPLACE INTO app_configs (key, value, category, metadata, updated_at)
                    VALUES (:key, :value, :category, :metadata, :updated_at)
                    """
                ),
                {
                    "key": UTC_DATETIME_MIGRATION_KEY,
                    "value": json.dumps(True),
                    "category": "system",
                    "metadata": json.dumps({"migration": "utc_datetime_text_v1"}),
                    "updated_at": format_utc_datetime(datetime.now(timezone.utc)),
                },
            )
        conn.commit()

def auto_migrate_schema():
    """
    Automatically detects missing columns in the database and adds them.
    This is a lightweight alternative to Alembic for the MVP stage.
    """
    inspector = inspect(engine)
    
    # Iterate through all models registered in SQLModel
    for table_name, table in SQLModel.metadata.tables.items():
        # Get existing columns in the database for this table
        try:
            existing_columns = {c['name'] for c in inspector.get_columns(table_name)}
        except Exception as e:
            logger.exception(f"⚠️ Could not inspect table {table_name} with exception: {e}")
            continue
            
        # Check each column in our model
        for column in table.columns:
            if column.name not in existing_columns:
                logger.info(f"🔧 Migrating: Adding missing column '{column.name}' to table '{table_name}'")
                
                # Determine SQL type
                type_str = str(column.type.compile(engine.dialect))
                
                # Prepare ALTER TABLE statement
                stmt = f"ALTER TABLE {table_name} ADD COLUMN {column.name} {type_str}"
                
                # Add default if present
                if column.default is not None and hasattr(column.default, 'arg'):
                    default_val = column.default.arg
                    if isinstance(default_val, (int, float)):
                        stmt += f" DEFAULT {default_val}"
                    elif isinstance(default_val, str):
                        stmt += f" DEFAULT '{default_val}'"
                elif not column.nullable:
                    if "INT" in type_str.upper():
                        stmt += " DEFAULT 0"
                    else:
                        stmt += " DEFAULT ''"

                # Direct execution without retries
                try:
                    with engine.connect() as conn:
                        conn.execute(text(stmt))
                        conn.commit()
                except Exception as e:
                    logger.critical(f"❌ Critical: Migration failed for table {table_name}.{column.name}")
                    raise e

def init_db():
    """Create tables if they don't exist and migrate schema."""
    SQLModel.metadata.create_all(engine)
    try:
        auto_migrate_schema()
        migrate_session_memory_json_payloads()
        migrate_datetime_columns_to_explicit_utc_strings()
    except Exception as e:
        logger.exception("🚨 DB Initialization Error")
        # Re-raise to prevent the app from starting in a broken state
        raise e
    logger.info(f"Database initialized and migrated at: {db_path}")

@contextmanager
def get_session() -> Generator[DBSession, None, None]:
    """Context manager for database sessions, also works as a FastAPI dependency."""
    with DBSession(engine) as session:
        yield session
