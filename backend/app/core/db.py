from pathlib import Path
from typing import Generator
from contextlib import contextmanager
import logging
from sqlmodel import SQLModel, create_engine, Session as DBSession, text
from sqlalchemy import inspect
from app.core.config import config
# Import models to ensure they are registered with SQLModel.metadata
from app.models import database 
import os

logger = logging.getLogger(__name__)

# Initialize engine at module level with absolute path and shared access
db_path = config.db_path.absolute()
db_path.parent.mkdir(parents=True, exist_ok=True)

# Broaden permissions and remove macOS extended attributes before connecting
import os
import subprocess
try:
    if db_path.exists():
            os.chmod(db_path, 0o666)
            subprocess.run(["xattr", "-c", str(db_path)], capture_output=True)
    os.chmod(db_path.parent, 0o777)
except Exception:
    pass

# Use check_same_thread=False for FastAPI/WebSocket compatibility
engine = create_engine(
    f"sqlite:///{db_path}",
    echo=False,
    connect_args={"check_same_thread": False}
)

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
            logger.warning(f"⚠️ Could not inspect table {table_name}: {e}")
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
                    logger.critical(f"❌ Critical: Migration failed for table {table_name}.{column.name}: {e}")
                    raise e

def init_db():
    """Create tables if they don't exist and migrate schema."""
    SQLModel.metadata.create_all(engine)
    try:
        auto_migrate_schema()
    except Exception as e:
        logger.error(f"🚨 DB Initialization Error: {e}")
        # Re-raise to prevent the app from starting in a broken state
        raise e
    logger.info(f"Database initialized and migrated at: {db_path}")

@contextmanager
def get_session() -> Generator[DBSession, None, None]:
    """Context manager for database sessions, also works as a FastAPI dependency."""
    with DBSession(engine) as session:
        yield session
