from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any, Dict, List
from pydantic import BaseModel, Field
import shortuuid

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
    kwargs: Dict[str, Any] = Field(default_factory=dict)
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
    kwargs: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
