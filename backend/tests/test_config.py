import pytest
from app.core.config import config
from app.models.database import AppConfig
from sqlmodel import select

def test_config_registry_persistence(session):
    """
    Verify that config.set saves to the DB and config.get retrieves it.
    Note: config singleton uses the default engine, but we want to test 
    integration with the database.
    """
    # Since config.py uses local imports of get_session, it normally hits the real DB.
    # In tests, we need to ensure it's using the test session if possible, 
    # but the config singleton is already initialized.
    
    # For a true integration test, we verify the methods work as expected.
    # We use a unique key to avoid collisions
    test_key = "registry.test.key"
    test_val = {"enabled": True, "count": 42}
    
    config.set(test_key, test_val, category="test")
    
    # Verify via the registry get
    retrieved = config.get(test_key)
    assert retrieved == test_val
    
    # Verify via direct DB access to ensure persistence
    from app.core.db import get_session
    with get_session() as db_session:
         statement = select(AppConfig).where(AppConfig.key == test_key)
         record = db_session.exec(statement).first()
         assert record is not None
         assert record.value == test_val

def test_config_list_by_category():
    """Test filtering configurations by category."""
    config.set("cat.1", "val1", category="c1")
    config.set("cat.2", "val2", category="c1")
    config.set("cat.3", "val3", category="c2")
    
    c1_list = config.list_by_category("c1")
    assert len(c1_list) >= 2
    keys = [item.key for item in c1_list]
    assert "cat.1" in keys
    assert "cat.2" in keys
    assert "cat.3" not in keys
