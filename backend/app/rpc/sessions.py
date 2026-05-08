from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from jsonrpcserver import Success, method
from sqlalchemy import func
from sqlmodel import select

from app.core.db import get_session as get_db_session
from app.models.database import Message, Session, Task
from app.rpc.pagination import fetch_datetime_cursor_page

logger = logging.getLogger(__name__)
STALE_PENDING_RUN_ERROR = "Run interrupted before completion."


def get_active_run_payload(context, session_id: str) -> dict[str, object] | None:
    """Return the in-memory active run for a session, if one is still running."""
    app_state = getattr(context, "app_state", None)
    if app_state is None:
        return None

    run_id = getattr(app_state, "session_run_index", {}).get(session_id)
    if not run_id:
        return None

    entry = getattr(app_state, "execute_runs", {}).get(run_id)
    if not entry:
        return None

    task = entry.get("task")
    if task is None or task.done():
        getattr(app_state, "execute_runs", {}).pop(run_id, None)
        if getattr(app_state, "session_run_index", {}).get(session_id) == run_id:
            getattr(app_state, "session_run_index", {}).pop(session_id, None)
        return None

    payload: dict[str, object] = {
        "run_id": run_id,
        "status": entry.get("status", "running"),
    }
    started_at = entry.get("started_at")
    if started_at:
        payload["started_at"] = started_at
    return payload


def finalize_stale_pending_runs(context, db_session, session_id: str) -> None:
    """Mark DB-pending runs as failed when no runtime task owns the session."""
    if get_active_run_payload(context, session_id) is not None:
        return

    pending_user_messages = list(db_session.exec(
        select(Message)
        .where(
            Message.session_id == session_id,
            Message.role == "user",
            func.json_extract(Message.metadata_, "$.run.status") == "pending",
        )
        .order_by(Message.created_at)
    ).all())
    if not pending_user_messages:
        return

    changed = False
    latest_pending_user_message = pending_user_messages[-1]
    for user_message in pending_user_messages:
        run_data = dict((user_message.metadata_ or {}).get("run") or {})
        run_id = str(run_data.get("id") or "").strip()
        if not run_id:
            continue

        failed_run_metadata = {
            "id": run_id,
            "status": "failed",
            "scope": run_data.get("scope") or "master",
            "error": STALE_PENDING_RUN_ERROR,
        }

        user_meta = dict(user_message.metadata_ or {})
        user_meta["run"] = failed_run_metadata
        user_message.metadata_ = user_meta
        db_session.add(user_message)

        if user_message.id != latest_pending_user_message.id:
            changed = True
            continue

        assistant_final = db_session.exec(
            select(Message)
            .where(
                Message.session_id == session_id,
                Message.role == "assistant",
                func.json_extract(Message.metadata_, "$.run.id") == run_id,
                func.json_extract(Message.metadata_, "$.run.status") != "pending",
            )
        ).first()
        if assistant_final is None:
            db_session.add(
                Message(
                    session_id=session_id,
                    role="assistant",
                    content=f"Run failed: {STALE_PENDING_RUN_ERROR}",
                    type="text",
                    metadata_={"run": failed_run_metadata},
                )
            )

        changed = True

    if not changed:
        return

    session_obj = db_session.get(Session, session_id)
    if session_obj:
        session_obj.updated_at = datetime.now(timezone.utc)
        db_session.add(session_obj)
    db_session.commit()


def serialize_session(session: Session, context=None) -> dict[str, object]:
    return {
        "id": session.id,
        "title": session.title,
        "updated_at": session.updated_at.isoformat(),
        "input_tokens": session.input_tokens,
        "output_tokens": session.output_tokens,
        "active_run": get_active_run_payload(context, session.id),
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
            "sessions": [serialize_session(session, context) for session in sessions_list],
            "next_cursor": next_cursor,
        })


@method
async def get_session(context, session_id: str):
    """Return a single chat session with its current runtime status."""
    logger.debug(f"Fetching session: {session_id}")
    with get_db_session() as db_session:
        session_obj = db_session.get(Session, session_id)
        if not session_obj:
            return Success({"status": "error", "message": "Session not found"})
        finalize_stale_pending_runs(context, db_session, session_id)
        db_session.refresh(session_obj)
        return Success(serialize_session(session_obj, context))


@method
async def list_messages(context, session_id: str, cursor: Optional[str] = None, limit: int = 50):
    """Return messages for a session with pagination."""
    logger.debug(f"Fetching messages for session: {session_id} (cursor: {cursor})")

    with get_db_session() as db_session:
        finalize_stale_pending_runs(context, db_session, session_id)
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
