from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import select

from app.core.db import get_session
from app.models.database import Task
from app.models.schemas import TaskStatus

logger = logging.getLogger(__name__)


class TaskManager:
    """Manage Ferryman task records and task state transitions."""

    @staticmethod
    def find_duplicate_task(title: str) -> Optional[Task]:
        """Search for an existing active task using order-agnostic word similarity."""
        import difflib

        def normalize(text: str) -> str:
            cleaned = "".join(c if c.isalnum() else " " for c in (text or "").lower())
            return " ".join(sorted(cleaned.split()))

        norm_title = normalize(title)
        if not norm_title:
            return None

        with get_session() as session:
            statement = select(Task).where(Task.status.in_(["pending", "running"]))  # type:ignore
            candidates = session.exec(statement).all()

            for candidate in candidates:
                norm_candidate = normalize(candidate.title)
                ratio = difflib.SequenceMatcher(None, norm_title, norm_candidate).ratio()
                if ratio > 0.85:
                    logger.info(
                        f"Task deduplication: {title!r} matched {candidate.title!r} "
                        f"(normalized ratio {ratio:.2f})"
                    )
                    return candidate

        return None

    def persist_task(
            self,
            session_id: str,
            title: str,
            parent_id: Optional[str] = None,
            args: Optional[dict[str, object]] = None,
    ) -> Task:
        existing = self.find_duplicate_task(title)
        if existing:
            return existing

        logger.debug(f"Creating task: {title} (session_id: {session_id}, parent_id: {parent_id})")
        task = Task(
            session_id=session_id,
            parent_id=parent_id,
            title=title,
            args=args or {},
        )
        with get_session() as session:
            session.add(task)
            session.commit()
            session.refresh(task)
            logger.debug(f"Task persisted to DB with ID: {task.id}")

        return task

    @staticmethod
    def persist_task_update(
            task_id: str,
            status: Optional[str] = None,
            metadata: Optional[dict[str, object]] = None,
    ) -> None:
        logger.debug(f"Updating task {task_id}: status={status}, metadata={metadata}")
        with get_session() as session:
            statement = select(Task).where(Task.id == task_id)
            db_task = session.exec(statement).first()

            if not db_task:
                return

            if status:
                db_task.status = status
                if status in (TaskStatus.SUCCESS, TaskStatus.FAILED):
                    db_task.finished_at = datetime.now(timezone.utc)
            if metadata:
                next_metadata = dict(db_task.metadata_)
                next_metadata.update(metadata)
                db_task.metadata_ = next_metadata
            db_task.updated_at = datetime.now(timezone.utc)
            session.add(db_task)
            session.commit()
