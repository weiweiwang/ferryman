from __future__ import annotations

from typing import Optional, Any, Dict

from pydantic_ai.tools import RunContext
from sqlalchemy import String as SAString, desc, or_
from sqlmodel import select

from app.core.db import get_session
from app.core.deps import AgentDeps
from app.models.database import Schedule, Task

VALID_TASK_STATUSES = frozenset({"pending", "running", "success", "failed", "canceled"})
PREVIEW_LIMIT = 120


def _require_non_empty(field_name: str, value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty.")
    return normalized


def _render_preview(value: str, *, limit: int = PREVIEW_LIMIT) -> str:
    compact = " ".join((value or "").split())
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit - 3].rstrip()}..."


class TaskToolkit:
    """Persistent task and schedule definitions used by the agent runtime.

    The task helpers are the durable hand-off layer between an agent run and the
    local database. They intentionally stay small and explicit: create a task,
    update its lifecycle state, or search the backlog. The schedule helpers only
    persist schedule definitions today; they do not execute cron jobs yet.
    """

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
        """Persist a task request and return the canonical task identifier.

        This method packages the agent-facing inputs into the kernel's task
        schema and delegates deduplication to ``kernel.persist_task``. Callers
        should treat ``title`` as the stable fingerprint for the work item and
        ``instruction`` as the durable SOP for whoever resumes the task later.

        Args:
            ctx: Agent run context. ``ctx.deps.kernel`` receives the persistence
                request and ``ctx.deps.session_id`` is recorded on new tasks.
            title: Stable task fingerprint, such as
                ``"Submit example.com to AlternativeTo.net"``.
            instruction: Durable execution brief describing the expected outcome.
            metadata: Optional structured hooks that improve later search and
                filtering, for example a domain, URL, SKU, or username.
            parent_id: Optional parent task identifier for hierarchical work.

        Returns:
            A human-readable confirmation that includes the persisted task ID.

        Raises:
            ValueError: If ``title`` or ``instruction`` is blank.

        Example:
            create_task(
                title='Monitor prices for SKU-123',
                instruction='Check site X every 1h and report if price < $100',
                metadata={'sku': '123', 'site': 'X'}
            )
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
        """Update a persisted task's lifecycle state and optional progress note.

        Args:
            ctx: Agent run context containing the kernel dependency.
            task_id: Identifier returned by :meth:`create_task`.
            status: One of ``pending``, ``running``, ``success``, ``failed``, or
                ``canceled``.
            progress_note: Optional operator-facing note describing the latest
                milestone, blocker, or result. Passing an empty string clears the
                note while preserving the status update.

        Returns:
            A compact confirmation string containing the task ID and new status.

        Raises:
            ValueError: If ``task_id`` is blank or ``status`` is unsupported.
        """
        kernel = ctx.deps.kernel
        normalized_task_id = _require_non_empty("task_id", task_id)
        normalized_status = status.strip().lower()
        if normalized_status not in VALID_TASK_STATUSES:
            allowed = ", ".join(sorted(VALID_TASK_STATUSES))
            raise ValueError(f"status must be one of: {allowed}.")

        meta = {"progress_note": progress_note} if progress_note is not None else None
        kernel.persist_task_update(normalized_task_id, status=normalized_status, metadata=meta)
        return f"Task {normalized_task_id} updated to {normalized_status}"

    @staticmethod
    async def list_tasks(
            ctx: RunContext[AgentDeps], 
            status: Optional[str] = None,
            query: Optional[str] = None
    ) -> str:
        """Summarize persisted tasks with optional status and fuzzy text filters.

        Args:
            ctx: Agent run context. The current implementation lists tasks across
                all sessions so operators can triage work globally.
            status: Optional lifecycle filter. Must be one of
                ``pending``, ``running``, ``success``, ``failed``, or
                ``canceled``.
            query: Optional fuzzy text filter matched against the task title and
                serialized task payload.

        Returns:
            A human-readable multi-line summary suitable for an agent to inspect.

        Raises:
            ValueError: If ``status`` is provided but unsupported.
        """
        normalized_status: Optional[str] = None
        if status is not None:
            normalized_status = status.strip().lower()
            if normalized_status not in VALID_TASK_STATUSES:
                allowed = ", ".join(sorted(VALID_TASK_STATUSES))
                raise ValueError(f"status must be one of: {allowed}.")

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
            ctx: RunContext[AgentDeps], name: str, cron_expression: str, instruction: str
    ) -> str:
        """Persist a recurring schedule definition for later execution.

        This helper records the schedule's name, cron expression, and execution
        instruction in the database. It does not run the schedule immediately and
        it does not calculate ``next_run_at`` yet; those capabilities belong to
        the future scheduler service.

        Args:
            ctx: Agent run context. The current implementation does not bind a
                schedule to a session, but the context is kept for API symmetry
                with the other tool methods.
            name: Human-readable schedule name.
            cron_expression: Raw cron expression that a future scheduler will
                interpret.
            instruction: Durable execution brief to run whenever the schedule
                fires.

        Returns:
            A confirmation string containing the new schedule ID.

        Raises:
            ValueError: If any required field is blank.
        """
        normalized_name = _require_non_empty("name", name)
        normalized_cron = _require_non_empty("cron_expression", cron_expression)
        normalized_instruction = _require_non_empty("instruction", instruction)

        new_schedule = Schedule(
            name=normalized_name,
            cron_expression=normalized_cron,
            args={"instruction": normalized_instruction},
        )
        with get_session() as session:
            session.add(new_schedule)
            session.commit()
            session.refresh(new_schedule)
        return f"Schedule '{normalized_name}' created with ID: {new_schedule.id}"

    @staticmethod
    async def list_schedules(ctx: RunContext[AgentDeps]) -> str:
        """List persisted schedule definitions in recency order.

        Returns:
            A human-readable multi-line summary of saved schedules. The output is
            intentionally descriptive rather than machine-readable because the
            primary caller is the agent itself.
        """
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
