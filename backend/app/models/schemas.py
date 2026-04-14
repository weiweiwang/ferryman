from datetime import datetime
from enum import IntEnum
from pathlib import Path
from typing import Optional, Any, Dict, List, Literal

from pydantic import BaseModel, Field


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
    created: Optional[str] = None
    updated: Optional[str] = None

class MCPToolModel(BaseModel):
    name: str
    description: str
    arguments: Dict[str, Any]
    server_name: str

class SessionModel(BaseModel):
    id: str
    title: str
    memory: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

class MessageModel(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    type: str
    parts: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

class TaskModel(BaseModel):
    id: str
    session_id: str
    title: str
    status: str = TaskStatus.PENDING
    args: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    parent_id: Optional[str] = None
    project_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    finished_at: Optional[datetime] = None

class ScheduleModel(BaseModel):
    id: str
    name: str
    cron_expression: str
    args: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class AgentRunResult(BaseModel):
    status: Literal["success", "error"]
    session_id: str
    response: Optional[Any] = None
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
