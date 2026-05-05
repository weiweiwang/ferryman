from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlmodel import select

from app.core.config import get_settings
from app.core.schedule_manager import (
    ScheduleManager,
    build_cron_trigger,
    compute_next_run_at,
    normalize_timezone_name,
)
from app.models.database import Schedule, Session


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs: dict[str, SimpleNamespace] = {}
        self.listeners: list[tuple[object, int]] = []

    def add_job(self, func, *, trigger, args, id, replace_existing, **kwargs):
        if id in self.jobs and not replace_existing:
            raise ValueError(f"Job {id} already exists.")
        if trigger == "date":
            next_run_time = kwargs["run_date"]
        else:
            next_run_time = trigger.get_next_fire_time(previous_fire_time=None, now=datetime.now(timezone.utc))
        job = SimpleNamespace(
            id=id,
            func=func,
            trigger=trigger,
            args=args,
            next_run_time=next_run_time,
            kwargs=kwargs,
        )
        self.jobs[id] = job
        return job

    def get_job(self, job_id: str):
        return self.jobs.get(job_id)

    def remove_job(self, job_id: str):
        if job_id not in self.jobs:
            raise KeyError(job_id)
        self.jobs.pop(job_id)

    def add_listener(self, callback, mask):
        self.listeners.append((callback, mask))


class StubKernel:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []
        self.schedule_manager = None

    async def run_master_agent(self, instruction: str, session_id: str):
        self.calls.append({"instruction": instruction, "session_id": session_id})
        return {
            "namespace": "agent",
            "event": "chat_final",
            "session_id": session_id,
            "payload": {
                "run_id": "run-123",
                "messages": [
                    {
                        "role": "assistant",
                        "content": f"Completed: {instruction}",
                    }
                ],
            },
        }


class FailingKernel(StubKernel):
    async def run_master_agent(self, instruction: str, session_id: str):
        self.calls.append({"instruction": instruction, "session_id": session_id})
        raise RuntimeError("scheduler failure")


@pytest.mark.asyncio
async def test_scheduler_sync_schedule_sets_timezone_and_next_run(session):
    schedule = Schedule(
        id="schedule-1",
        name="Morning sync",
        cron_expression="0 8 * * *",
        timezone="Asia/Shanghai",
        enabled=True,
        args={"instruction": "Run the morning sync."},
    )
    session.add(schedule)
    session.commit()

    scheduler = ScheduleManager(StubKernel(), get_settings())
    scheduler._scheduler = FakeScheduler()

    await scheduler.sync_schedule(schedule.id)

    session.expire_all()
    refreshed = session.exec(select(Schedule).where(Schedule.id == schedule.id)).one()
    assert refreshed.timezone == "Asia/Shanghai"
    assert refreshed.next_run_at is not None
    assert scheduler._scheduler.get_job(schedule.id) is not None


def test_schedule_datetime_columns_are_persisted_as_explicit_utc_strings(session):
    schedule = Schedule(
        id="schedule-utc-storage",
        name="UTC storage",
        cron_expression="14 10 * * *",
        timezone="Asia/Shanghai",
        enabled=True,
        args={"instruction": "Persist as explicit UTC."},
        next_run_at=datetime(2026, 4, 19, 2, 14, tzinfo=timezone.utc),
    )
    session.add(schedule)
    session.commit()

    row = session.execute(
        text("SELECT next_run_at, created_at, updated_at FROM schedules WHERE id = :schedule_id"),
        {"schedule_id": schedule.id},
    ).one()

    assert row[0] == "2026-04-19T02:14:00Z"
    assert row[1].endswith("Z")
    assert row[2].endswith("Z")


def test_schedule_cron_helpers_validate_inputs_and_compute_utc_next_run():
    assert normalize_timezone_name(" Asia/Shanghai ") == "Asia/Shanghai"

    next_run_at = compute_next_run_at(
        "0 8 * * *",
        "Asia/Shanghai",
        now=datetime(2026, 4, 18, 23, 59),
    )
    assert next_run_at == datetime(2026, 4, 19, 0, 0, tzinfo=timezone.utc)

    trigger = build_cron_trigger("0 8 * * *", "Asia/Shanghai")
    assert trigger.get_next_fire_time(
        previous_fire_time=None,
        now=datetime(2026, 4, 18, 23, 59, tzinfo=timezone.utc),
    ) == datetime(2026, 4, 19, 8, 0, tzinfo=trigger.timezone)


@pytest.mark.parametrize(
    ("cron_expression", "timezone_name", "expected_message"),
    [
        ("   ", "UTC", "cron_expression must not be empty."),
        ("not-a-cron", "UTC", "Invalid cron expression:"),
        ("0 8 * * *", "Mars/Base", "Invalid timezone: Mars/Base"),
    ],
)
def test_schedule_cron_helpers_reject_invalid_inputs(
        cron_expression,
        timezone_name,
        expected_message,
):
    with pytest.raises(ValueError, match=expected_message):
        build_cron_trigger(cron_expression, timezone_name)


@pytest.mark.asyncio
async def test_scheduler_run_uses_schedule_id_as_session_and_updates_metrics(session):
    schedule = Schedule(
        id="schedule-2",
        name="Nightly digest",
        cron_expression="0 1 * * *",
        timezone="UTC",
        enabled=True,
        args={"instruction": "Prepare the nightly digest."},
    )
    session.add(schedule)
    session.commit()

    kernel = StubKernel()
    scheduler = ScheduleManager(kernel, get_settings())
    scheduler._scheduler = FakeScheduler()
    await scheduler.sync_schedule(schedule.id)

    await scheduler._run_schedule(schedule.id)

    session.expire_all()
    refreshed = session.exec(select(Schedule).where(Schedule.id == schedule.id)).one()
    persisted_session = session.get(Session, schedule.id)

    assert kernel.calls == [{
        "instruction": "Prepare the nightly digest.",
        "session_id": schedule.id,
    }]
    assert refreshed.last_run_at is not None
    assert refreshed.total_run_count == 1
    assert refreshed.next_run_at is not None
    assert refreshed.last_run_result == {
        "status": "success",
        "summary": "Completed: Prepare the nightly digest.",
        "error": None,
        "run_id": "run-123",
        "trigger": "scheduled",
        "started_at": refreshed.last_run_result["started_at"],
        "finished_at": refreshed.last_run_result["finished_at"],
        "duration_ms": refreshed.last_run_result["duration_ms"],
    }
    assert refreshed.last_run_result["duration_ms"] >= 0
    assert persisted_session is not None
    assert persisted_session.title == "Nightly digest"
    assert persisted_session.metadata_ == {"kind": "schedule", "schedule_id": schedule.id}


@pytest.mark.asyncio
async def test_scheduler_run_updates_metrics_even_when_agent_execution_fails(session):
    schedule = Schedule(
        id="schedule-3",
        name="Failing digest",
        cron_expression="0 1 * * *",
        timezone="UTC",
        enabled=True,
        args={"instruction": "Prepare the failing digest."},
    )
    session.add(schedule)
    session.commit()

    kernel = FailingKernel()
    scheduler = ScheduleManager(kernel, get_settings())
    scheduler._scheduler = FakeScheduler()
    await scheduler.sync_schedule(schedule.id)

    await scheduler._run_schedule(schedule.id)

    session.expire_all()
    refreshed = session.exec(select(Schedule).where(Schedule.id == schedule.id)).one()

    assert kernel.calls == [{
        "instruction": "Prepare the failing digest.",
        "session_id": schedule.id,
    }]
    assert refreshed.last_run_at is not None
    assert refreshed.total_run_count == 1
    assert refreshed.next_run_at is not None
    assert refreshed.last_run_result == {
        "status": "failed",
        "summary": None,
        "error": "scheduler failure",
        "run_id": None,
        "trigger": "scheduled",
        "started_at": refreshed.last_run_result["started_at"],
        "finished_at": refreshed.last_run_result["finished_at"],
        "duration_ms": refreshed.last_run_result["duration_ms"],
    }
    assert refreshed.last_run_result["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_scheduler_run_disables_schedule_when_instruction_is_missing(session):
    schedule = Schedule(
        id="schedule-missing-instruction",
        name="Missing instruction",
        cron_expression="0 1 * * *",
        timezone="UTC",
        enabled=True,
        args={},
    )
    session.add(schedule)
    session.commit()

    kernel = StubKernel()
    scheduler = ScheduleManager(kernel, get_settings())
    scheduler._scheduler = FakeScheduler()
    await scheduler.sync_schedule(schedule.id)

    await scheduler._run_schedule(schedule.id)

    session.expire_all()
    refreshed = session.exec(select(Schedule).where(Schedule.id == schedule.id)).one()

    assert kernel.calls == []
    assert refreshed.enabled is False
    assert refreshed.next_run_at is None
    assert refreshed.last_run_result is not None
    assert refreshed.last_run_result["status"] == "failed"
    assert refreshed.last_run_result["summary"] == "Schedule disabled because its configuration is invalid."
    assert refreshed.last_run_result["error"] == "instruction must not be empty."
    assert scheduler._scheduler.get_job(schedule.id) is None


@pytest.mark.asyncio
async def test_scheduler_sync_all_disables_invalid_persisted_schedule(session):
    valid_schedule = Schedule(
        id="schedule-valid",
        name="Valid schedule",
        cron_expression="0 8 * * *",
        timezone="UTC",
        enabled=True,
        args={"instruction": "Run the valid schedule."},
    )
    invalid_schedule = Schedule(
        id="schedule-invalid",
        name="Invalid schedule",
        cron_expression="not-a-cron",
        timezone="Mars/Base",
        enabled=True,
        args={"instruction": "Run the invalid schedule."},
    )
    session.add(valid_schedule)
    session.add(invalid_schedule)
    session.commit()

    scheduler = ScheduleManager(StubKernel(), get_settings())
    scheduler._scheduler = FakeScheduler()

    await scheduler.sync_all()

    session.expire_all()
    refreshed_valid = session.exec(select(Schedule).where(Schedule.id == valid_schedule.id)).one()
    refreshed_invalid = session.exec(select(Schedule).where(Schedule.id == invalid_schedule.id)).one()

    assert refreshed_valid.enabled is True
    assert refreshed_valid.next_run_at is not None
    assert scheduler._scheduler.get_job(valid_schedule.id) is not None

    assert refreshed_invalid.enabled is False
    assert refreshed_invalid.next_run_at is None
    assert refreshed_invalid.last_run_result is not None
    assert refreshed_invalid.last_run_result["status"] == "failed"
    assert refreshed_invalid.last_run_result["summary"] == "Schedule disabled because its configuration is invalid."
    assert refreshed_invalid.last_run_result["error"]
    assert scheduler._scheduler.get_job(invalid_schedule.id) is None


@pytest.mark.asyncio
async def test_scheduler_sync_schedule_adds_catchup_job_for_recent_missed_run(session):
    missed_run_at = datetime.now(timezone.utc) - timedelta(hours=2)
    schedule = Schedule(
        id="schedule-catchup",
        name="Catch up",
        cron_expression="0 8 * * *",
        timezone="UTC",
        enabled=True,
        args={"instruction": "Run catch-up."},
        next_run_at=missed_run_at,
    )
    session.add(schedule)
    session.commit()

    settings = SimpleNamespace(
        get=lambda key, default=None: 0 if key == "system.schedule.catchup_skip_if_next_within" else default
    )
    scheduler = ScheduleManager(StubKernel(), settings)
    scheduler._scheduler = FakeScheduler()

    await scheduler.sync_schedule(schedule.id)

    regular_job = scheduler._scheduler.get_job(schedule.id)
    catchup_job = scheduler._scheduler.get_job(f"{schedule.id}:catchup")
    assert regular_job is not None
    assert catchup_job is not None
    assert regular_job.args == [schedule.id, "scheduled"]
    assert catchup_job.args == [schedule.id, "catch_up"]
    assert catchup_job.trigger == "date"


@pytest.mark.asyncio
async def test_scheduler_sync_schedule_skips_catchup_outside_grace_time(session):
    schedule = Schedule(
        id="schedule-stale-missed-run",
        name="Stale missed run",
        cron_expression="0 8 * * *",
        timezone="UTC",
        enabled=True,
        args={"instruction": "Run only if recent."},
        next_run_at=datetime.now(timezone.utc) - timedelta(hours=5),
    )
    session.add(schedule)
    session.commit()

    scheduler = ScheduleManager(StubKernel(), get_settings())
    scheduler._scheduler = FakeScheduler()

    await scheduler.sync_schedule(schedule.id)

    assert scheduler._scheduler.get_job(schedule.id) is not None
    assert scheduler._scheduler.get_job(f"{schedule.id}:catchup") is None


@pytest.mark.asyncio
async def test_scheduler_sync_schedule_skips_catchup_when_next_regular_run_is_close(session):
    schedule = Schedule(
        id="schedule-next-run-close",
        name="Next run close",
        cron_expression="* * * * *",
        timezone="UTC",
        enabled=True,
        args={"instruction": "Run frequently."},
        next_run_at=datetime.now(timezone.utc) - timedelta(minutes=10),
    )
    session.add(schedule)
    session.commit()

    scheduler = ScheduleManager(StubKernel(), get_settings())
    scheduler._scheduler = FakeScheduler()

    await scheduler.sync_schedule(schedule.id)

    assert scheduler._scheduler.get_job(schedule.id) is not None
    assert scheduler._scheduler.get_job(f"{schedule.id}:catchup") is None


@pytest.mark.asyncio
async def test_scheduler_sync_schedule_replaces_only_existing_catchup_job(session):
    schedule = Schedule(
        id="schedule-catchup-replace",
        name="Catch up replace",
        cron_expression="0 8 * * *",
        timezone="UTC",
        enabled=True,
        args={"instruction": "Run one catch-up."},
        next_run_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    session.add(schedule)
    session.commit()

    fake_scheduler = FakeScheduler()
    settings = SimpleNamespace(
        get=lambda key, default=None: 0 if key == "system.schedule.catchup_skip_if_next_within" else default
    )
    scheduler = ScheduleManager(StubKernel(), settings)
    scheduler._scheduler = fake_scheduler

    await scheduler.sync_schedule(schedule.id)
    first_regular_job = fake_scheduler.get_job(schedule.id)
    first_catchup_job = fake_scheduler.get_job(f"{schedule.id}:catchup")
    await scheduler.sync_schedule(schedule.id)

    assert fake_scheduler.get_job(schedule.id) is not None
    assert fake_scheduler.get_job(f"{schedule.id}:catchup") is not None
    assert fake_scheduler.get_job(schedule.id) is not first_catchup_job
    assert fake_scheduler.get_job(f"{schedule.id}:catchup") is not first_regular_job


def test_scheduler_missed_event_adds_catchup_job_and_refreshes_next_run(session):
    now = datetime.now(timezone.utc)
    schedule = Schedule(
        id="schedule-missed-event",
        name="Missed event",
        cron_expression="0 8 * * *",
        timezone="UTC",
        enabled=True,
        args={"instruction": "Run from missed event."},
        next_run_at=now - timedelta(minutes=20),
    )
    session.add(schedule)
    session.commit()

    fake_scheduler = FakeScheduler()
    scheduler = ScheduleManager(StubKernel(), get_settings())
    scheduler._scheduler = fake_scheduler
    next_regular_run_at = now + timedelta(hours=2)
    fake_scheduler.jobs[schedule.id] = SimpleNamespace(
        id=schedule.id,
        next_run_time=next_regular_run_at,
    )

    scheduler._handle_job_missed_inner(
        SimpleNamespace(
            job_id=schedule.id,
            scheduled_run_time=now - timedelta(minutes=20),
        )
    )

    session.expire_all()
    refreshed = session.exec(select(Schedule).where(Schedule.id == schedule.id)).one()
    catchup_job = fake_scheduler.get_job(f"{schedule.id}:catchup")

    assert refreshed.next_run_at == next_regular_run_at
    assert catchup_job is not None
    assert catchup_job.args == [schedule.id, "catch_up"]
    assert catchup_job.trigger == "date"


def test_scheduler_missed_event_ignores_catchup_jobs(session):
    now = datetime.now(timezone.utc)
    schedule = Schedule(
        id="schedule-catchup-missed-event",
        name="Catch-up missed event",
        cron_expression="0 8 * * *",
        timezone="UTC",
        enabled=True,
        args={"instruction": "Do not recurse."},
        next_run_at=now - timedelta(minutes=20),
    )
    session.add(schedule)
    session.commit()

    fake_scheduler = FakeScheduler()
    scheduler = ScheduleManager(StubKernel(), get_settings())
    scheduler._scheduler = fake_scheduler

    scheduler._handle_job_missed_inner(
        SimpleNamespace(
            job_id=f"{schedule.id}:catchup",
            scheduled_run_time=now - timedelta(minutes=20),
        )
    )

    assert fake_scheduler.get_job(f"{schedule.id}:catchup") is None


@pytest.mark.asyncio
async def test_scheduler_run_records_catchup_trigger_and_duration(session):
    schedule = Schedule(
        id="schedule-catchup-result",
        name="Catch-up result",
        cron_expression="0 1 * * *",
        timezone="UTC",
        enabled=True,
        args={"instruction": "Prepare the catch-up result."},
    )
    session.add(schedule)
    session.commit()

    kernel = StubKernel()
    scheduler = ScheduleManager(kernel, get_settings())
    scheduler._scheduler = FakeScheduler()
    await scheduler.sync_schedule(schedule.id)

    await scheduler._run_schedule(schedule.id, "catch_up")

    session.expire_all()
    refreshed = session.exec(select(Schedule).where(Schedule.id == schedule.id)).one()

    assert refreshed.last_run_result is not None
    assert refreshed.last_run_result["trigger"] == "catch_up"
    assert refreshed.last_run_result["started_at"]
    assert refreshed.last_run_result["finished_at"]
    assert refreshed.last_run_result["duration_ms"] >= 0
