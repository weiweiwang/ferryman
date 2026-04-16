import json
import logging
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import inspect
from sqlmodel import SQLModel, create_engine, Session as DBSession, text

from app.core.config import get_settings

logger = logging.getLogger(__name__)

db_path = get_settings().db_path.absolute()
db_path.parent.mkdir(parents=True, exist_ok=True)


engine = create_engine(
    f"sqlite:///{db_path}",
    echo=False,
    connect_args={"check_same_thread": False}
)


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
