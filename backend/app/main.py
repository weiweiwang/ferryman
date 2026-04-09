import json
import logging
import os
import secrets
from collections import deque
from contextlib import asynccontextmanager
from logging.config import dictConfig
from pathlib import Path
from typing import Optional

from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status
from jsonrpcserver import async_dispatch, method, Success
from sqlmodel import select, desc, text

from app.core.config import get_settings
from app.core.db import get_session
from app.core.kernel import FerrymanKernel
from app.models.database import Session, Message, Task
from app.models.schemas import JsonRpcError, JsonRpcErrorCode, JsonRpcErrorResponse

logger = logging.getLogger(__name__)
DEFAULT_FERRYMAN_BEARER_TOKEN = "dev-token"


def is_websocket_authorized(websocket: WebSocket) -> bool:
    presented_token = websocket.query_params.get("access_token")
    expected_token = getattr(websocket.app.state, "bearer_token", None)
    if not presented_token or not expected_token:
        return False
    return secrets.compare_digest(presented_token, expected_token)


def configure_logging(log_level: Optional[str] = None) -> None:
    settings = get_settings()
    log_level = log_level or settings.log_level
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
                "level": "WARNING",
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
    Returns consolidated API configurations for OpenAI, Anthropic, and Gemini.
    """
    providers = ["gemini", "openai", "anthropic"]

    # UI Placeholders (standard URLs)
    placeholders = {
        "openai": "https://api.openai.com/v1",
        "anthropic": "https://api.anthropic.com/v1",
        "gemini": "https://generativelanguage.googleapis.com"
    }

    results = []
    for p in providers:
        # Each provider is stored in a single row with key "llm.{provider}"
        stored_config = get_settings().get(f"llm.{p}", {})

        results.append({
            "provider": p,
            "api_key": stored_config.get("api_key", ""),
            "base_url": stored_config.get("base_url", ""),
            "metadata": {
                "label": p.capitalize(),
                "placeholder_base_url": placeholders.get(p, "")
            }
        })

    return Success(results)


@method
async def set_llm_config(context, provider: str, api_key: str = None, base_url: str = None):
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
    return Success(get_settings().get_available_models())


@method
async def list_skills(context):
    if context and hasattr(context, "kernel"):
        skills = sorted(context.kernel.skills.values(), key=lambda skill: skill.name.lower())
        return Success([
            {
                "name": skill.name,
                "description": skill.description,
                "version": skill.version,
                "author": skill.author,
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
async def read_backend_logs(context, source: str = "app", lines: int = 200):
    paths = get_backend_log_paths()
    target = Path(paths.get(source, paths["app"]))
    requested_lines = max(20, min(lines, 1000))
    return Success({
        "source": source if source in paths else "app",
        "path": str(target),
        "content": tail_lines(target, requested_lines),
    })


async def background_generate_title(kernel, session_id: str, instruction: str):
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
                db_session.add(session_obj)
                db_session.commit()
    except Exception as e:
        logger.error(f"Failed to auto-generate title for session {session_id}: {e}")


@method
async def execute(context, instruction: str, session_id: str = "default"):
    """
    Ferryman OS 核心指令入口：接收自然语言指令并调度 Master Agent。
    """
    logger.info(f"📥 OS Instruction Received: {instruction} (Session: {session_id})")

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
            import asyncio
            asyncio.create_task(background_generate_title(context.kernel, session_id, instruction))

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
        db_session.add(session_obj)
        db_session.commit()
        return Success({"status": "success"})


@method
async def list_sessions(context, cursor: Optional[str] = None, limit: int = 20):
    """Lists available chat sessions with cursor-based pagination."""
    logger.debug(f"Listing sessions (cursor: {cursor}, limit: {limit})")
    with get_session() as db_session:
        statement = select(Session).order_by(desc(Session.updated_at))

        if cursor:
            # We assume cursor is the isoformat string of updated_at for simplicity in this implementation
            # Or use id if updated_at is identical. For now, let's use updated_at.
            try:
                from datetime import datetime
                cursor_dt = datetime.fromisoformat(cursor)
                statement = statement.where(Session.updated_at < cursor_dt)
            except Exception as e:
                logger.exception(f"Invalid cursor format: {cursor}, exception: {e}")

        sessions_list = db_session.exec(statement.limit(limit + 1)).all()

        has_more = len(sessions_list) > limit
        if has_more:
            sessions_list = sessions_list[:limit]
            next_cursor = sessions_list[-1].updated_at.isoformat()
        else:
            next_cursor = None

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
async def get_messages(context, session_id: str, cursor: Optional[str] = None, limit: int = 50):
    """Returns messages for a specific session with pagination and token refresh logic."""
    logger.debug(f"Fetching messages for session: {session_id} (cursor: {cursor})")

    with get_session() as db_session:
        # 1. On-open refresh: Sync token counts from messages
        # Use SQL aggregation for efficiency as planned
        try:
            # SQLite specific json_extract usage via text() for precision
            sync_sql = text("""
                            UPDATE sessions
                            SET input_tokens  = COALESCE((SELECT SUM(json_extract(metadata, '$.usage.input_tokens'))
                                                          FROM messages
                                                          WHERE session_id = :sid
                                                            AND role = 'assistant'), 0),
                                output_tokens = COALESCE((SELECT SUM(json_extract(metadata, '$.usage.output_tokens'))
                                                          FROM messages
                                                          WHERE session_id = :sid
                                                            AND role = 'assistant'), 0)
                            WHERE id = :sid
                            """)
            db_session.execute(sync_sql, {"sid": session_id})
            db_session.commit()
        except Exception as e:
            logger.error(f"Failed to sync session tokens: {e}")

        # 2. Fetch messages with pagination
        statement = select(Message).where(Message.session_id == session_id).order_by(desc(Message.created_at))

        if cursor:
            # Here cursor is the message ID or timestamp. Let's use ID for stable paging.
            # But created_at is better for chronological order.
            try:
                from datetime import datetime
                cursor_dt = datetime.fromisoformat(cursor)
                statement = statement.where(Message.created_at < cursor_dt)
            except Exception as e:
                logger.exception(f"Invalid cursor format: {cursor}, exception: {e}")

        messages_list = db_session.exec(statement.limit(limit + 1)).all()

        # Sort back to ascending for display
        has_more = len(messages_list) > limit
        if has_more:
            messages_list = messages_list[:limit]
            next_cursor = messages_list[-1].created_at.isoformat()
        else:
            next_cursor = None

        # Sort ascending for the frontend
        messages_list.reverse()

        return Success({
            "messages": [{"role": m.role, "content": m.content, "type": m.type, "metadata": m.metadata_} for m in
                         messages_list],
            "next_cursor": next_cursor
        })


@method
async def list_tasks(context, session_id: Optional[str] = None):
    """Lists tasks, optionally filtered by session."""
    logger.debug(f"Listing tasks (filter session_id: {session_id})")
    from sqlmodel import select
    from app.models.database import Task
    from app.core.db import get_session
    with get_session() as session:
        statement = select(Task)
        if session_id:
            statement = statement.where(Task.session_id == session_id)
        tasks = session.exec(statement.order_by(Task.updated_at.desc())).all()
        logger.debug(f"Found {len(tasks)} tasks")
        return Success([{
            "id": t.id,
            "title": t.title,
            "status": t.status,
            "progress": t.metadata_.get("progress_note", ""),
            "updated_at": t.updated_at.isoformat()
        } for t in tasks])


@method
async def list_schedules(context):
    """Lists all automated routines."""
    logger.debug("Listing all automated schedules")
    from sqlmodel import select
    from app.models.database import Schedule
    from app.core.db import get_session
    with get_session() as session:
        schedules = session.exec(select(Schedule)).all()
        logger.debug(f"Found {len(schedules)} schedules")
        return Success([{
            "id": s.id,
            "name": s.name,
            "cron": s.cron_expression,
            "enabled": s.enabled
        } for s in schedules])


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
                logger.info("❌ WebSocket disconnected")
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
