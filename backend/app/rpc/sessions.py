from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from jsonrpcserver import Success, method
from sqlmodel import select

from app.core.db import get_session as get_db_session
from app.models.database import Message, Session, Task
from app.rpc.pagination import fetch_datetime_cursor_page

logger = logging.getLogger(__name__)


def serialize_session(session: Session) -> dict[str, object]:
    return {
        "id": session.id,
        "title": session.title,
        "updated_at": session.updated_at.isoformat(),
        "input_tokens": session.input_tokens,
        "output_tokens": session.output_tokens,
    }


@method
async def create_session(context, title: Optional[str] = None):
    """Create a new chat session."""
    logger.info(f"🆕 Creating new session: {title}")
    with get_db_session() as db_session:
        normalized_title = title or ""
        new_session = Session(title=normalized_title)
        db_session.add(new_session)
        db_session.commit()
        db_session.refresh(new_session)
        return Success({"id": new_session.id, "title": new_session.title})


@method
async def delete_session(context, session_id: str):
    """Delete a session and its associated messages/tasks."""
    logger.info(f"🗑️ Deleting session: {session_id}")
    with get_db_session() as db_session:
        session_obj = db_session.get(Session, session_id)
        if not session_obj:
            return Success({"status": "error", "message": "Session not found"})

        msgs = db_session.exec(select(Message).where(Message.session_id == session_id)).all()
        for message in msgs:
            db_session.delete(message)
        tasks = db_session.exec(select(Task).where(Task.session_id == session_id)).all()
        for task in tasks:
            db_session.delete(task)

        db_session.delete(session_obj)
        db_session.commit()
        return Success({"status": "success"})


@method
async def update_session(context, session_id: str, title: str):
    """Update a session's title."""
    logger.info(f"📝 Updating session {session_id} title to: {title}")
    with get_db_session() as db_session:
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
    """List chat sessions with cursor-based pagination."""
    logger.debug(f"Listing sessions (cursor: {cursor}, limit: {limit})")
    with get_db_session() as db_session:
        sessions_list, next_cursor = fetch_datetime_cursor_page(
            db_session,
            select(Session),
            model=Session,
            sort_field="updated_at",
            cursor=cursor,
            limit=limit,
        )

        return Success({
            "sessions": [serialize_session(session) for session in sessions_list],
            "next_cursor": next_cursor,
        })


@method
async def list_messages(context, session_id: str, cursor: Optional[str] = None, limit: int = 50):
    """Return messages for a session with pagination."""
    logger.debug(f"Fetching messages for session: {session_id} (cursor: {cursor})")

    with get_db_session() as db_session:
        messages_list, next_cursor = fetch_datetime_cursor_page(
            db_session,
            select(Message).where(Message.session_id == session_id, Message.role.in_(("user", "assistant"))),
            model=Message,
            sort_field="created_at",
            cursor=cursor,
            limit=limit,
        )

        messages_list.reverse()

        return Success({
            "messages": [
                {
                    "id": message.id,
                    "role": message.role,
                    "content": message.content,
                    "type": message.type,
                    "metadata": message.metadata_,
                    "created_at": message.created_at.isoformat(),
                }
                for message in messages_list
            ],
            "next_cursor": next_cursor,
        })


@method
async def get_session_insights(
    context,
    session_id: str,
    range_key: str = "last_7_days",
    timezone: str = "UTC",
):
    """Return token trend and memory details for the current session."""
    logger.debug(
        f"Fetching session insights (session_id: {session_id}, "
        f"range_key: {range_key}, timezone: {timezone})"
    )
    return Success(
        context.runtime.session_manager.get_session_insights(
            session_id,
            range_key=range_key,
            timezone_name=timezone,
        )
    )
