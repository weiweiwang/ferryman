from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlmodel import select

from app.core.config import get_settings
from app.core.scheduler import FerrymanScheduler
from app.models.database import Schedule, Session


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs: dict[str, SimpleNamespace] = {}

    def add_job(self, func, *, trigger, args, id, replace_existing):
        next_run_time = trigger.get_next_fire_time(previous_fire_time=None, now=datetime.now(timezone.utc))
        job = SimpleNamespace(id=id, func=func, args=args, next_run_time=next_run_time)
        self.jobs[id] = job
        return job

    def get_job(self, job_id: str):
        return self.jobs.get(job_id)

    def remove_job(self, job_id: str):
        if job_id not in self.jobs:
            raise KeyError(job_id)
        self.jobs.pop(job_id)


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

    scheduler = FerrymanScheduler(StubKernel(), get_settings())
    scheduler._scheduler = FakeScheduler()

    await scheduler.sync_schedule(schedule.id)

    session.expire_all()
    refreshed = session.exec(select(Schedule).where(Schedule.id == schedule.id)).one()
    assert refreshed.timezone == "Asia/Shanghai"
    assert refreshed.next_run_at is not None
    assert scheduler._scheduler.get_job(schedule.id) is not None


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
    scheduler = FerrymanScheduler(kernel, get_settings())
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
        "finished_at": refreshed.last_run_result["finished_at"],
    }
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
    scheduler = FerrymanScheduler(kernel, get_settings())
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
        "finished_at": refreshed.last_run_result["finished_at"],
    }


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
    scheduler = FerrymanScheduler(kernel, get_settings())
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

    scheduler = FerrymanScheduler(StubKernel(), get_settings())
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
