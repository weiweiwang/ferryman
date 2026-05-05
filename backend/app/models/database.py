from datetime import datetime, timezone
from typing import Optional

import shortuuid
from sqlalchemy import Column as SAColumn
from sqlmodel import SQLModel, Field, JSON

from app.core.utc_datetime import UTCDateTime


class Session(SQLModel, table=True):
    __tablename__ = "sessions"
    id: str = Field(default_factory=shortuuid.uuid, primary_key=True)
    title: str = Field(default="")
    memory: Optional[dict[str, object]] = Field(default=None, sa_column=SAColumn(JSON, nullable=True))
    input_tokens: int = Field(default=0)
    output_tokens: int = Field(default=0)
    metadata_: dict[str, object] = Field(default_factory=dict, sa_column=SAColumn("metadata", JSON))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=SAColumn(UTCDateTime(), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=SAColumn(UTCDateTime(), nullable=False),
    )

class Message(SQLModel, table=True):
    __tablename__ = "messages"
    id: str = Field(default_factory=shortuuid.uuid, primary_key=True)
    session_id: str = Field(index=True)
    role: str  # user, assistant, system, tool
    content: str
    parts: list[dict[str, object]] = Field(default_factory=list, sa_column=SAColumn(JSON))
    type: str  # text, tool_call, tool_result, thinking
    token_estimate: int = Field(default=0)
    metadata_: dict[str, object] = Field(default_factory=dict, sa_column=SAColumn("metadata", JSON))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=SAColumn(UTCDateTime(), nullable=False),
    )

class Task(SQLModel, table=True):
    __tablename__ = "tasks"
    id: str = Field(default_factory=shortuuid.uuid, primary_key=True)
    session_id: str = Field(index=True)
    parent_id: Optional[str] = None
    title: str
    args: dict[str, object] = Field(default_factory=dict, sa_column=SAColumn(JSON))
    status: str = Field(default="pending")  # pending, running, success, failed, canceled
    metadata_: dict[str, object] = Field(default_factory=dict, sa_column=SAColumn("metadata", JSON))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=SAColumn(UTCDateTime(), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=SAColumn(UTCDateTime(), nullable=False),
    )
    finished_at: Optional[datetime] = Field(default=None, sa_column=SAColumn(UTCDateTime(), nullable=True))

class Schedule(SQLModel, table=True):
    __tablename__ = "schedules"
    id: str = Field(default_factory=shortuuid.uuid, primary_key=True)
    name: str
    args: dict[str, object] = Field(default_factory=dict, sa_column=SAColumn(JSON))
    cron_expression: str
    timezone: str = Field(default="UTC")
    enabled: bool = Field(default=True)
    last_run_at: Optional[datetime] = Field(default=None, sa_column=SAColumn(UTCDateTime(), nullable=True))
    next_run_at: Optional[datetime] = Field(default=None, sa_column=SAColumn(UTCDateTime(), nullable=True))
    total_run_count: int = Field(default=0)
    last_run_result: Optional[dict[str, object]] = Field(default=None, sa_column=SAColumn(JSON, nullable=True))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=SAColumn(UTCDateTime(), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=SAColumn(UTCDateTime(), nullable=False),
    )

class AppConfig(SQLModel, table=True):
    __tablename__ = "app_configs"
    key: str = Field(primary_key=True)  # e.g., "llm.openai.api_key", "system.llm.active_model"
    value: object = Field(sa_column=SAColumn(JSON))
    category: str = Field(index=True)  # e.g., "llm", "system"
    metadata_: dict[str, object] = Field(default_factory=dict, sa_column=SAColumn("metadata", JSON))
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=SAColumn(UTCDateTime(), nullable=False),
    )
