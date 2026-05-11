import logging
from datetime import date, datetime, timezone
from enum import IntEnum
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger(__name__)

class TaskStatus:
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELED = "canceled"

class SkillModel(BaseModel):
    name: str
    description: str
    path: Path
    sop_content: Optional[str] = None
    version: str = "0.1.0"
    author: str = "Unknown"
    created: Optional[date] = None
    updated: Optional[date] = None

class MCPToolModel(BaseModel):
    name: str
    description: str
    arguments: dict[str, object]
    server_name: str


class ValidatorBaseModel(BaseModel):
    @classmethod
    def utc_datetime(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class SessionCompactionMemory(ValidatorBaseModel):
    model_config = ConfigDict(extra="ignore")

    summary: Optional[str] = None
    cutoff_created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    guard_until: Optional[datetime] = None

    @field_validator("summary", mode="before")
    @classmethod
    def normalize_summary(cls, value: object) -> Optional[str]:
        if not isinstance(value, str):
            return None
        summary = value.strip()
        return summary or None

    @field_validator("cutoff_created_at", "updated_at", "guard_until", mode="before")
    @classmethod
    def validate_datetime(cls, value: object) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return cls.utc_datetime(value)
        if isinstance(value, date):
            return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
        if isinstance(value, str):
            normalized = value.strip()
            if not normalized:
                return None
            try:
                return cls.utc_datetime(datetime.fromisoformat(normalized.replace("Z", "+00:00")))
            except ValueError:
                return None
        return None


class SessionMemory(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_version: int = 1
    compaction: SessionCompactionMemory = Field(default_factory=SessionCompactionMemory)

    @field_validator("schema_version", mode="before")
    @classmethod
    def normalize_schema_version(cls, value: object) -> int:
        return 1

    @field_validator("compaction", mode="before")
    @classmethod
    def normalize_compaction(cls, value: object) -> dict[str, object]:
        return value if isinstance(value, dict) else {}

class SessionModel(ValidatorBaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    memory: Optional[dict[str, object]] = None
    metadata: dict[str, object] = Field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def validate_datetime(cls, value: datetime):
        return cls.utc_datetime(value)


class SessionResponseModel(SessionModel):
    active_run: Optional[dict[str, object]] = None


class MessageModel(ValidatorBaseModel):
    id: str
    session_id: str
    role: str
    content: str
    type: str
    token_estimate: int = 0
    parts: list[dict[str, object]] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def validate_datetime(cls, value: datetime):
        return ValidatorBaseModel.utc_datetime(value)


class TaskModel(ValidatorBaseModel):
    id: str
    session_id: str
    title: str
    status: str = TaskStatus.PENDING
    args: dict[str, object] = Field(default_factory=dict)
    metadata: dict[str, object] = Field(default_factory=dict)
    parent_id: Optional[str] = None
    project_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    finished_at: Optional[datetime] = None

    @field_validator("created_at", "updated_at", "finished_at")
    @classmethod
    def validate_datetime(cls, value: datetime):
        return ValidatorBaseModel.utc_datetime(value)


class ScheduleModel(ValidatorBaseModel):
    id: str
    name: str
    cron_expression: str
    args: dict[str, object] = Field(default_factory=dict)
    timezone: str = "UTC"
    enabled: bool = True
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    total_run_count: int = 0
    last_run_result: Optional[dict[str, object]] = None
    created_at: datetime
    updated_at: datetime

    @field_validator("last_run_at", "next_run_at", "created_at", "updated_at")
    @classmethod
    def validate_datetime(cls, value: datetime):
        return ValidatorBaseModel.utc_datetime(value)


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class AgentRunResult(BaseModel):
    status: Literal["success", "error"]
    session_id: str
    response: object | None = None
    message: Optional[str] = None
    usage: Usage = Field(default_factory=Usage)


class JsonRpcErrorCode(IntEnum):
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603
    SERVER_ERROR = -32000


class JsonRpcError(BaseModel):
    code: int
    message: str


class JsonRpcErrorResponse(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    error: JsonRpcError
    id: Optional[int | str] = None
