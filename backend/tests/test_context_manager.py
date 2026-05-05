from datetime import datetime, timezone

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse
from sqlmodel import select

from app.core.config import Settings
from app.core.context_manager import ContextManager
from app.core.runtime import FerrymanRuntime
from app.models.database import Message, Session


def test_context_manager_splits_tail_by_token_budget():
    messages = [
        Message(session_id="s1", role="user", content="a", token_estimate=10),
        Message(session_id="s1", role="assistant", content="b", token_estimate=10),
        Message(session_id="s1", role="user", content="c", token_estimate=10),
        Message(session_id="s1", role="assistant", content="d", token_estimate=10),
    ]

    compactable, tail = ContextManager.split_compaction_tail(messages, tail_tokens=20)

    assert [message.content for message in compactable] == ["a", "b"]
    assert [message.content for message in tail] == ["c", "d"]


def test_context_manager_selects_rolling_chunk():
    messages = [
        Message(session_id="s1", role="user", content="a", token_estimate=10),
        Message(session_id="s1", role="assistant", content="b", token_estimate=10),
        Message(session_id="s1", role="user", content="c", token_estimate=10),
    ]

    chunk = ContextManager.select_compaction_chunk(messages, max_tokens=25)

    assert [message.content for message in chunk] == ["a", "b"]


def test_context_manager_loads_summary_and_tail_messages(session, tmp_path):
    runtime = FerrymanRuntime(Settings(root_dir=tmp_path))
    session_id = "context-session"
    cutoff = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    session.add(
        Session(
            id=session_id,
            memory={
                "schema_version": 1,
                "compaction": {
                    "summary": "Earlier SEO matrix decisions.",
                    "cutoff_created_at": cutoff.isoformat().replace("+00:00", "Z"),
                },
            },
        )
    )
    session.add(
        Message(
            session_id=session_id,
            role="user",
            content="old",
            type="text",
            created_at=datetime(2026, 1, 1, 11, 0, tzinfo=timezone.utc),
        )
    )
    session.add(
        Message(
            session_id=session_id,
            role="user",
            content="new",
            type="text",
            created_at=datetime(2026, 1, 1, 13, 0, tzinfo=timezone.utc),
        )
    )
    session.commit()

    history = runtime.context_manager.get_session_messages(session_id)

    assert isinstance(history[0], ModelRequest)
    assert isinstance(history[1], ModelResponse)
    assert "Earlier SEO matrix decisions." in history[1].parts[0].content
    assert isinstance(history[2], ModelRequest)
    assert history[2].parts[0].content == "new"


def test_context_manager_methods_are_used_directly(tmp_path, monkeypatch):
    runtime = FerrymanRuntime(Settings(root_dir=tmp_path))
    calls = []

    monkeypatch.setattr(runtime.context_manager, "estimate_text_tokens", lambda text: calls.append(text) or 7)
    monkeypatch.setattr(runtime.context_manager, "get_session_messages", lambda session_id: [session_id])

    assert runtime.context_manager.estimate_text_tokens("hello") == 7
    assert runtime.context_manager.get_session_messages("s1") == ["s1"]
    assert calls == ["hello"]


@pytest.mark.asyncio
async def test_context_manager_records_memory_compaction_message(session, tmp_path, monkeypatch):
    runtime = FerrymanRuntime(Settings(root_dir=tmp_path))
    session_id = "compact-session"
    first_created_at = datetime(2026, 5, 5, 1, 0, tzinfo=timezone.utc)
    second_created_at = datetime(2026, 5, 5, 2, 0, tzinfo=timezone.utc)
    session.add(Session(id=session_id))
    session.add_all([
        Message(
            session_id=session_id,
            role="user",
            content="Build SEO matrix.",
            type="text",
            token_estimate=10,
            created_at=first_created_at,
        ),
        Message(
            session_id=session_id,
            role="assistant",
            content="Done.",
            type="text",
            token_estimate=10,
            created_at=second_created_at,
        ),
    ])
    session.commit()

    class FakeUsage:
        input_tokens = 30
        output_tokens = 7
        total_tokens = 37

    class FakeResult:
        output = "Compacted SEO decisions."

        @staticmethod
        def usage():
            return FakeUsage()

    class FakeAgent:
        @staticmethod
        async def run(_prompt):
            return FakeResult()

    monkeypatch.setattr(
        Settings,
        "get",
        lambda _self, key, default=None: {
            "system.llm.compaction_threshold_tokens": 1,
            "system.llm.compaction_chunk_tokens": 100,
            "system.llm.compaction_guard_seconds": 60,
            "system.llm.compaction_tail_tokens": 0,
        }.get(key, default),
    )
    monkeypatch.setattr(runtime.context_manager, "get_compaction_agent", lambda: FakeAgent())

    await runtime.context_manager.maybe_compact_session(session_id)

    session.expire_all()
    refreshed_session = session.get(Session, session_id)
    compaction_message = next(
        message for message in session.exec(select(Message).where(Message.session_id == session_id)).all()
        if message.role == "memory" and message.type == "compaction"
    )
    assert refreshed_session.input_tokens == 30
    assert refreshed_session.output_tokens == 7
    assert refreshed_session.memory["compaction"]["summary"] == "Compacted SEO decisions."
    assert compaction_message.content == "Compacted SEO decisions."
    assert compaction_message.metadata_["usage"]["total_tokens"] == 37
    assert compaction_message.metadata_["compaction"] == {
        "from_created_at": "2026-05-05T01:00:00Z",
        "cutoff_created_at": "2026-05-05T02:00:00Z",
        "message_count": 2,
    }
