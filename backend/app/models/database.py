from datetime import datetime, timezone
from typing import Optional, Any, Dict, List

import shortuuid
from sqlalchemy import Column as SAColumn
from sqlmodel import SQLModel, Field, JSON


class Session(SQLModel, table=True):
    __tablename__ = "sessions"
    id: str = Field(default_factory=shortuuid.uuid, primary_key=True)
    title: str = Field(default="")
    memory: Optional[Dict[str, Any]] = Field(default=None, sa_column=SAColumn(JSON, nullable=True))
    input_tokens: int = Field(default=0)
    output_tokens: int = Field(default=0)
    metadata_: Dict[str, Any] = Field(default_factory=dict, sa_column=SAColumn("metadata", JSON))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class Message(SQLModel, table=True):
    __tablename__ = "messages"
    id: str = Field(default_factory=shortuuid.uuid, primary_key=True)
    session_id: str = Field(index=True)
    role: str  # user, assistant, system, tool
    content: str
    parts: List[Dict[str, Any]] = Field(default_factory=list, sa_column=SAColumn(JSON))
    type: str  # text, tool_call, tool_result, thinking
    token_estimate: int = Field(default=0)
    metadata_: Dict[str, Any] = Field(default_factory=dict, sa_column=SAColumn("metadata", JSON))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class Task(SQLModel, table=True):
    __tablename__ = "tasks"
    id: str = Field(default_factory=shortuuid.uuid, primary_key=True)
    session_id: str = Field(index=True)
    parent_id: Optional[str] = None
    title: str
    args: Dict[str, Any] = Field(default_factory=dict, sa_column=SAColumn(JSON))
    status: str = Field(default="pending")  # pending, running, success, failed, canceled
    metadata_: Dict[str, Any] = Field(default_factory=dict, sa_column=SAColumn("metadata", JSON))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: Optional[datetime] = None

class Schedule(SQLModel, table=True):
    __tablename__ = "schedules"
    id: str = Field(default_factory=shortuuid.uuid, primary_key=True)
    name: str
    args: Dict[str, Any] = Field(default_factory=dict, sa_column=SAColumn(JSON))
    cron_expression: str
    timezone: str = Field(default="UTC")
    enabled: bool = Field(default=True)
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    total_run_count: int = Field(default=0)
    last_run_result: Optional[Dict[str, Any]] = Field(default=None, sa_column=SAColumn(JSON, nullable=True))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class AppConfig(SQLModel, table=True):
    __tablename__ = "app_configs"
    key: str = Field(primary_key=True)  # e.g., "llm.openai.api_key", "system.llm.active_model"
    value: Any = Field(sa_column=SAColumn(JSON))
    category: str = Field(index=True)  # e.g., "llm", "system"
    metadata_: Dict[str, Any] = Field(default_factory=dict, sa_column=SAColumn("metadata", JSON))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
