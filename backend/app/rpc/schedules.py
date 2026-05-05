from __future__ import annotations

import logging
from datetime import datetime, timezone as dt_timezone
from typing import Optional

from jsonrpcserver import Success, method
from sqlmodel import select

from app.core.db import get_session
from app.core.schedule_manager import compute_next_run_at, normalize_timezone_name
from app.models.database import Schedule
from app.rpc.pagination import fetch_datetime_cursor_page
from app.rpc.serializers import serialize_schedule

logger = logging.getLogger(__name__)


@method
async def list_schedules(context, cursor: Optional[str] = None, limit: int = 50):
    """List automated routines with cursor-based pagination."""
    logger.debug(f"Listing automated schedules (cursor: {cursor}, limit: {limit})")

    with get_session() as session:
        schedules, next_cursor = fetch_datetime_cursor_page(
            session,
            select(Schedule),
            model=Schedule,
            sort_field="created_at",
            cursor=cursor,
            limit=limit,
        )

        logger.debug(f"Found {len(schedules)} schedules")
        return Success({
            "schedules": [serialize_schedule(schedule) for schedule in schedules],
            "next_cursor": next_cursor,
        })


@method
async def get_schedule(context, schedule_id: str):
    """Return a single schedule with editable details."""
    logger.debug(f"Fetching schedule detail: {schedule_id}")
    with get_session() as session:
        schedule = session.get(Schedule, schedule_id)
        if not schedule:
            return Success({"status": "error", "message": "Schedule not found"})
        return Success({"schedule": serialize_schedule(schedule, detail=True)})


@method
async def update_schedule(
    context,
    schedule_id: str,
    name: Optional[str] = None,
    cron: Optional[str] = None,
    timezone: Optional[str] = None,
    enabled: Optional[bool] = None,
    instruction: Optional[str] = None,
):
    """Update editable schedule fields."""
    logger.info(f"Updating schedule: {schedule_id}")

    with get_session() as session:
        schedule = session.get(Schedule, schedule_id)
        if not schedule:
            return Success({"status": "error", "message": "Schedule not found"})

        target_enabled = enabled if enabled is not None else schedule.enabled
        candidate_name = name if name is not None else schedule.name
        candidate_cron = cron if cron is not None else schedule.cron_expression
        candidate_timezone = timezone if timezone is not None else schedule.timezone
        candidate_instruction = instruction if instruction is not None else schedule.args.get("instruction", "")

        try:
            if name is not None or target_enabled:
                candidate_name = candidate_name.strip()
                if not candidate_name:
                    raise ValueError("name must not be empty.")

            if instruction is not None or target_enabled:
                candidate_instruction = candidate_instruction.strip()
                if not candidate_instruction:
                    raise ValueError("instruction must not be empty.")

            normalized_cron = candidate_cron.strip()
            if cron is not None and not normalized_cron:
                raise ValueError("cron must not be empty.")

            if timezone is not None or target_enabled:
                normalized_timezone = normalize_timezone_name(candidate_timezone)
            else:
                normalized_timezone = schedule.timezone

            if target_enabled:
                if not normalized_cron:
                    raise ValueError("cron must not be empty.")
                next_run_at = compute_next_run_at(normalized_cron, normalized_timezone)
            else:
                next_run_at = None
        except ValueError as exc:
            return Success({"status": "error", "message": str(exc)})

        if name is not None:
            schedule.name = candidate_name
        if cron is not None:
            schedule.cron_expression = normalized_cron
        if timezone is not None:
            schedule.timezone = normalized_timezone
        if enabled is not None:
            schedule.enabled = enabled
        if instruction is not None:
            args = dict(schedule.args or {})
            args["instruction"] = candidate_instruction
            schedule.args = args
        schedule.next_run_at = next_run_at

        schedule.updated_at = datetime.now(dt_timezone.utc)
        session.add(schedule)
        session.commit()

    schedule_manager = getattr(context, "schedule_manager", None)
    if schedule_manager:
        await schedule_manager.sync_schedule(schedule_id)
    return Success({"status": "success"})


@method
async def delete_schedule(context, schedule_id: str):
    """Delete a schedule."""
    logger.info(f"Deleting schedule: {schedule_id}")
    with get_session() as session:
        schedule = session.get(Schedule, schedule_id)
        if not schedule:
            return Success({"status": "error", "message": "Schedule not found"})
        session.delete(schedule)
        session.commit()
    schedule_manager = getattr(context, "schedule_manager", None)
    if schedule_manager:
        await schedule_manager.remove_schedule(schedule_id)
    return Success({"status": "success"})

