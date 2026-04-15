from __future__ import annotations

from typing import Optional, Any, Dict

from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.tools import RunContext
from sqlalchemy import String as SAString, desc, or_
from sqlmodel import select

from app.core.db import get_session
from app.core.deps import AgentDeps
from app.core.scheduler import compute_next_run_at, normalize_timezone_name
from app.models.database import Schedule, Task

VALID_TASK_STATUSES = frozenset({"pending", "running", "success", "failed", "canceled"})
PREVIEW_LIMIT = 120


def _require_non_empty(field_name: str, value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ModelRetry(f"{field_name} must not be empty.")
    return normalized


def _render_preview(value: str, *, limit: int = PREVIEW_LIMIT) -> str:
    compact = " ".join((value or "").split())
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit - 3].rstrip()}..."


class TaskToolkit:
    """Persist and query tasks and schedule definitions for the agent runtime."""

    @staticmethod
    def get_tools():
        return [
            TaskToolkit.create_task,
            TaskToolkit.update_task,
            TaskToolkit.list_tasks,
            TaskToolkit.create_schedule,
            TaskToolkit.list_schedules,
        ]

    @staticmethod
    async def create_task(
            ctx: RunContext[AgentDeps],
            title: str,
            instruction: str,
            metadata: Optional[Dict[str, Any]] = None,
            parent_id: Optional[str] = None
    ) -> str:
        """Create or deduplicate a persisted task.

        Stores the task title, instruction, and optional metadata, then returns
        a confirmation with the canonical task ID.
        """
        kernel = ctx.deps.kernel
        session_id = ctx.deps.session_id
        normalized_title = _require_non_empty("title", title)
        normalized_instruction = _require_non_empty("instruction", instruction)

        task_args = {
            "instruction": normalized_instruction,
            "payload": dict(metadata or {}),
        }

        task = kernel.persist_task(
            session_id=session_id,
            title=normalized_title,
            parent_id=parent_id,
            args=task_args,
        )
        return f"Task created/verified: ID={task.id}, Title='{task.title}'"

    @staticmethod
    async def update_task(
            ctx: RunContext[AgentDeps], task_id: str, status: str, progress_note: Optional[str] = None
    ) -> str:
        """Update a task status and optional progress note.

        `status` must be one of: pending, running, success, failed, or canceled.
        """
        kernel = ctx.deps.kernel
        normalized_task_id = _require_non_empty("task_id", task_id)
        normalized_status = status.strip().lower()
        if normalized_status not in VALID_TASK_STATUSES:
            allowed = ", ".join(sorted(VALID_TASK_STATUSES))
            raise ModelRetry(f"status must be one of: {allowed}.")

        meta = {"progress_note": progress_note} if progress_note is not None else None
        kernel.persist_task_update(normalized_task_id, status=normalized_status, metadata=meta)
        return f"Task {normalized_task_id} updated to {normalized_status}"

    @staticmethod
    async def list_tasks(
            ctx: RunContext[AgentDeps], 
            status: Optional[str] = None,
            query: Optional[str] = None
    ) -> str:
        """List persisted tasks with optional status and text filters."""
        normalized_status: Optional[str] = None
        if status is not None:
            normalized_status = status.strip().lower()
            if normalized_status not in VALID_TASK_STATUSES:
                allowed = ", ".join(sorted(VALID_TASK_STATUSES))
                raise ModelRetry(f"status must be one of: {allowed}.")

        normalized_query = query.strip() if query else None

        with get_session() as db_session:
            statement = select(Task)
            if normalized_status:
                statement = statement.where(Task.status == normalized_status)
            if normalized_query:
                statement = statement.where(
                    or_(
                        Task.title.contains(normalized_query),
                        Task.args.cast(SAString).contains(normalized_query),
                    )
                )
            statement = statement.order_by(desc(Task.updated_at), desc(Task.id))
            tasks = db_session.exec(statement).all()

            if not tasks:
                status_msg = f" with status '{normalized_status}'" if normalized_status else ""
                query_msg = f" matching '{normalized_query}'" if normalized_query else ""
                return f"No tasks found{status_msg}{query_msg}."

            lines = [f"Found {len(tasks)} tasks:"]
            for t in tasks:
                instruction = t.args.get("instruction", "No instruction")
                payload = t.args.get("payload", {})
                lines.append(f"- ID: {t.id} | [{t.status}] {t.title}")
                lines.append(f"  Context: {_render_preview(instruction)}")
                if payload:
                    lines.append(f"  Metadata: {payload}")

            return "\n".join(lines)

    @staticmethod
    async def create_schedule(
            ctx: RunContext[AgentDeps],
            name: str,
            cron_expression: str,
            instruction: str,
            timezone: Optional[str] = None,
    ) -> str:
        """Create a persisted schedule definition.

        Stores the name, cron expression, and instruction in the database. This
        tool does not execute the schedule.
        """
        kernel = ctx.deps.kernel
        normalized_name = _require_non_empty("name", name)
        normalized_cron = _require_non_empty("cron_expression", cron_expression)
        normalized_instruction = _require_non_empty("instruction", instruction)
        normalized_timezone = normalize_timezone_name(timezone)
        next_run_at = compute_next_run_at(normalized_cron, normalized_timezone)

        new_schedule = Schedule(
            name=normalized_name,
            cron_expression=normalized_cron,
            timezone=normalized_timezone,
            args={"instruction": normalized_instruction},
            next_run_at=next_run_at,
        )
        with get_session() as session:
            session.add(new_schedule)
            session.commit()
            session.refresh(new_schedule)
        schedule_manager = getattr(kernel, "schedule_manager", None)
        if schedule_manager:
            await schedule_manager.sync_schedule(new_schedule.id)
        return f"Schedule '{normalized_name}' created with ID: {new_schedule.id}"

    @staticmethod
    async def list_schedules(ctx: RunContext[AgentDeps]) -> str:
        """List persisted schedule definitions in recency order."""
        with get_session() as session:
            schedules = session.exec(
                select(Schedule).order_by(desc(Schedule.updated_at), desc(Schedule.id))
            ).all()
            if not schedules:
                return "No schedules registered."
            lines = ["Registered Automated Routines:"]
            for s in schedules:
                status = "Enabled" if s.enabled else "Disabled"
                lines.append(f"- [{status}] ID: {s.id} | Name: {s.name} | Cron: {s.cron_expression}")
            return "\n".join(lines)
