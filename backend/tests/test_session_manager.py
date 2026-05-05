from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlmodel import select

from app.core.session_manager import SessionManager
from app.models.database import Message, Session


def test_session_manager_records_successful_agent_run_atomically(session):
    manager = SessionManager()

    manager.ensure_session("chat-1")
    user_message = manager.append_user_message(
        session_id="chat-1",
        content="Build SEO content matrix.",
        run_id="run-1",
        token_estimate=7,
    )

    assistant_message = manager.record_agent_run_success(
        user_message_id=user_message.id,
        session_id="chat-1",
        run_id="run-1",
        content="Done",
        token_estimate=3,
        parts=[{"type": "text", "content": "Done"}],
        usage={"input_tokens": 11, "output_tokens": 5, "total_tokens": 16},
        model={"name": "test-model", "provider": "test-provider"},
    )

    session.expire_all()
    refreshed_session = session.get(Session, "chat-1")
    refreshed_user_message = session.get(Message, user_message.id)
    refreshed_assistant_message = session.get(Message, assistant_message.id)

    assert refreshed_session is not None
    assert refreshed_session.input_tokens == 11
    assert refreshed_session.output_tokens == 5
    assert refreshed_user_message.metadata_["run"]["status"] == "success"
    assert refreshed_assistant_message.content == "Done"
    assert refreshed_assistant_message.metadata_["usage"]["total_tokens"] == 16
    assert refreshed_assistant_message.metadata_["model"]["name"] == "test-model"


def test_session_manager_records_failed_agent_run(session):
    manager = SessionManager()

    manager.ensure_session("chat-failed")
    user_message = manager.append_user_message(
        session_id="chat-failed",
        content="Run failing workflow.",
        run_id="run-failed",
        token_estimate=4,
    )

    failure_message = manager.record_agent_run_failure(
        user_message_id=user_message.id,
        session_id="chat-failed",
        run_id="run-failed",
        error_message="boom",
    )

    session.expire_all()
    refreshed_user_message = session.get(Message, user_message.id)
    refreshed_failure_message = session.get(Message, failure_message.id)

    assert refreshed_user_message.metadata_["run"]["status"] == "failed"
    assert refreshed_user_message.metadata_["run"]["error"] == "boom"
    assert refreshed_failure_message.content == "Run failed: boom"
    assert refreshed_failure_message.metadata_["run"]["status"] == "failed"


def test_session_manager_load_chat_messages_filters_cutoff(session):
    manager = SessionManager()
    cutoff = datetime(2026, 4, 20, 9, 0, tzinfo=timezone.utc)
    session.add_all([
        Message(
            session_id="chat-history",
            role="user",
            content="before",
            type="text",
            created_at=datetime(2026, 4, 20, 8, 59, tzinfo=timezone.utc),
        ),
        Message(
            session_id="chat-history",
            role="assistant",
            content="after",
            type="text",
            created_at=datetime(2026, 4, 20, 9, 1, tzinfo=timezone.utc),
        ),
        Message(
            session_id="chat-history",
            role="tool",
            content="ignored",
            type="text",
            created_at=datetime(2026, 4, 20, 9, 2, tzinfo=timezone.utc),
        ),
    ])
    session.commit()

    messages = manager.load_chat_messages("chat-history", cutoff_created_at=cutoff)

    assert [message.content for message in messages] == ["after"]


def test_session_manager_update_session_usage(session):
    manager = SessionManager()
    manager.ensure_session("chat-usage")

    manager.update_session_usage("chat-usage", input_tokens=3, output_tokens=4)

    session.expire_all()
    refreshed = session.exec(select(Session).where(Session.id == "chat-usage")).one()
    assert refreshed.input_tokens == 3
    assert refreshed.output_tokens == 4


def test_session_manager_records_memory_compaction_message(session):
    manager = SessionManager()
    from_created_at = datetime(2026, 5, 5, 1, 0, tzinfo=timezone.utc)
    cutoff_created_at = datetime(2026, 5, 5, 2, 0, tzinfo=timezone.utc)

    message = manager.append_memory_compaction_message(
        session_id="chat-memory",
        content="Compacted SEO context.",
        usage={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
        from_created_at=from_created_at,
        cutoff_created_at=cutoff_created_at,
        message_count=4,
        token_estimate=8,
    )

    session.expire_all()
    refreshed = session.get(Message, message.id)
    assert refreshed.role == "memory"
    assert refreshed.type == "compaction"
    assert refreshed.content == "Compacted SEO context."
    assert refreshed.metadata_["usage"]["total_tokens"] == 120
    assert refreshed.metadata_["compaction"] == {
        "from_created_at": "2026-05-05T01:00:00Z",
        "cutoff_created_at": "2026-05-05T02:00:00Z",
        "message_count": 4,
    }


def test_session_manager_get_session_insights_aggregates_message_usage(session):
    manager = SessionManager()
    now = datetime.now(timezone.utc)
    session.add(
        Session(
            id="chat-insights",
            title="SEO content matrix",
            input_tokens=20,
            output_tokens=9,
            memory={
                "schema_version": 1,
                "compaction": {
                    "summary": "SEO content matrix context and decisions.",
                    "cutoff_created_at": "2026-05-05T01:00:00Z",
                    "updated_at": "2026-05-05T01:05:00Z",
                },
            },
        )
    )
    session.add_all([
        Message(
            session_id="chat-insights",
            role="assistant",
            content="Done",
            type="text",
            created_at=now,
            metadata_={"usage": {"input_tokens": 11, "output_tokens": 5, "total_tokens": 16}},
        ),
        Message(
            session_id="chat-insights",
            role="assistant",
            content="Older",
            type="text",
            created_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
            metadata_={"usage": {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3}},
        ),
        Message(
            session_id="chat-insights",
            role="memory",
            type="compaction",
            content="Compacted",
            created_at=now,
            metadata_={"usage": {"input_tokens": 7, "output_tokens": 3, "total_tokens": 10}},
        ),
    ])
    session.commit()

    insights = manager.get_session_insights("chat-insights", range_key="today", timezone_name="UTC")

    assert insights["usage"]["range_totals"] == {
        "input_tokens": 18,
        "output_tokens": 8,
        "total_tokens": 26,
    }
    assert insights["usage"]["archived_totals"] == {
        "input_tokens": 20,
        "output_tokens": 9,
        "total_tokens": 29,
    }
    assert insights["usage"]["unattributed_system_usage"] == {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
    }
    assert insights["memory"]["compaction"]["summary_token_estimate"] > 0


def test_session_manager_get_session_insights_handles_missing_session(session):
    manager = SessionManager()

    insights = manager.get_session_insights("missing", range_key="last_30_days", timezone_name="UTC")

    assert insights["session_id"] == "missing"
    assert insights["range"]["key"] == "last_30_days"
    assert insights["usage"]["range_totals"]["total_tokens"] == 0
    assert insights["memory"] is None


def test_session_manager_get_session_insights_groups_by_local_timezone_day(session):
    manager = SessionManager()
    local_timezone = ZoneInfo("Asia/Shanghai")
    local_datetime = datetime.now(local_timezone).replace(hour=0, minute=30, second=0, microsecond=0)
    local_date = local_datetime.date().isoformat()
    session.add(Session(id="chat-local-day", title="Local day", input_tokens=3, output_tokens=1))
    session.add(
        Message(
            session_id="chat-local-day",
            role="assistant",
            content="Local midnight boundary",
            type="text",
            created_at=local_datetime.astimezone(timezone.utc),
            metadata_={"usage": {"input_tokens": 3, "output_tokens": 1, "total_tokens": 4}},
        )
    )
    session.commit()

    insights = manager.get_session_insights("chat-local-day", range_key="last_90_days", timezone_name="Asia/Shanghai")
    bucket = next(item for item in insights["usage"]["daily"] if item["date"] == local_date)

    assert bucket["input_tokens"] == 3
    assert bucket["output_tokens"] == 1
    assert bucket["total_tokens"] == 4
