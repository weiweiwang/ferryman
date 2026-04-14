import json
import logging
import os
import secrets
import asyncio
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from logging.config import dictConfig
from pathlib import Path
from typing import Any, Optional

from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status
from jsonrpcserver import async_dispatch, method, Success
from sqlalchemy import String as SAString, and_, func, or_
from sqlmodel import select, desc

from app.core.config import get_settings
from app.core.db import get_session
from app.core.kernel import FerrymanKernel
from app.models.database import Session, Message, Schedule, Task
from app.models.schemas import JsonRpcError, JsonRpcErrorCode, JsonRpcErrorResponse

logger = logging.getLogger(__name__)
DEFAULT_FERRYMAN_BEARER_TOKEN = "dev-token"


def encode_datetime_cursor(sort_at: datetime, entity_id: str) -> str:
    if sort_at.tzinfo is None:
        sort_at = sort_at.replace(tzinfo=timezone.utc)
    normalized = sort_at.astimezone(timezone.utc).isoformat()
    return json.dumps({"sort_at": normalized, "id": entity_id}, separators=(",", ":"))


def decode_datetime_cursor(cursor: str) -> tuple[datetime, str]:
    payload = json.loads(cursor)
    if not isinstance(payload, dict):
        raise ValueError("Cursor payload must be an object.")

    sort_at = payload.get("sort_at")
    entity_id = payload.get("id")
    if not isinstance(sort_at, str) or not isinstance(entity_id, str):
        raise ValueError("Cursor must include string sort_at and id fields.")

    parsed_at = datetime.fromisoformat(sort_at)
    if parsed_at.tzinfo is None:
        parsed_at = parsed_at.replace(tzinfo=timezone.utc)

    return parsed_at, entity_id


def fetch_datetime_cursor_page(
    db_session,
    statement,
    *,
    model: Any,
    sort_field: str,
    cursor: Optional[str],
    limit: int,
) -> tuple[list[Any], Optional[str]]:
    limit = max(1, limit)
    sort_column = getattr(model, sort_field)
    id_column = getattr(model, "id")

    statement = statement.order_by(desc(sort_column), desc(id_column))
    if cursor:
        try:
            cursor_dt, cursor_id = decode_datetime_cursor(cursor)
            statement = statement.where(
                or_(
                    sort_column < cursor_dt,
                    and_(sort_column == cursor_dt, id_column < cursor_id),
                )
            )
        except Exception as e:
            logger.exception(f"Invalid cursor format: {cursor}, exception: {e}")

    items = list(db_session.exec(statement.limit(limit + 1)).all())
    has_more = len(items) > limit
    if not has_more:
        return items, None

    items = items[:limit]
    last_item = items[-1]
    return items, encode_datetime_cursor(getattr(last_item, sort_field), last_item.id)


def serialize_task(task: Task, *, detail: bool = False) -> dict[str, Any]:
    progress = task.metadata_.get("progress_note", "")
    payload = {
        "id": task.id,
        "session_id": task.session_id,
        "parent_id": task.parent_id,
        "title": task.title,
        "status": task.status,
        "progress": progress,
        "updated_at": task.updated_at.isoformat(),
    }
    if detail:
        payload.update({
            "instruction": task.args.get("instruction", ""),
            "payload": task.args.get("payload", {}),
            "created_at": task.created_at.isoformat(),
            "finished_at": task.finished_at.isoformat() if task.finished_at else None,
        })
    return payload


def serialize_schedule(schedule: Schedule, *, detail: bool = False) -> dict[str, Any]:
    payload = {
        "id": schedule.id,
        "name": schedule.name,
        "cron": schedule.cron_expression,
        "enabled": schedule.enabled,
        "last_run_at": schedule.last_run_at.isoformat() if schedule.last_run_at else None,
        "next_run_at": schedule.next_run_at.isoformat() if schedule.next_run_at else None,
        "updated_at": schedule.updated_at.isoformat(),
    }
    if detail:
        payload.update({
            "instruction": schedule.args.get("instruction", ""),
            "created_at": schedule.created_at.isoformat(),
        })
    return payload


async def emit_refresh_event(
    emit_event_cb,
    *,
    entity: str,
    action: str,
    entity_id: Optional[str] = None,
    delta: Optional[dict] = None,
    session_id: Optional[str] = None,
) -> None:
    if not emit_event_cb:
        return

    from app.models.events import DataEntity, EntityAction, EventNamespace, FerrymanEventEnvelope, RefreshPayload

    event = FerrymanEventEnvelope(
        namespace=EventNamespace.DATA,
        event="refresh",
        session_id=session_id,
        payload=RefreshPayload(
            entity=DataEntity(entity),
            action=EntityAction(action),
            entity_id=entity_id,
            delta=delta,
        ),
    )
    await emit_event_cb(event)


def is_websocket_authorized(websocket: WebSocket) -> bool:
    presented_token = websocket.query_params.get("access_token")
    expected_token = getattr(websocket.app.state, "bearer_token", None)
    if not presented_token or not expected_token:
        return False
    return secrets.compare_digest(presented_token, expected_token)


def configure_logging(log_level: Optional[str] = None) -> None:
    settings = get_settings()
    log_level = (log_level or settings.log_level).upper()
    log_dir = settings.log_dir
    log_file = log_dir / "ferryman.log"

    # Ensure log directory exists (redundant with bootstrap but safe)
    os.makedirs(log_dir, exist_ok=True)

    dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "correlation_id": {
                "()": "asgi_correlation_id.CorrelationIdFilter",
                "uuid_length": 32,
                "default_value": "-",
            },
        },
        "formatters": {
            "json": {
                "()": "pythonjsonlogger.orjson.OrjsonFormatter",
                "format": "%(asctime)s %(levelname)s %(name)s %(module)s %(funcName)s:%(lineno)d [%(correlation_id)s] %(message)s",
                "rename_fields": {"levelname": "severity", "asctime": "timestamp"}
            },
            "standard": {
                "format": "%(asctime)s [%(levelname)s] %(name)s [%(correlation_id)s]: %(message)s"
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "filters": ["correlation_id"],
                "formatter": "json",
            },
            "file": {
                "class": "logging.handlers.TimedRotatingFileHandler",
                "filename": str(log_file),
                "when": "D",
                "interval": 1,
                "backupCount": 3,
                "filters": ["correlation_id"],
                "formatter": "json",
                "encoding": "utf-8",
            }
        },
        "loggers": {
            "": {  # root logger
                "handlers": ["console", "file"],
                "level": log_level,
            },
            "httpx": {
                "level": "WARNING",
                "handlers": ["console", "file"],
                "propagate": False,
            },
            "httpcore": {
                "level": "WARNING",
                "handlers": ["console", "file"],
                "propagate": False,
            },
            "trafilatura": {
                "level": "WARNING",
                "handlers": ["console", "file"],
                "propagate": False,
            },
            "pydantic_ai": {
                "level": log_level,
                "handlers": ["console", "file"],
                "propagate": False,
            }
        }
    })


def get_backend_log_paths() -> dict[str, str]:
    settings = get_settings()
    log_dir = settings.log_dir
    return {
        "app": str(log_dir / "ferryman.log"),
        "sidecar": str(log_dir / "ferryman-tauri.log"),
    }


def tail_lines(path: Path, lines: int = 200) -> str:
    if not path.exists():
        return ""

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return "".join(deque(handle, maxlen=lines))


@asynccontextmanager
async def lifespan(fastapi_app: FastAPI):
    # Initialize logging
    configure_logging()
    logger.info("🚀 Ferryman Sidecar starting...")

    fastapi_app.state.kernel = FerrymanKernel(get_settings())
    fastapi_app.state.bearer_token = os.environ.get("FERRYMAN_BEARER_TOKEN") or DEFAULT_FERRYMAN_BEARER_TOKEN

    # Pre-scan skills
    fastapi_app.state.kernel.scan_skills()

    yield
    await fastapi_app.state.kernel.shutdown()
    logger.info("🛑 Ferryman Sidecar shutting down...")


app = FastAPI(title="Ferryman Sidecar", lifespan=lifespan)
app.add_middleware(CorrelationIdMiddleware, update_request_header=True)  # type:ignore


@method
async def ping(context):
    return Success("pong")


@method
async def get_llm_configs(context):
    """
    Returns consolidated API configurations for supported providers.
    """
    providers = get_settings().get_llm_provider_catalog()

    results = []
    for provider, metadata in providers.items():
        # Each provider is stored in a single row with key "llm.{provider}"
        stored_config = get_settings().get(f"llm.{provider}", {})

        results.append({
            "provider": provider,
            "api_key": stored_config.get("api_key", ""),
            "base_url": stored_config.get("base_url", ""),
            "model": stored_config.get("model", ""),
            "metadata": {
                "label": metadata.get("label", provider.capitalize()),
                "placeholder_base_url": metadata.get("placeholder_base_url", ""),
                "placeholder_model": metadata.get("placeholder_model", ""),
                "supports_model": bool(metadata.get("supports_model", False)),
            }
        })

    return Success(results)


@method
async def set_llm_config(
    context,
    provider: str,
    api_key: str = None,
    base_url: str = None,
    model: str = None,
):
    """
    Updates the consolidated config object for a provider.
    """
    key = f"llm.{provider}"
    current_config = get_settings().get(key, {})

    if api_key is not None:
        current_config["api_key"] = api_key
    if base_url is not None:
        # If empty string, we treat it as "use default"
        current_config["base_url"] = base_url.strip() if base_url.strip() else ""
    if model is not None and provider == "custom":
        current_config["model"] = model.strip() if model.strip() else ""

    get_settings().set(key, current_config, category="llm")

    return Success({"status": "success"})


@method
async def get_active_model(context):
    """
    Returns the currently active model identifier.
    """
    return Success(get_settings().get_active_model_id())


@method
async def set_active_model(context, model: str):
    """
    Updates the active model globally.
    """
    get_settings().set("system.llm.active_model", model, category="system")
    return Success({"status": "success"})


@method
async def get_available_models(context):
    """
    Returns the mapped candidate models for the UI select.
    """
    return Success(await asyncio.to_thread(get_settings().get_available_models))


@method
async def list_skills(context):
    if context and hasattr(context, "kernel"):
        skills = sorted(context.kernel.skills.values(), key=lambda skill: skill.name.lower())
        skills = sorted(skills, key=lambda skill: getattr(skill, "updated", "") or "", reverse=True)
        return Success([
            {
                "name": skill.name,
                "description": skill.description,
                "version": skill.version,
                "author": skill.author,
                "created": getattr(skill, "created", None),
                "updated": getattr(skill, "updated", None),
            }
            for skill in skills
        ])

    return Success([])


@method
async def get_backend_log_info(context):
    paths = get_backend_log_paths()
    return Success({
        "paths": paths,
        "active_log": paths["app"],
    })


@method
async def get_browser_runtime_status(context):
    from app.core.browser import BrowserController

    return Success(BrowserController.get_runtime_status())


@method
async def read_backend_logs(context, source: str = "app", lines: int = 200):
    paths = get_backend_log_paths()
    target = Path(paths.get(source, paths["app"]))
    requested_lines = max(20, min(lines, 1000))
    return Success({
        "source": source if source in paths else "app",
        "path": str(target),
        "content": tail_lines(target, requested_lines),
    })


async def background_generate_title(kernel, session_id: str, instruction: str, emit_event_cb=None):
    try:
        from pydantic_ai.agent import Agent
        from app.models.database import Session
        logger.info(f"Generating auto-title for session {session_id}")

        llm = kernel._init_llm_model()
        agent = Agent(llm, system_prompt="You are a helpful assistant. Summarize the user's instruction into a very short chat title (MAX 5 words). Output ONLY the title, no quotes, no extra text.")
        result = await agent.run(f"User instruction: {instruction}")
        
        generated_title = result.output.strip(' \'"')
        logger.info(f"Generated title for session {session_id}: {generated_title}")

        with get_session() as db_session:
            session_obj = db_session.get(Session, session_id)
            if session_obj and not session_obj.title:
                session_obj.title = generated_title
                session_obj.updated_at = datetime.now(timezone.utc)
                db_session.add(session_obj)
                db_session.commit()
                await emit_refresh_event(
                    emit_event_cb,
                    entity="session",
                    action="updated",
                    entity_id=session_id,
                    delta={"title": generated_title},
                    session_id=session_id,
                )
    except Exception as e:
        logger.error(f"Failed to auto-generate title for session {session_id}: {e}")


@method
async def execute(context, instruction: str, session_id: str = "default"):
    """
    Ferryman OS 核心指令入口：接收自然语言指令并调度 Master Agent。
    """
    if context and hasattr(context, "kernel"):
        # Provide an emit callback that uses the active websocket
        async def emit_ws_event(event_model) -> None:
            try:
                ws = getattr(context, "active_ws", None)
                if ws and ws.client_state.name == "CONNECTED":
                    to_send = {
                        "jsonrpc": "2.0",
                        "method": "ferryman_event",
                        "params": event_model.model_dump(mode="json", exclude_none=True)
                    }
                    import json
                    await ws.send_text(json.dumps(to_send))
            except Exception as e:
                logger.error(f"Failed to emit WS event {event_model.event}: {e}")

        # 调用 Kernel 的 Master Agent 入口
        # 这里 Master Agent 会根据 OS Prompt 和可用 Skills 决定下一步
        result = await context.kernel.run_master_agent(
            instruction=instruction,
            session_id=session_id,
            emit_event_cb=emit_ws_event
        )

        need_title_gen = False
        with get_session() as db_session:
            session_obj = db_session.get(Session, session_id)
            if session_obj and not session_obj.title:
                need_title_gen = True

        if need_title_gen:
            asyncio.create_task(background_generate_title(context.kernel, session_id, instruction, emit_ws_event))

        # result is already dumped as a dict in run_master_agent in the new unified format
        return Success(result)

    return Success({"status": "error", "message": "Kernel not initialized"})


@method
async def create_session(context, session_id: Optional[str] = None, title: Optional[str] = None):
    """Creates a new chat session."""
    logger.info(f"🆕 Creating new session: {title} (ID: {session_id})")
    with get_session() as db_session:
        normalized_title = title or ""
        new_session = Session(id=session_id, title=normalized_title) if session_id else Session(title=normalized_title)
        db_session.add(new_session)
        db_session.commit()
        db_session.refresh(new_session)
        return Success({"id": new_session.id, "title": new_session.title})


@method
async def delete_session(context, session_id: str):
    """Deletes a session and its associated messages/tasks."""
    logger.info(f"🗑️ Deleting session: {session_id}")
    with get_session() as db_session:
        session_obj = db_session.get(Session, session_id)
        if not session_obj:
            return Success({"status": "error", "message": "Session not found"})

        # SQLModel/SQLAlchemy will handle cascade if configured, but let's be explicit if needed
        # Or just rely on the DB cascade if setup. Assuming manual cleanup for clarity here:
        msgs = db_session.exec(select(Message).where(Message.session_id == session_id)).all()
        for m in msgs:
            db_session.delete(m)
        tasks = db_session.exec(select(Task).where(Task.session_id == session_id)).all()
        for t in tasks:
            db_session.delete(t)

        db_session.delete(session_obj)
        db_session.commit()
        return Success({"status": "success"})


@method
async def update_session(context, session_id: str, title: str):
    """Updates a session's title."""
    logger.info(f"📝 Updating session {session_id} title to: {title}")
    with get_session() as db_session:
        session_obj = db_session.get(Session, session_id)
        if not session_obj:
            return Success({"status": "error", "message": "Session not found"})
        session_obj.title = title
        session_obj.updated_at = datetime.now(timezone.utc)
        db_session.add(session_obj)
        db_session.commit()
        return Success({"status": "success"})


@method
async def list_sessions(context, cursor: Optional[str] = None, limit: int = 20):
    """Lists available chat sessions with cursor-based pagination."""
    logger.debug(f"Listing sessions (cursor: {cursor}, limit: {limit})")
    with get_session() as db_session:
        sessions_list, next_cursor = fetch_datetime_cursor_page(
            db_session,
            select(Session),
            model=Session,
            sort_field="updated_at",
            cursor=cursor,
            limit=limit,
        )

        return Success({
            "sessions": [{
                "id": s.id,
                "title": s.title,
                "updated_at": s.updated_at.isoformat(),
                "input_tokens": s.input_tokens,
                "output_tokens": s.output_tokens
            } for s in sessions_list],
            "next_cursor": next_cursor
        })


@method
async def list_messages(context, session_id: str, cursor: Optional[str] = None, limit: int = 50):
    """Returns messages for a specific session with pagination."""
    logger.debug(f"Fetching messages for session: {session_id} (cursor: {cursor})")

    with get_session() as db_session:
        messages_list, next_cursor = fetch_datetime_cursor_page(
            db_session,
            select(Message).where(Message.session_id == session_id),
            model=Message,
            sort_field="created_at",
            cursor=cursor,
            limit=limit,
        )

        messages_list.reverse()

        return Success({
            "messages": [{"role": m.role, "content": m.content, "type": m.type, "metadata": m.metadata_} for m in
                         messages_list],
            "next_cursor": next_cursor
        })


@method
async def list_tasks(
    context,
    session_id: Optional[str] = None,
    status: Optional[str] = None,
    query: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: int = 50,
):
    """Lists tasks, optionally filtered by session/status/query, with cursor-based pagination."""
    logger.debug(
        f"Listing tasks (session_id: {session_id}, status: {status}, query: {query}, cursor: {cursor}, limit: {limit})"
    )
    with get_session() as session:
        base_filters = []
        if session_id:
            base_filters.append(Task.session_id == session_id)
        if query:
            base_filters.append(
                or_(
                    Task.title.contains(query),
                    Task.args.cast(SAString).contains(query),
                )
            )

        statement = select(Task).where(*base_filters)
        if status:
            statement = statement.where(Task.status == status)

        tasks, next_cursor = fetch_datetime_cursor_page(
            session,
            statement,
            model=Task,
            sort_field="updated_at",
            cursor=cursor,
            limit=limit,
        )

        logger.debug(f"Found {len(tasks)} tasks")
        status_counts = dict.fromkeys(["pending", "running", "success", "failed", "canceled"], 0)
        summary_rows = session.exec(
            select(Task.status, func.count()).where(*base_filters).group_by(Task.status)
        ).all()
        for row_status, count in summary_rows:
            status_counts[row_status] = count

        return Success({
            "tasks": [serialize_task(t) for t in tasks],
            "next_cursor": next_cursor,
            "summary": {
                **status_counts,
                "total": sum(status_counts.values()),
            },
        })


@method
async def get_task(context, task_id: str):
    """Returns a single task with editable details."""
    logger.debug(f"Fetching task detail: {task_id}")
    with get_session() as session:
        task = session.get(Task, task_id)
        if not task:
            return Success({"status": "error", "message": "Task not found"})
        return Success({"task": serialize_task(task, detail=True)})


@method
async def update_task(
    context,
    task_id: str,
    title: Optional[str] = None,
    status: Optional[str] = None,
    progress_note: Optional[str] = None,
    instruction: Optional[str] = None,
    payload: Optional[dict[str, Any]] = None,
):
    """Updates editable task fields."""
    logger.info(f"Updating task: {task_id}")
    allowed_statuses = {"pending", "running", "success", "failed", "canceled"}
    if status is not None and status not in allowed_statuses:
        return Success({"status": "error", "message": "Invalid task status"})

    with get_session() as session:
        task = session.get(Task, task_id)
        if not task:
            return Success({"status": "error", "message": "Task not found"})

        if title is not None:
            task.title = title
        if status is not None:
            task.status = status
            task.finished_at = datetime.now(timezone.utc) if status in {"success", "failed", "canceled"} else None
        if progress_note is not None:
            metadata = dict(task.metadata_ or {})
            metadata["progress_note"] = progress_note
            task.metadata_ = metadata
        if instruction is not None or payload is not None:
            args = dict(task.args or {})
            if instruction is not None:
                args["instruction"] = instruction
            if payload is not None:
                args["payload"] = payload
            task.args = args

        task.updated_at = datetime.now(timezone.utc)
        session.add(task)
        session.commit()
        return Success({"status": "success"})


@method
async def delete_task(context, task_id: str):
    """Deletes a task."""
    logger.info(f"Deleting task: {task_id}")
    with get_session() as session:
        task = session.get(Task, task_id)
        if not task:
            return Success({"status": "error", "message": "Task not found"})
        session.delete(task)
        session.commit()
        return Success({"status": "success"})


@method
async def list_schedules(context, cursor: Optional[str] = None, limit: int = 50):
    """Lists automated routines with cursor-based pagination."""
    logger.debug(f"Listing automated schedules (cursor: {cursor}, limit: {limit})")

    with get_session() as session:
        schedules, next_cursor = fetch_datetime_cursor_page(
            session,
            select(Schedule),
            model=Schedule,
            sort_field="updated_at",
            cursor=cursor,
            limit=limit,
        )

        logger.debug(f"Found {len(schedules)} schedules")
        return Success({
            "schedules": [serialize_schedule(s) for s in schedules],
            "next_cursor": next_cursor,
        })


@method
async def get_schedule(context, schedule_id: str):
    """Returns a single schedule with editable details."""
    logger.debug(f"Fetching schedule detail: {schedule_id}")
    with get_session() as session:
        schedule = session.get(Schedule, schedule_id)
        if not schedule:
            return Success({"status": "error", "message": "Schedule not found"})
        return Success({"schedule": serialize_schedule(schedule, detail=True)})


@method
async def update_schedule(
    context,
    schedule_id: str,
    name: Optional[str] = None,
    cron: Optional[str] = None,
    enabled: Optional[bool] = None,
    instruction: Optional[str] = None,
):
    """Updates editable schedule fields."""
    logger.info(f"Updating schedule: {schedule_id}")
    with get_session() as session:
        schedule = session.get(Schedule, schedule_id)
        if not schedule:
            return Success({"status": "error", "message": "Schedule not found"})

        if name is not None:
            schedule.name = name
        if cron is not None:
            schedule.cron_expression = cron
        if enabled is not None:
            schedule.enabled = enabled
        if instruction is not None:
            args = dict(schedule.args or {})
            args["instruction"] = instruction
            schedule.args = args

        schedule.updated_at = datetime.now(timezone.utc)
        session.add(schedule)
        session.commit()
        return Success({"status": "success"})


@method
async def delete_schedule(context, schedule_id: str):
    """Deletes a schedule."""
    logger.info(f"Deleting schedule: {schedule_id}")
    with get_session() as session:
        schedule = session.get(Schedule, schedule_id)
        if not schedule:
            return Success({"status": "error", "message": "Schedule not found"})
        session.delete(schedule)
        session.commit()
        return Success({"status": "success"})


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    if not is_websocket_authorized(websocket):
        logger.warning("Unauthorized WebSocket connection rejected")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Unauthorized")
        return

    await websocket.accept()
    websocket.app.state.active_ws = websocket
    logger.info("🔌 WebSocket connection established")

    try:
        while True:
            try:
                data = await websocket.receive_text()
            except WebSocketDisconnect:
                logger.warning("❌ WebSocket disconnected")
                break

            try:
                # Process one JSON-RPC request at a time and keep the socket alive on request errors.
                response = await async_dispatch(data, context=websocket.app.state)
                if response:
                    await websocket.send_text(str(response))
            except Exception:
                logger.exception("⚠️ JSON-RPC dispatch failed")
                request_id = None
                try:
                    parsed = json.loads(data)
                    if isinstance(parsed, dict):
                        candidate_id = parsed.get("id")
                        if isinstance(candidate_id, (str, int)):
                            request_id = candidate_id
                except Exception:
                    request_id = None

                error_payload = JsonRpcErrorResponse(
                    error=JsonRpcError(
                        code=JsonRpcErrorCode.INTERNAL_ERROR,
                        message="Internal server error",
                    ),
                    id=request_id,
                )
                await websocket.send_text(error_payload.model_dump_json())
    except WebSocketDisconnect:
        logger.info("❌ WebSocket disconnected")
    except Exception:
        logger.exception("⚠️ WebSocket connection-level error")
        if websocket.client_state.name != "DISCONNECTED":
            await websocket.close()


if __name__ == "__main__":
    from app.sidecar import main

    main()
