from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.events import EVENT_JOB_MISSED
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlmodel import select

from app.core.config import Settings
from app.core.db import get_session
from app.models.database import Schedule, Session

logger = logging.getLogger(__name__)

DEFAULT_TIMEZONE = "UTC"
CATCHUP_JOB_SUFFIX = ":catchup"
DEFAULT_CATCHUP_GRACE_TIME_SECONDS = 4 * 60 * 60
DEFAULT_CATCHUP_SKIP_IF_NEXT_WITHIN_SECONDS = 60 * 60


def get_default_timezone_name() -> str:
    env_timezone = os.environ.get("TZ", "").strip()
    if env_timezone:
        try:
            ZoneInfo(env_timezone)
            return env_timezone
        except ZoneInfoNotFoundError:
            logger.warning(f"Ignoring invalid TZ environment variable: {env_timezone}")

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
            logger.warning(f"Falling back to UTC for unrecognized local timezone: {candidate}")

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


class ScheduleManager:
    """Bridge persisted schedules in SQLite to in-process APScheduler jobs."""

    def __init__(self, runtime, settings: Settings) -> None:
        self.runtime = runtime
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
        scheduler.add_listener(self._handle_job_missed, EVENT_JOB_MISSED)
        scheduler.start()
        self._scheduler = scheduler
        await self.sync_all()

    async def shutdown(self) -> None:
        scheduler = self._scheduler
        self._scheduler = None
        if scheduler:
            scheduler.shutdown(wait=False)

    async def sync_all(self) -> None:
        with get_session() as session:
            schedules = list(session.exec(select(Schedule)).all())
        for schedule in schedules:
            try:
                await self.sync_schedule(schedule.id)
            except Exception as exc:
                logger.exception(f"Skipping invalid persisted schedule during scheduler sync: {schedule.id}")
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
                self._remove_job_if_present(self._catchup_job_id(schedule_id))
                if schedule.next_run_at is not None:
                    schedule.next_run_at = None
                    session.add(schedule)
                    session.commit()
                return

            now = datetime.now(timezone.utc)
            missed_run_at = self._normalize_utc(schedule.next_run_at)
            trigger = build_cron_trigger(schedule.cron_expression, schedule.timezone)
            schedule.timezone = normalize_timezone_name(schedule.timezone)
            job = scheduler.add_job(
                self._run_schedule,
                trigger=trigger,
                args=[schedule.id, "scheduled"],
                id=schedule.id,
                replace_existing=True,
            )
            next_regular_run_at = self._normalize_utc(job.next_run_time)
            schedule.next_run_at = next_regular_run_at
            session.add(schedule)
            session.commit()

        self._schedule_catchup_if_needed(
            schedule_id=schedule_id,
            missed_run_at=missed_run_at,
            next_regular_run_at=next_regular_run_at,
            now=now,
        )

    async def remove_schedule(self, schedule_id: str) -> None:
        self._remove_job_if_present(schedule_id)
        self._remove_job_if_present(self._catchup_job_id(schedule_id))

    async def _run_schedule(self, schedule_id: str, trigger: str = "scheduled") -> None:
        logger.info(f"Running scheduled task for schedule {schedule_id} via {trigger}")
        with get_session() as session:
            schedule = session.get(Schedule, schedule_id)
            if not schedule or not schedule.enabled:
                self._remove_job_if_present(schedule_id)
                return
            instruction = str(schedule.args.get("instruction", "")).strip()
            schedule_name = schedule.name

        if not instruction:
            logger.warning(f"Skipping schedule {schedule_id} because instruction is empty")
            self._mark_schedule_invalid(schedule_id, ValueError("instruction must not be empty."))
            return

        self._ensure_schedule_session(schedule_id, schedule_name)
        started_at = datetime.now(timezone.utc)
        finished_at = started_at
        last_run_result = self._build_last_run_result_from_exception(
            RuntimeError("Schedule run did not finish."),
            trigger=trigger,
            started_at=started_at,
            finished_at=finished_at,
        )

        try:
            result = await self.runtime.run_master_agent(instruction, session_id=schedule_id)
            finished_at = datetime.now(timezone.utc)
            last_run_result = self._build_last_run_result(
                result,
                trigger=trigger,
                started_at=started_at,
                finished_at=finished_at,
            )
        except Exception as exc:
            logger.exception(f"Scheduled run failed for schedule {schedule_id}")
            finished_at = datetime.now(timezone.utc)
            last_run_result = self._build_last_run_result_from_exception(
                exc,
                trigger=trigger,
                started_at=started_at,
                finished_at=finished_at,
            )
        finally:
            with get_session() as session:
                schedule = session.get(Schedule, schedule_id)
                if not schedule:
                    return
                schedule.last_run_at = finished_at
                schedule.total_run_count += 1
                schedule.last_run_result = last_run_result
                job = self._get_job(schedule_id)
                schedule.next_run_at = self._normalize_utc(job.next_run_time if job else None)
                session.add(schedule)
                session.commit()

    @staticmethod
    def _ensure_schedule_session(schedule_id: str, schedule_name: str) -> None:
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
        except Exception as e:
            logger.exception(f"Failed to remove job:schedule_id with exception:{e}")
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

    def _handle_job_missed(self, event) -> None:
        try:
            self._handle_job_missed_inner(event)
        except Exception as e:
            job_id = getattr(event, "job_id", None)
            logger.exception(f"Failed to handle missed schedule job:{job_id} with exception:{e}")

    def _handle_job_missed_inner(self, event) -> None:
        schedule_id = getattr(event, "job_id", None)
        if not isinstance(schedule_id, str) or schedule_id.endswith(CATCHUP_JOB_SUFFIX):
            return

        missed_run_at = self._normalize_utc(getattr(event, "scheduled_run_time", None))
        if missed_run_at is None:
            return

        job = self._get_job(schedule_id)
        next_regular_run_at = self._normalize_utc(job.next_run_time if job else None)
        if next_regular_run_at is None:
            return

        with get_session() as session:
            schedule = session.get(Schedule, schedule_id)
            if not schedule or not schedule.enabled:
                return
            schedule.next_run_at = next_regular_run_at
            session.add(schedule)
            session.commit()

        now = datetime.now(timezone.utc)
        logger.info(f"Handling missed schedule {schedule_id} from {missed_run_at}")
        self._schedule_catchup_if_needed(
            schedule_id=schedule_id,
            missed_run_at=missed_run_at,
            next_regular_run_at=next_regular_run_at,
            now=now,
        )

    def _schedule_catchup_if_needed(
            self,
            *,
            schedule_id: str,
            missed_run_at: Optional[datetime],
            next_regular_run_at: Optional[datetime],
            now: datetime,
    ) -> None:
        scheduler = self._require_scheduler()
        if not self.settings.get("system.schedule.catchup_enabled", True):
            return
        if missed_run_at is None or next_regular_run_at is None:
            return
        if missed_run_at > now:
            return

        catchup_grace_time = timedelta(
            seconds=self.settings.get(
                "system.schedule.catchup_grace_time",
                DEFAULT_CATCHUP_GRACE_TIME_SECONDS,
            )
        )
        catchup_skip_if_next_within = timedelta(
            seconds=self.settings.get(
                "system.schedule.catchup_skip_if_next_within",
                DEFAULT_CATCHUP_SKIP_IF_NEXT_WITHIN_SECONDS,
            )
        )
        lateness = now - missed_run_at
        time_until_next = next_regular_run_at - now
        if lateness > catchup_grace_time:
            logger.info(
                f"Skipping catch-up for schedule {schedule_id} "
                f"because missed run is outside grace time: {lateness}"
            )
            return
        if time_until_next <= catchup_skip_if_next_within:
            logger.info(
                f"Skipping catch-up for schedule {schedule_id} "
                f"because next regular run is too close: {time_until_next}"
            )
            return

        scheduler.add_job(
            self._run_schedule,
            trigger="date",
            run_date=now,
            args=[schedule_id, "catch_up"],
            id=self._catchup_job_id(schedule_id),
            replace_existing=True,
            misfire_grace_time=self.settings.get("system.schedule.misfire_grace_time", 300),
        )
        logger.info(f"Scheduled catch-up run for schedule {schedule_id} missed at {missed_run_at}")

    @staticmethod
    def _catchup_job_id(schedule_id: str) -> str:
        return f"{schedule_id}{CATCHUP_JOB_SUFFIX}"

    @staticmethod
    def _build_last_run_result(
            result: object,
            *,
            trigger: str,
            started_at: datetime,
            finished_at: datetime,
    ) -> dict[str, object]:
        duration_ms = ScheduleManager._duration_ms(started_at, finished_at)
        base_result = {
            "trigger": trigger,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "duration_ms": duration_ms,
        }
        if not isinstance(result, dict):
            return {
                "status": "success",
                "summary": ScheduleManager._truncate_summary(str(result)),
                "error": None,
                "run_id": None,
                **base_result,
            }

        payload = result.get("payload", {}) if isinstance(result.get("payload"), dict) else {}
        messages = payload.get("messages", []) if isinstance(payload.get("messages"), list) else []
        last_message = messages[-1] if messages and isinstance(messages[-1], dict) else {}
        message_content = str(last_message.get("content", "")).strip() or None
        run_metadata = last_message.get("metadata", {}).get("run", {}) if isinstance(last_message.get("metadata"),
                                                                                     dict) else {}
        status = run_metadata.get("status") if isinstance(run_metadata, dict) else None
        normalized_status = "failed" if status == "failed" else "success"
        error = run_metadata.get("error") if isinstance(run_metadata, dict) else None

        return {
            "status": normalized_status,
            "summary": None if normalized_status == "failed" else ScheduleManager._truncate_summary(message_content),
            "error": str(error).strip() if error else None,
            "run_id": payload.get("run_id"),
            **base_result,
        }

    @staticmethod
    def _build_last_run_result_from_exception(
            exc: Exception,
            *,
            trigger: str,
            started_at: datetime,
            finished_at: datetime,
    ) -> dict[str, object]:
        return {
            "status": "failed",
            "summary": None,
            "error": ScheduleManager._truncate_summary(str(exc), limit=500),
            "run_id": None,
            "trigger": trigger,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "duration_ms": ScheduleManager._duration_ms(started_at, finished_at),
        }

    @staticmethod
    def _duration_ms(started_at: datetime, finished_at: datetime) -> int:
        return max(0, int((finished_at - started_at).total_seconds() * 1000))

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
