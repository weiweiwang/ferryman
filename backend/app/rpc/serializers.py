from __future__ import annotations

from datetime import date, datetime

from app.core.utc_datetime import format_utc_datetime
from app.models.database import Schedule, Task


def format_optional_date(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return None


def serialize_task(task: Task, *, detail: bool = False) -> dict[str, object]:
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


def serialize_schedule(schedule: Schedule, *, detail: bool = False) -> dict[str, object]:
    payload = {
        "id": schedule.id,
        "name": schedule.name,
        "cron": schedule.cron_expression,
        "timezone": schedule.timezone or "UTC",
        "enabled": schedule.enabled,
        "last_run_at": format_utc_datetime(schedule.last_run_at) if schedule.last_run_at else None,
        "next_run_at": format_utc_datetime(schedule.next_run_at) if schedule.next_run_at else None,
        "total_run_count": schedule.total_run_count,
        "updated_at": format_utc_datetime(schedule.updated_at),
    }
    if detail:
        payload.update({
            "instruction": schedule.args.get("instruction", ""),
            "last_run_result": schedule.last_run_result,
            "created_at": format_utc_datetime(schedule.created_at),
        })
    return payload

