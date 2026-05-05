from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from jsonrpcserver import Success, method
from sqlalchemy import String as SAString, func, or_
from sqlmodel import select

from app.core.db import get_session
from app.models.database import Task
from app.rpc.pagination import fetch_datetime_cursor_page
from app.rpc.serializers import serialize_task

logger = logging.getLogger(__name__)


@method
async def list_tasks(
    context,
    session_id: Optional[str] = None,
    status: Optional[str] = None,
    query: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: int = 50,
):
    """List tasks, optionally filtered by session/status/query, with cursor-based pagination."""
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
            "tasks": [serialize_task(task) for task in tasks],
            "next_cursor": next_cursor,
            "summary": {
                **status_counts,
                "total": sum(status_counts.values()),
            },
        })


@method
async def get_task(context, task_id: str):
    """Return a single task with editable details."""
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
    payload: Optional[dict[str, object]] = None,
):
    """Update editable task fields."""
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
    """Delete a task."""
    logger.info(f"Deleting task: {task_id}")
    with get_session() as session:
        task = session.get(Task, task_id)
        if not task:
            return Success({"status": "error", "message": "Task not found"})
        session.delete(task)
        session.commit()
        return Success({"status": "success"})

