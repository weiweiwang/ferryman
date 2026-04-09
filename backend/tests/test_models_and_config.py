import pytest
from datetime import datetime, timezone
from sqlmodel import select

from app.models.database import Session, Message, Task, AppConfig
from app.models.schemas import SessionModel, MessageModel, TaskModel
from app.core.config import Settings as config

from app.models.events import (
    FerrymanEventEnvelope,
    EventNamespace,
    ToolActivityPayload,
    ToolPhase,
    ChatFinalPayload,
    RefreshPayload,
    EntityAction,
    DataEntity
)


def test_app_config_crud(session):
    """Test AppConfig database operations."""
    app_config = AppConfig(key="test.key", value={"foo": "bar"}, category="test")
    session.add(app_config)
    session.commit()
    
    statement = select(AppConfig).where(AppConfig.key == "test.key")
    result = session.exec(statement).first()
    assert result is not None
    assert result.value == {"foo": "bar"}
    assert result.category == "test"


def test_session_message_relationship(session):
    """Test creating a session and associated messages."""
    new_session = Session(title="Test Session")
    session.add(new_session)
    session.commit()
    session.refresh(new_session)
    
    msg = Message(
        session_id=new_session.id,
        role="user",
        content="Hello",
        type="text"
    )
    session.add(msg)
    session.commit()
    
    statement = select(Message).where(Message.session_id == new_session.id)
    results = session.exec(statement).all()
    assert len(results) == 1
    assert results[0].content == "Hello"


def test_pydantic_schema_validation():
    """Test Pydantic model validation and transformation."""
    data = {
        "id": "test-uuid",
        "session_id": "session-uuid",
        "role": "assistant",
        "content": "Hi",
        "type": "text",
        "created_at": datetime.now(timezone.utc)
    }
    model = MessageModel(**data)
    assert model.role == "assistant"
    assert model.content == "Hi"


def test_event_models_serialization():
    """Test that event models can be created and serialized properly."""
    tool_payload = ToolActivityPayload(
        run_id="run-1",
        tool_name="navigate",
        phase=ToolPhase.START,
        input={"url": "example.com"}
    )
    env = FerrymanEventEnvelope(
        namespace=EventNamespace.AGENT,
        event="tool_activity",
        session_id="session-1",
        payload=tool_payload
    )
    
    dumped = env.model_dump(mode="json")
    assert dumped["namespace"] == "agent"
    assert dumped["payload"]["phase"] == "start"
    assert dumped["payload"]["input"]["url"] == "example.com"
    assert "ts" in dumped

    chat_payload = ChatFinalPayload(
        run_id="run-2",
        messages=[{"role": "assistant", "content": "Done"}],
        usage={"input_tokens": 10, "output_tokens": 5}
    )
    env = FerrymanEventEnvelope(
        namespace=EventNamespace.AGENT,
        event="chat_final",
        payload=chat_payload
    )
    dumped = env.model_dump(mode="json")
    assert dumped["payload"]["messages"][0]["content"] == "Done"

    refresh_payload = RefreshPayload(
        entity=DataEntity.TASK,
        action=EntityAction.UPDATED,
        entity_id="task-123"
    )
    env = FerrymanEventEnvelope(
        namespace=EventNamespace.DATA,
        event="refresh",
        payload=refresh_payload
    )
    dumped = env.model_dump(mode="json")
    assert dumped["payload"]["entity"] == "task"


def test_config_registry_persistence(session):
    """Test config registry sets and gets via the database."""
    test_key = "registry.test.key"
    test_val = {"enabled": True, "count": 42}
    
    config.set(test_key, test_val, category="test")
    retrieved = config.get(test_key)
    assert retrieved == test_val
    
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
