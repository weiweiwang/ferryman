import pytest
from datetime import datetime, timezone
from app.models.database import Session, Message, Task, AppConfig
from app.models.schemas import SessionModel, MessageModel, TaskModel
from sqlmodel import select

def test_app_config_crud(session):
    """Test AppConfig database operations."""
    config = AppConfig(key="test.key", value={"foo": "bar"}, category="test")
    session.add(config)
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
    
    # Verify retrieval
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
