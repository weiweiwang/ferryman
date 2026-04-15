from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic_ai.exceptions import ModelRetry
from sqlmodel import select

from app.core.toolkits.task import TaskToolkit
from app.models.database import Schedule, Task


def make_ctx(*, kernel=None, session_id: str = "session-1"):
    return SimpleNamespace(deps=SimpleNamespace(kernel=kernel, session_id=session_id))


class StubKernel:
    def __init__(self) -> None:
        self.persist_task_calls: list[dict] = []
        self.persist_task_update_calls: list[dict] = []

    def persist_task(self, *, session_id: str, title: str, parent_id: str | None, args: dict):
        self.persist_task_calls.append({
            "session_id": session_id,
            "title": title,
            "parent_id": parent_id,
            "args": args,
        })
        return SimpleNamespace(id="task-123", title=title)

    def persist_task_update(self, task_id: str, *, status: str, metadata: dict | None = None) -> None:
        self.persist_task_update_calls.append({
            "task_id": task_id,
            "status": status,
            "metadata": metadata,
        })


@pytest.mark.asyncio
async def test_create_task_packages_instruction_metadata_and_parent_id():
    kernel = StubKernel()
    ctx = make_ctx(kernel=kernel, session_id="session-alpha")

    result = await TaskToolkit.create_task(
        ctx,
        title="  Monitor SKU-123  ",
        instruction="  Check site X every hour and report when price drops.  ",
        metadata={"sku": "123", "site": "X"},
        parent_id="parent-1",
    )

    assert result == "Task created/verified: ID=task-123, Title='Monitor SKU-123'"
    assert kernel.persist_task_calls == [{
        "session_id": "session-alpha",
        "title": "Monitor SKU-123",
        "parent_id": "parent-1",
        "args": {
            "instruction": "Check site X every hour and report when price drops.",
            "payload": {"sku": "123", "site": "X"},
        },
    }]


@pytest.mark.asyncio
async def test_create_task_defaults_metadata_to_empty_payload():
    kernel = StubKernel()
    ctx = make_ctx(kernel=kernel)

    await TaskToolkit.create_task(
        ctx,
        title="Collect competitor pricing",
        instruction="Capture the current price sheet and summarize major deltas.",
    )

    assert kernel.persist_task_calls[0]["args"]["payload"] == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("title", "instruction", "expected_message"),
    [
        ("   ", "valid instruction", "title must not be empty."),
        ("Valid title", "   ", "instruction must not be empty."),
    ],
)
async def test_create_task_rejects_blank_required_fields(title, instruction, expected_message):
    kernel = StubKernel()
    ctx = make_ctx(kernel=kernel)

    with pytest.raises(ModelRetry, match=expected_message):
        await TaskToolkit.create_task(ctx, title=title, instruction=instruction)


@pytest.mark.asyncio
async def test_update_task_forwards_status_and_allows_clearing_progress_note():
    kernel = StubKernel()
    ctx = make_ctx(kernel=kernel)

    result = await TaskToolkit.update_task(ctx, task_id="task-77", status="RUNNING", progress_note="")

    assert result == "Task task-77 updated to running"
    assert kernel.persist_task_update_calls == [{
        "task_id": "task-77",
        "status": "running",
        "metadata": {"progress_note": ""},
    }]


@pytest.mark.asyncio
async def test_update_task_rejects_invalid_status():
    kernel = StubKernel()
    ctx = make_ctx(kernel=kernel)

    with pytest.raises(ModelRetry, match="status must be one of:"):
        await TaskToolkit.update_task(ctx, task_id="task-77", status="queued")


@pytest.mark.asyncio
async def test_list_tasks_returns_helpful_empty_messages():
    ctx = make_ctx()

    assert await TaskToolkit.list_tasks(ctx) == "No tasks found."
    assert (
        await TaskToolkit.list_tasks(ctx, status="pending", query="example.com")
        == "No tasks found with status 'pending' matching 'example.com'."
    )


@pytest.mark.asyncio
async def test_list_tasks_filters_orders_and_formats_results(session):
    now = datetime.now(timezone.utc)
    session.add_all([
        Task(
            id="task-old",
            session_id="session-a",
            title="Old task",
            status="running",
            args={"instruction": "This older task should be filtered out by query.", "payload": {}},
            updated_at=now - timedelta(minutes=5),
        ),
        Task(
            id="task-match-new",
            session_id="session-b",
            title="Submit example.com to Product Hunt",
            status="pending",
            args={
                "instruction": "Investigate the submission requirements for example.com and prepare the draft.",
                "payload": {"domain": "example.com", "channel": "product-hunt"},
            },
            updated_at=now,
        ),
        Task(
            id="task-match-old",
            session_id="session-c",
            title="Submit docs.example.com to Directory",
            status="pending",
            args={
                "instruction": "Use the docs site pitch and include the launch summary in the submission.",
                "payload": {"domain": "docs.example.com"},
            },
            updated_at=now - timedelta(minutes=1),
        ),
    ])
    session.commit()

    result = await TaskToolkit.list_tasks(make_ctx(), status="PENDING", query="example.com")

    assert "Found 2 tasks:" in result
    assert result.index("task-match-new") < result.index("task-match-old")
    assert "- ID: task-match-new | [pending] Submit example.com to Product Hunt" in result
    assert "Metadata: {'domain': 'example.com', 'channel': 'product-hunt'}" in result
    assert "task-old" not in result


@pytest.mark.asyncio
async def test_list_tasks_rejects_invalid_status():
    with pytest.raises(ModelRetry, match="status must be one of:"):
        await TaskToolkit.list_tasks(make_ctx(), status="later")


@pytest.mark.asyncio
async def test_create_schedule_persists_instruction_and_leaves_runtime_fields_empty(session):
    result = await TaskToolkit.create_schedule(
        make_ctx(),
        name="  Morning sync  ",
        cron_expression=" 0 8 * * * ",
        instruction="  Run the daily sync workflow and summarize failures. ",
    )

    schedule = session.exec(select(Schedule)).one()

    assert result == f"Schedule 'Morning sync' created with ID: {schedule.id}"
    assert schedule.name == "Morning sync"
    assert schedule.cron_expression == "0 8 * * *"
    assert schedule.timezone == "UTC"
    assert schedule.args == {"instruction": "Run the daily sync workflow and summarize failures."}
    assert schedule.last_run_at is None
    assert schedule.next_run_at is not None
    assert schedule.enabled is True
    assert schedule.total_run_count == 0
    assert schedule.last_run_result is None


@pytest.mark.asyncio
async def test_create_schedule_syncs_schedule_manager_when_available(session):
    sync_schedule = AsyncMock()
    kernel = SimpleNamespace(schedule_manager=SimpleNamespace(sync_schedule=sync_schedule))

    result = await TaskToolkit.create_schedule(
        make_ctx(kernel=kernel),
        name="Hourly check",
        cron_expression="0 * * * *",
        instruction="Run the hourly check.",
    )

    schedule = session.exec(select(Schedule)).one()
    assert result == f"Schedule 'Hourly check' created with ID: {schedule.id}"
    sync_schedule.assert_awaited_once_with(schedule.id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "cron_expression", "instruction", "expected_message"),
    [
        ("", "0 * * * *", "run it", "name must not be empty."),
        ("Hourly", "   ", "run it", "cron_expression must not be empty."),
        ("Hourly", "0 * * * *", "   ", "instruction must not be empty."),
    ],
)
async def test_create_schedule_rejects_blank_required_fields(
    name,
    cron_expression,
    instruction,
    expected_message,
):
    with pytest.raises(ModelRetry, match=expected_message):
        await TaskToolkit.create_schedule(
            make_ctx(),
            name=name,
            cron_expression=cron_expression,
            instruction=instruction,
        )


@pytest.mark.asyncio
async def test_list_schedules_returns_empty_message():
    assert await TaskToolkit.list_schedules(make_ctx()) == "No schedules registered."


@pytest.mark.asyncio
async def test_list_schedules_orders_results_and_displays_enabled_state(session):
    now = datetime.now(timezone.utc)
    session.add_all([
        Schedule(
            id="schedule-old",
            name="Nightly crawl",
            cron_expression="0 2 * * *",
            enabled=False,
            updated_at=now - timedelta(hours=1),
        ),
        Schedule(
            id="schedule-new",
            name="Morning report",
            cron_expression="0 8 * * *",
            enabled=True,
            updated_at=now,
        ),
    ])
    session.commit()

    result = await TaskToolkit.list_schedules(make_ctx())

    assert result.startswith("Registered Automated Routines:")
    assert result.index("schedule-new") < result.index("schedule-old")
    assert "- [Enabled] ID: schedule-new | Name: Morning report | Cron: 0 8 * * *" in result
    assert "- [Disabled] ID: schedule-old | Name: Nightly crawl | Cron: 0 2 * * *" in result
