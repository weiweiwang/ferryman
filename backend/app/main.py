import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from typing import Optional
from jsonrpcserver import async_dispatch, method, Success
from app.core.config import config
from app.core.bootstrap import init_env
from app.core.logging_config import configure_logging
from app.core.kernel import FerrymanKernel
from app.core.mcp_client import MCPClient
from app.core.config import (
    config,
    get_runtime_config, 
    set_runtime_config, 
    get_active_model_id,
    list_configs_by_category
)
from sqlmodel import select, desc, and_, text, func
from app.models.database import Session, Message, Task
from app.core.db import get_session

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize environment
    init_env(config)
    
    # Initialize logging
    configure_logging()
    logger.info("🚀 Ferryman Sidecar starting...")
    
    # Initialize Core Components
    app.state.mcp_client = MCPClient()
    app.state.mcp_client.load_config()
    await app.state.mcp_client.connect_all()

    app.state.kernel = FerrymanKernel()
    app.state.kernel.mcp_client = app.state.mcp_client # Bridge them
    
    # Pre-scan skills
    app.state.kernel.scan_skills()
    
    yield
    logger.info("🛑 Ferryman Sidecar shutting down...")

app = FastAPI(title="Ferryman Sidecar", lifespan=lifespan)

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
        stored_config = get_runtime_config(f"llm.{p}", {})
        
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
    current_config = get_runtime_config(key, {})
    
    if api_key is not None:
        current_config["api_key"] = api_key
    if base_url is not None:
        # If empty string, we treat it as "use default"
        current_config["base_url"] = base_url.strip() if base_url.strip() else ""
    
    set_runtime_config(key, current_config, category="llm")
    
    return Success({"status": "success"})

@method
async def get_active_model(context):
    """
    Returns the currently active model identifier.
    """
    return Success(get_active_model_id())

@method
async def set_active_model(context, model: str):
    """
    Updates the active model globally.
    """
    set_runtime_config("system.llm.active_model", model, category="system")
    return Success({"status": "success"})

@method
async def get_available_models(context):
    """
    Returns the mapped candidate models for the UI select.
    """
    return Success(config.get_available_models())

@method
async def execute(context, instruction: str, session_id: str = "default"):
    """
    Ferryman OS 核心指令入口：接收自然语言指令并调度 Master Agent。
    """
    logger.info(f"📥 OS Instruction Received: {instruction} (Session: {session_id})")
    
    if context and hasattr(context, "kernel"):
        # 调用 Kernel 的 Master Agent 入口
        # 这里 Master Agent 会根据 OS Prompt 和可用 Skills 决定下一步
        result = await context.kernel.run_master_agent(
            instruction=instruction,
            session_id=session_id
        )
        return Success(result)
    
    return Success({"status": "error", "message": "Kernel not initialized"})

@method
async def create_session(context, id: Optional[str] = None, title: str = "New Chat"):
    """Creates a new chat session."""
    logger.info(f"🆕 Creating new session: {title} (ID: {id})")
    with get_session() as db_session:
        new_session = Session(id=id, title=title) if id else Session(title=title)
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
            cursor_dt = None
            try:
                from datetime import datetime
                cursor_dt = datetime.fromisoformat(cursor)
                statement = statement.where(Session.updated_at < cursor_dt)
            except Exception:
                logger.error(f"Invalid cursor format: {cursor}")

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
                SET input_tokens = COALESCE((
                    SELECT SUM(json_extract(metadata, '$.usage.input_tokens')) 
                    FROM messages 
                    WHERE session_id = :sid AND role = 'assistant'
                ), 0),
                output_tokens = COALESCE((
                    SELECT SUM(json_extract(metadata, '$.usage.output_tokens')) 
                    FROM messages 
                    WHERE session_id = :sid AND role = 'assistant'
                ), 0)
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
            cursor_dt = None
            try:
                from datetime import datetime
                cursor_dt = datetime.fromisoformat(cursor)
                statement = statement.where(Message.created_at < cursor_dt)
            except Exception:
                pass

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
            "messages": [{"role": m.role, "content": m.content, "type": m.type, "metadata": m.metadata_} for m in messages_list],
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
    await websocket.accept()
    logger.info("🔌 WebSocket connection established")
    
    try:
        while True:
            data = await websocket.receive_text()
            # 处理 JSON-RPC 请求，通过 context 传递 app.state
            response = await async_dispatch(data, context=websocket.app.state)
            if response:
                await websocket.send_text(str(response))
    except WebSocketDisconnect:
        logger.info("❌ WebSocket disconnected")
    except Exception as e:
        logger.error(f"⚠️ Error: {e}")
        if not websocket.client_state.name == "DISCONNECTED":
            await websocket.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=config.port)
