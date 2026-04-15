from __future__ import annotations
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlmodel import select

from app.core.config import Settings
from app.core.db import get_session
from app.models.database import Schedule, Session

logger = logging.getLogger(__name__)

DEFAULT_TIMEZONE = "UTC"


def get_default_timezone_name() -> str:
    env_timezone = os.environ.get("TZ", "").strip()
    if env_timezone:
        try:
            ZoneInfo(env_timezone)
            return env_timezone
        except ZoneInfoNotFoundError:
            logger.warning("Ignoring invalid TZ environment variable: %s", env_timezone)

    local_tz = datetime.now().astimezone().tzinfo
    for attr in ("key", "zone"):
        name = getattr(local_tz, attr, None)
        if isinstance(name, str) and name:
            return name

    candidate = str(local_tz) if local_tz else ""
    if candidate and "/" in candidate:
        try:
            ZoneInfo(candidate)
            return candidate
        except ZoneInfoNotFoundError:
            logger.warning("Falling back to UTC for unrecognized local timezone: %s", candidate)

    return DEFAULT_TIMEZONE


def normalize_timezone_name(timezone_name: Optional[str]) -> str:
    candidate = (timezone_name or "").strip() or get_default_timezone_name()
    try:
        ZoneInfo(candidate)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Invalid timezone: {candidate}") from exc
    return candidate


def build_cron_trigger(cron_expression: str, timezone_name: Optional[str] = None) -> CronTrigger:
    normalized_cron = cron_expression.strip()
    if not normalized_cron:
        raise ValueError("cron_expression must not be empty.")

    normalized_timezone = normalize_timezone_name(timezone_name)
    try:
        return CronTrigger.from_crontab(
            normalized_cron,
            timezone=ZoneInfo(normalized_timezone),
        )
    except ValueError as exc:
        raise ValueError(f"Invalid cron expression: {exc}") from exc


def compute_next_run_at(
    cron_expression: str,
    timezone_name: Optional[str] = None,
    *,
    now: Optional[datetime] = None,
) -> Optional[datetime]:
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    else:
        current_time = current_time.astimezone(timezone.utc)

    trigger = build_cron_trigger(cron_expression, timezone_name)
    next_fire_time = trigger.get_next_fire_time(previous_fire_time=None, now=current_time)
    if next_fire_time is None:
        return None
    if next_fire_time.tzinfo is None:
        next_fire_time = next_fire_time.replace(tzinfo=timezone.utc)
    return next_fire_time.astimezone(timezone.utc)


class FerrymanScheduler:
    """Bridge persisted schedules in SQLite to in-process APScheduler jobs."""

    def __init__(self, kernel, settings: Settings) -> None:
        self.kernel = kernel
        self.settings = settings
        self._scheduler: Optional[AsyncIOScheduler] = None

    async def start(self) -> None:
        scheduler = AsyncIOScheduler(
            timezone=timezone.utc,
            job_defaults={
                "coalesce": True,
                "max_instances": 1,
                "misfire_grace_time": self.settings.get("system.schedule.misfire_grace_time", 300),
            },
        )
        scheduler.start()
        self._scheduler = scheduler
        self.kernel.schedule_manager = self
        await self.sync_all()

    async def shutdown(self) -> None:
        scheduler = self._scheduler
        self._scheduler = None
        self.kernel.schedule_manager = None
        if scheduler:
            scheduler.shutdown(wait=False)

    async def sync_all(self) -> None:
        with get_session() as session:
            schedules = list(session.exec(select(Schedule)).all())
        for schedule in schedules:
            try:
                await self.sync_schedule(schedule.id)
            except Exception as exc:
                logger.exception("Skipping invalid persisted schedule during scheduler sync: %s", schedule.id)
                self._mark_schedule_invalid(schedule.id, exc)

    async def sync_schedule(self, schedule_id: str) -> None:
        scheduler = self._require_scheduler()
        with get_session() as session:
            schedule = session.get(Schedule, schedule_id)
            if not schedule:
                self._remove_job_if_present(schedule_id)
                return

            if not schedule.enabled:
                self._remove_job_if_present(schedule_id)
                if schedule.next_run_at is not None:
                    schedule.next_run_at = None
                    session.add(schedule)
                    session.commit()
                return

            trigger = build_cron_trigger(schedule.cron_expression, schedule.timezone)
            schedule.timezone = normalize_timezone_name(schedule.timezone)
            job = scheduler.add_job(
                self._run_schedule,
                trigger=trigger,
                args=[schedule.id],
                id=schedule.id,
                replace_existing=True,
            )
            schedule.next_run_at = self._normalize_utc(job.next_run_time)
            session.add(schedule)
            session.commit()

    async def remove_schedule(self, schedule_id: str) -> None:
        self._remove_job_if_present(schedule_id)

    async def _run_schedule(self, schedule_id: str) -> None:
        logger.info("Running scheduled task for schedule %s", schedule_id)
        with get_session() as session:
            schedule = session.get(Schedule, schedule_id)
            if not schedule or not schedule.enabled:
                self._remove_job_if_present(schedule_id)
                return
            instruction = str(schedule.args.get("instruction", "")).strip()
            schedule_name = schedule.name

        if not instruction:
            logger.warning("Skipping schedule %s because instruction is empty", schedule_id)
            self._mark_schedule_invalid(schedule_id, ValueError("instruction must not be empty."))
            return

        self._ensure_schedule_session(schedule_id, schedule_name)
        last_run_result: dict[str, Any]

        try:
            result = await self.kernel.run_master_agent(instruction, session_id=schedule_id)
            last_run_result = self._build_last_run_result(result)
        except Exception as exc:
            logger.exception("Scheduled run failed for schedule %s", schedule_id)
            last_run_result = self._build_last_run_result_from_exception(exc)
        finally:
            with get_session() as session:
                schedule = session.get(Schedule, schedule_id)
                if not schedule:
                    return
                schedule.last_run_at = datetime.now(timezone.utc)
                schedule.total_run_count += 1
                schedule.last_run_result = last_run_result
                job = self._get_job(schedule_id)
                schedule.next_run_at = self._normalize_utc(job.next_run_time if job else None)
                session.add(schedule)
                session.commit()

    def _ensure_schedule_session(self, schedule_id: str, schedule_name: str) -> None:
        with get_session() as session:
            session_obj = session.get(Session, schedule_id)
            if session_obj:
                updated = False
                metadata = dict(session_obj.metadata_ or {})
                if metadata.get("kind") != "schedule":
                    metadata.update({"kind": "schedule", "schedule_id": schedule_id})
                    session_obj.metadata_ = metadata
                    updated = True
                if not session_obj.title:
                    session_obj.title = schedule_name
                    updated = True
                if updated:
                    session.add(session_obj)
                    session.commit()
                return

            session.add(
                Session(
                    id=schedule_id,
                    title=schedule_name,
                    metadata_={"kind": "schedule", "schedule_id": schedule_id},
                )
            )
            session.commit()

    def _require_scheduler(self):
        if not self._scheduler:
            raise RuntimeError("Scheduler has not been started.")
        return self._scheduler

    def _remove_job_if_present(self, schedule_id: str) -> None:
        scheduler = self._scheduler
        if not scheduler:
            return
        try:
            scheduler.remove_job(schedule_id)
        except Exception:
            pass

    def _mark_schedule_invalid(self, schedule_id: str, exc: Exception) -> None:
        self._remove_job_if_present(schedule_id)

        with get_session() as session:
            schedule = session.get(Schedule, schedule_id)
            if not schedule:
                return

            schedule.enabled = False
            schedule.next_run_at = None
            schedule.last_run_result = {
                "status": "failed",
                "summary": "Schedule disabled because its configuration is invalid.",
                "error": self._truncate_summary(str(exc), limit=500),
                "run_id": None,
                "finished_at": datetime.now(timezone.utc).isoformat(),
            }
            session.add(schedule)
            session.commit()

    def _get_job(self, schedule_id: str):
        scheduler = self._scheduler
        if not scheduler:
            return None
        return scheduler.get_job(schedule_id)

    @staticmethod
    def _build_last_run_result(result: Any) -> dict[str, Any]:
        finished_at = datetime.now(timezone.utc).isoformat()
        if not isinstance(result, dict):
            return {
                "status": "success",
                "summary": FerrymanScheduler._truncate_summary(str(result)),
                "error": None,
                "run_id": None,
                "finished_at": finished_at,
            }

        payload = result.get("payload", {}) if isinstance(result.get("payload"), dict) else {}
        messages = payload.get("messages", []) if isinstance(payload.get("messages"), list) else []
        last_message = messages[-1] if messages and isinstance(messages[-1], dict) else {}
        message_content = str(last_message.get("content", "")).strip() or None
        run_metadata = last_message.get("metadata", {}).get("run", {}) if isinstance(last_message.get("metadata"), dict) else {}
        status = run_metadata.get("status") if isinstance(run_metadata, dict) else None
        normalized_status = "failed" if status == "failed" else "success"
        error = run_metadata.get("error") if isinstance(run_metadata, dict) else None

        return {
            "status": normalized_status,
            "summary": None if normalized_status == "failed" else FerrymanScheduler._truncate_summary(message_content),
            "error": str(error).strip() if error else None,
            "run_id": payload.get("run_id"),
            "finished_at": finished_at,
        }

    @staticmethod
    def _build_last_run_result_from_exception(exc: Exception) -> dict[str, Any]:
        return {
            "status": "failed",
            "summary": None,
            "error": FerrymanScheduler._truncate_summary(str(exc), limit=500),
            "run_id": None,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _truncate_summary(value: Optional[str], *, limit: int = 1000) -> Optional[str]:
        if value is None:
            return None
        compact = " ".join(value.split())
        if len(compact) <= limit:
            return compact
        return f"{compact[:limit - 3].rstrip()}..."

    @staticmethod
    def _normalize_utc(value: Optional[datetime]) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
