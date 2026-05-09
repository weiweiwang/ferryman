from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from enum import StrEnum
from typing import Awaitable, Callable, Optional

from app.models.events import FerrymanEventEnvelope


class ActiveRunStatus(StrEnum):
    RUNNING = "running"
    CANCELING = "canceling"


class RunAlreadyActiveError(RuntimeError):
    """Raised when a session already has a live agent run."""

    def __init__(self, *, session_id: str, run_id: str) -> None:
        super().__init__("Current session already has an active run.")
        self.session_id = session_id
        self.run_id = run_id


class RunRegistry:
    """Process-local control plane for live agent runs."""

    def __init__(self, runtime) -> None:
        self._runtime = runtime
        self._runs_by_id: dict[str, dict[str, object]] = {}
        self._run_id_by_session: dict[str, str] = {}

    def start_run(
        self,
        *,
        session_id: str,
        instruction: str,
        run_id: str,
        source: str,
        emit_event_cb: Optional[Callable[[FerrymanEventEnvelope], Awaitable[None]]] = None,
    ) -> asyncio.Task[dict[str, object]]:
        active_run = self.get_active_run_payload(session_id)
        if active_run is not None:
            raise RunAlreadyActiveError(
                session_id=session_id,
                run_id=str(active_run["run_id"]),
            )

        started_at = datetime.now(timezone.utc).isoformat()
        runner_task = asyncio.create_task(
            self._run_agent(
                instruction=instruction,
                session_id=session_id,
                run_id=run_id,
                emit_event_cb=emit_event_cb,
            )
        )
        self._runs_by_id[run_id] = {
            "session_id": session_id,
            "instruction": instruction,
            "source": source,
            "status": ActiveRunStatus.RUNNING,
            "started_at": started_at,
            "runner_task": runner_task,
        }
        self._run_id_by_session[session_id] = run_id
        return runner_task

    def get_active_run_payload(self, session_id: str) -> dict[str, object] | None:
        run_id = self._run_id_by_session.get(session_id)
        if not run_id:
            return None

        entry = self._runs_by_id.get(run_id)
        if not entry:
            self._run_id_by_session.pop(session_id, None)
            return None

        runner_task = entry.get("runner_task")
        if not isinstance(runner_task, asyncio.Task) or runner_task.done():
            self._forget_run(run_id, session_id)
            return None

        status = entry.get("status", ActiveRunStatus.RUNNING)
        if isinstance(status, ActiveRunStatus):
            status_value = status.value
        else:
            status_value = str(status)

        return {
            "run_id": run_id,
            "status": status_value,
            "started_at": entry.get("started_at"),
        }

    def cancel_run(self, run_id: str, *, session_id: str | None = None) -> dict[str, object]:
        entry = self._runs_by_id.get(run_id)
        if not entry:
            return {"status": "not_found", "run_id": run_id}

        entry_session_id = str(entry["session_id"])
        if session_id and entry_session_id != session_id:
            return {
                "status": "error",
                "message": "run_id does not match session_id",
                "run_id": run_id,
            }

        runner_task = entry.get("runner_task")
        if not isinstance(runner_task, asyncio.Task):
            self._forget_run(run_id, entry_session_id)
            return {"status": "not_found", "run_id": run_id}

        if runner_task.done():
            self._forget_run(run_id, entry_session_id)
            return {
                "status": "already_finished",
                "run_id": run_id,
                "session_id": entry_session_id,
            }

        entry["status"] = ActiveRunStatus.CANCELING
        runner_task.cancel()
        return {"status": "canceling", "run_id": run_id, "session_id": entry_session_id}

    async def _run_agent(
        self,
        *,
        instruction: str,
        session_id: str,
        run_id: str,
        emit_event_cb: Optional[Callable[[FerrymanEventEnvelope], Awaitable[None]]] = None,
    ) -> dict[str, object]:
        try:
            return await self._runtime.run_master_agent(
                instruction=instruction,
                session_id=session_id,
                run_id=run_id,
                emit_event_cb=emit_event_cb,
            )
        finally:
            self._forget_run(run_id, session_id)

    def _forget_run(self, run_id: str, session_id: str) -> None:
        self._runs_by_id.pop(run_id, None)
        if self._run_id_by_session.get(session_id) == run_id:
            self._run_id_by_session.pop(session_id, None)
