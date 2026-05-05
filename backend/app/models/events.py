from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Union

from pydantic import BaseModel, Field


# ==========================================
# Ferryman EDA (Event-Driven Architecture) Protocol
# ==========================================
# 本模块定义了 Ferryman 后端主动向前端推送的所有 WebSocket 事件协议格式。
# 所有事件统一封装在 JSON-RPC 2.0 的 Notification (无 id 字段) 中。
# RPC Method 名称统一固定为: "ferryman_event"
# ==========================================


class EventNamespace(str, Enum):
    """事件领域（Namespace），用于从顶层区分事件的来源体系"""
    AGENT = "agent"     # 大模型执行相关的生命周期与观测事件
    DATA = "data"       # 数据库实体与状态的异步变更通知
    SYSTEM = "system"   # 全局系统状态与故障报错


# ------------------------------------------
# 1. Agent 观测区 (Namespace: agent)
# ------------------------------------------

class ToolPhase(str, Enum):
    """工具执行的不同阶段"""
    START = "start"
    RUNNING = "running"
    COMPLETE = "complete"
    ERROR = "error"


class ToolActivityPayload(BaseModel):
    """
    场景 1.1: 汇报 Agent 正在使用工具的状态 (Observability)。
    用于在前端聊天气泡下方展示 "正在联网搜索..." 等实时动态。
    """
    run_id: str = Field(..., description="识别同一次大模型并发或任务的标识 UUID")
    event_id: Optional[str] = Field(None, description="单条工具观测事件的唯一 ID，便于排查重复发送或重复接收")
    seq: Optional[int] = Field(None, description="同一 AgentDeps 生命周期内递增的工具事件序号")
    tool_name: str = Field(..., description="底层原生的工具名称，如 'navigate', 'get_distilled_dom'")
    phase: ToolPhase = Field(..., description="工具执行阶段")
    input: Optional[dict[str, object]] = Field(None, description="工具的入参摘要（仅在 start/running 给定，限制大小）")
    duration_ms: Optional[int] = Field(None, description="消耗时间毫秒（仅在 complete/error 时必定下发）")


class ChatDeltaPayload(BaseModel):
    """
    场景 1.2: 汇报大模型流式文本输出（未来版图预留）。
    用于突破等待动画，实现真实逐字打字机效果。
    """
    run_id: str = Field(..., description="关联当前的会话流")
    chunk: str = Field(..., description="当前帧增量文本片段")
    is_final: bool = Field(False, description="是否是最后一帧")


class ChatFinalPayload(BaseModel):
    """
    场景 1.3: 汇报大模型最终的全量文本及执行结果。
    它不仅用于事件推送（可选），更用作前端同步阻塞调用的 `result` 的标准 Payload。
    """
    run_id: str = Field(..., description="关联当前的会话流")
    messages: list[dict[str, object]] = Field(..., description="最新的一系列对话消息记录")
    usage: Optional[dict[str, object]] = Field(None, description="本次请求消耗的 Tokens 等统计信息")


# ------------------------------------------
# 2. 数据实体防腐区 (Namespace: data)
# ------------------------------------------

class DataEntity(str, Enum):
    """可被监听与刷新的核心实体类型"""
    TASK = "task"
    SCHEDULE = "schedule"
    SKILL = "skill"
    SESSION = "session"


class EntityAction(str, Enum):
    """数据变化的动作"""
    CREATED = "created"
    UPDATED = "updated"
    DELETED = "deleted"
    BULK = "bulk"    # 发生了大批量操作，建议前端直接重新 Fetch 整个列表


class RefreshPayload(BaseModel):
    """
    场景 2.1: 通知前端某类数据实体发生变更。
    用来代替原先乱七八糟的 task_update, schedule_sync 等，统一接口。
    """
    entity: DataEntity = Field(..., description="变更的业务实体类型")
    action: EntityAction = Field(..., description="变更动作")
    entity_id: Optional[str] = Field(None, description="发生变更的实体 ID，如果是 bulk 刷新可为空")
    delta: Optional[dict[str, object]] = Field(None, description="增量数据（可选提供，以便前端直接合并减少请求）")


# ------------------------------------------
# 3. 系统级防线 (Namespace: system)
# ------------------------------------------

class ErrorSeverity(str, Enum):
    """错误的严重程度"""
    INFO = "info"         # 弱提示
    WARNING = "warning"   # 警告（如断线重连中），不打断主流程
    ERROR = "error"       # 局部错误（如某个定时脚本挂了）
    FATAL = "fatal"       # 致命错误，要求应用强制重置或白屏


class SystemErrorPayload(BaseModel):
    """
    场景 3.1: 汇报底层系统、网络或异步守护进程的故障。
    注意：您之前提议的 'fault' 已改为更符合直觉的 'error'。
    """
    code: str = Field(..., description="约定的后端内部错误码，如 'A_004', 'NET_TIMEOUT'")
    severity: ErrorSeverity = Field(..., description="错误严重级别")
    message: str = Field(..., description="面向用户的可读错误描述")
    context: Optional[dict[str, object]] = Field(None, description="相关异常的现场信息，如抛错堆栈或 ID，供排错")


# ------------------------------------------
# 协议统一 Envelope (信封)
# ------------------------------------------

class FerrymanEventEnvelope(BaseModel):
    """
    最顶层的事件模型，强制包裹了 `namespace`、`event` 与强类型的 `payload`。
    使用 Pydantic 的 discriminated union 可以直接做强类型反序列化。
    """
    namespace: EventNamespace
    event: str
    session_id: Optional[str] = Field(None, description="发生该事件时绑定的 UI Session ID（如果相关）")
    ts: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(), description="ISO8601 UTC 绝对时间戳")
    
    # 负载，使用 Union 允许根据情况赋不同模型（可根据业务通过 Pydantic 区分）
    payload: Union[ToolActivityPayload, ChatDeltaPayload, ChatFinalPayload, RefreshPayload, SystemErrorPayload, dict[str, object]]

    model_config = {
        "json_schema_extra": {
            "example": {
                "namespace": "agent",
                "event": "tool_activity",
                "session_id": "session-123",
                "ts": "2026-04-09T08:00:00Z",
                "payload": {
                    "run_id": "run-456",
                    "tool_name": "navigate",
                    "phase": "start",
                    "input": {"url": "abc.com"}
                }
            }
        }
    }
