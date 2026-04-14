import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from starlette.websockets import WebSocketDisconnect

from app.main import app
import app.main as main_module
from app.models.database import Message, Schedule, Session, Task
from app.models.schemas import AgentRunResult, Usage


def websocket_path(token: str = "test-bearer-token") -> str:
    return f"/ws?access_token={token}"


def send_rpc(websocket, method: str, params: dict | None = None, request_id: int = 1) -> dict:
    websocket.send_text(json.dumps({
        "jsonrpc": "2.0",
        "method": method,
        "params": params or {},
        "id": request_id,
    }))
    return json.loads(websocket.receive_text())


def test_websocket_rejects_invalid_token(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(websocket_path("wrong-token")):
            pass


def test_websocket_ping(client):
    with client.websocket_connect(websocket_path()) as websocket:
        response = send_rpc(websocket, "ping")
        assert response["result"] == "pong"
        assert response["id"] == 1


def test_websocket_invalid_json_does_not_disconnect(client):
    with client.websocket_connect(websocket_path()) as websocket:
        websocket.send_text("{bad-json")
        response = json.loads(websocket.receive_text())
        assert response["error"]["code"] in {-32700, -32600}

        follow_up = send_rpc(websocket, "ping", request_id=2)
        assert follow_up["result"] == "pong"
        assert follow_up["id"] == 2


def test_websocket_dispatch_exception_returns_error_and_keeps_connection(client, monkeypatch):
    original_dispatch = main_module.async_dispatch
    fail_once = {"value": True}

    async def flaky_dispatch(*args, **kwargs):
        if fail_once["value"]:
            fail_once["value"] = False
            raise RuntimeError("dispatch failed")
        return await original_dispatch(*args, **kwargs)

    monkeypatch.setattr(main_module, "async_dispatch", flaky_dispatch)

    with client.websocket_connect(websocket_path()) as websocket:
        first = send_rpc(websocket, "ping", request_id=3)
        assert first["error"] == {"code": -32603, "message": "Internal server error"}
        assert first["id"] == 3

        second = send_rpc(websocket, "ping", request_id=4)
        assert second["result"] == "pong"
        assert second["id"] == 4


def test_websocket_llm_and_model_config_flow(client):
    from app.core.config import Settings

    original_fetcher = Settings._fetch_provider_models

    def fake_fetcher(provider: str, api_key: str, base_url: str, list_mode: str):
        if provider == "openai":
            return ["gpt-4o"]
        if provider == "kimi":
            return ["kimi-k2.5"]
        if provider == "doubao":
            return ["doubao-seed-2-0-pro-260215"]
        if provider == "azure_openai":
            return ["gpt-5.4-mini"]
        if provider == "custom":
            return ["custom-chat-model"]
        return []

    Settings._fetch_provider_models = staticmethod(fake_fetcher)

    with client.websocket_connect(websocket_path()) as websocket:
        try:
            response = send_rpc(
                websocket,
                "set_llm_config",
                {
                    "provider": "openai",
                    "api_key": "sk-test-key",
                    "base_url": "https://test.api",
                },
                request_id=2,
            )
            assert response["result"] == {"status": "success"}

            response = send_rpc(websocket, "get_llm_configs", request_id=3)
            openai_config = next((c for c in response["result"] if c["provider"] == "openai"), None)
            kimi_config = next((c for c in response["result"] if c["provider"] == "kimi"), None)
            doubao_config = next((c for c in response["result"] if c["provider"] == "doubao"), None)
            azure_config = next((c for c in response["result"] if c["provider"] == "azure_openai"), None)
            assert openai_config is not None
            assert kimi_config is not None
            assert doubao_config is not None
            assert azure_config is not None
            assert kimi_config["metadata"]["label"] == "Kimi"
            assert kimi_config["metadata"]["placeholder_base_url"] == "https://api.moonshot.cn/v1"
            assert doubao_config["metadata"]["label"] == "Doubao"
            assert doubao_config["metadata"]["placeholder_base_url"] == "https://ark.cn-beijing.volces.com/api/v3"
            assert azure_config["metadata"]["label"] == "Azure OpenAI"
            assert azure_config["metadata"]["placeholder_base_url"] == "https://your-resource.openai.azure.com/openai/v1"
            assert openai_config["api_key"] == "sk-test-key"
            assert openai_config["base_url"] == "https://test.api"

            response = send_rpc(
                websocket,
                "set_active_model",
                {"model": "openai:gpt-4o"},
                request_id=4,
            )
            assert response["result"] == {"status": "success"}

            response = send_rpc(websocket, "get_active_model", request_id=5)
            assert response["result"] == "openai:gpt-4o"

            response = send_rpc(websocket, "get_available_models", request_id=6)
            assert "openai" in response["result"]
            assert "anthropic" not in response["result"]
            assert "gemini" not in response["result"]
            assert "qwen" not in response["result"]
            assert "kimi" not in response["result"]
            assert "doubao" not in response["result"]
            assert "azure_openai" not in response["result"]

            response = send_rpc(
                websocket,
                "set_llm_config",
                {
                    "provider": "kimi",
                    "api_key": "sk-kimi",
                },
                request_id=7,
            )
            assert response["result"] == {"status": "success"}

            response = send_rpc(websocket, "get_available_models", request_id=8)
            assert response["result"]["kimi"] == ["kimi-k2.5"]

            response = send_rpc(
                websocket,
                "set_llm_config",
                {
                    "provider": "doubao",
                    "api_key": "sk-doubao",
                },
                request_id=9,
            )
            assert response["result"] == {"status": "success"}

            response = send_rpc(websocket, "get_available_models", request_id=10)
            assert response["result"]["doubao"] == ["doubao-seed-2-0-pro-260215"]

            response = send_rpc(
                websocket,
                "set_llm_config",
                {
                    "provider": "azure_openai",
                    "api_key": "sk-azure",
                    "base_url": "https://example.openai.azure.com/openai/v1",
                },
                request_id=101,
            )
            assert response["result"] == {"status": "success"}

            response = send_rpc(websocket, "get_available_models", request_id=102)
            assert response["result"]["azure_openai"] == ["gpt-5.4-mini"]

            response = send_rpc(
                websocket,
                "set_llm_config",
                {
                    "provider": "custom",
                    "api_key": "custom-key",
                    "base_url": "https://custom.example.com/v1",
                    "model": "custom-chat-model",
                },
                request_id=11,
            )
            assert response["result"] == {"status": "success"}

            response = send_rpc(websocket, "get_llm_configs", request_id=12)
            custom_config = next((c for c in response["result"] if c["provider"] == "custom"), None)
            assert custom_config is not None
            assert custom_config["model"] == "custom-chat-model"

            response = send_rpc(websocket, "get_available_models", request_id=13)
            assert response["result"]["custom"] == ["custom-chat-model"]
        finally:
            Settings._fetch_provider_models = original_fetcher


def test_websocket_list_skills(client, monkeypatch):
    app.state.kernel.skills = {
        "b-skill": SimpleNamespace(
            name="b-skill",
            description="Second skill",
            version="1.1.0",
            author="Ferryman",
            updated="2026-04-14",
        ),
        "a-skill": SimpleNamespace(
            name="a-skill",
            description="First skill",
            version="1.0.0",
            author="Tester",
            created="2026-04-10",
            updated="2026-04-11",
        ),
        "legacy-skill": SimpleNamespace(
            name="legacy-skill",
            description="Older skill metadata without timestamps",
            version="0.9.0",
            author="Legacy",
        ),
    }

    with client.websocket_connect(websocket_path()) as websocket:
        response = send_rpc(websocket, "list_skills", request_id=7)
        assert response["result"] == [
            {
                "name": "b-skill",
                "description": "Second skill",
                "version": "1.1.0",
                "author": "Ferryman",
                "created": None,
                "updated": "2026-04-14",
            },
            {
                "name": "a-skill",
                "description": "First skill",
                "version": "1.0.0",
                "author": "Tester",
                "created": "2026-04-10",
                "updated": "2026-04-11",
            },
            {
                "name": "legacy-skill",
                "description": "Older skill metadata without timestamps",
                "version": "0.9.0",
                "author": "Legacy",
                "created": None,
                "updated": None,
            },
        ]


def test_websocket_backend_log_endpoints(client, monkeypatch):
    fake_paths = {
        "app": "/tmp/ferryman.log",
        "sidecar": "/tmp/ferryman-sidecar.log",
    }

    monkeypatch.setattr("app.main.get_backend_log_paths", lambda: fake_paths)
    monkeypatch.setattr("app.main.tail_lines", lambda path, lines: f"{path.name}:{lines}")

    with client.websocket_connect(websocket_path()) as websocket:
        response = send_rpc(websocket, "get_backend_log_info", request_id=8)
        assert response["result"] == {
            "paths": fake_paths,
            "active_log": fake_paths["app"],
        }

        response = send_rpc(
            websocket,
            "read_backend_logs",
            {"source": "sidecar", "lines": 10},
            request_id=9,
        )
        assert response["result"] == {
            "source": "sidecar",
            "path": fake_paths["sidecar"],
            "content": "ferryman-sidecar.log:20",
        }


def test_websocket_execute_serializes_agent_result(client, monkeypatch):
    async def fake_run_master_agent(instruction: str, session_id: str, emit_event_cb=None):
        return {
            "namespace": "agent",
            "event": "chat_final",
            "session_id": session_id,
            "ts": "2026-04-09T00:00:00Z",
            "payload": {
                "run_id": "run-10",
                "messages": [{"role": "assistant", "content": "处理完成"}],
                "usage": {"input_tokens": 12, "output_tokens": 34, "total_tokens": 46}
            }
        }

    monkeypatch.setattr(app.state.kernel, "run_master_agent", fake_run_master_agent)

    with client.websocket_connect(websocket_path()) as websocket:
        response = send_rpc(
            websocket,
            "execute",
            {"instruction": "测试执行", "session_id": "session-1"},
            request_id=10,
        )
        assert response["result"] == {
            "namespace": "agent",
            "event": "chat_final",
            "session_id": "session-1",
            "ts": "2026-04-09T00:00:00Z",
            "payload": {
                "run_id": "run-10",
                "messages": [{"role": "assistant", "content": "处理完成"}],
                "usage": {"input_tokens": 12, "output_tokens": 34, "total_tokens": 46}
            }
        }


def test_websocket_create_session_without_title_defaults_to_empty_string(client, session):
    with client.websocket_connect(websocket_path()) as websocket:
        response = send_rpc(
            websocket,
            "create_session",
            {"session_id": "session-untitled"},
            request_id=10,
        )
        assert response["result"] == {"id": "session-untitled", "title": ""}

    created = session.get(Session, "session-untitled")
    assert created is not None
    assert created.title == ""


def test_websocket_session_message_and_task_flows(client, session):
    now = datetime.now(timezone.utc)
    older_session = Session(
        id="session-old",
        title="Older Session",
        updated_at=now - timedelta(hours=1),
    )
    active_session = Session(
        id="session-1",
        title="Session One",
        input_tokens=11,
        output_tokens=7,
        updated_at=now,
    )
    message_1 = Message(
        session_id="session-1",
        role="user",
        content="你好",
        type="text",
        created_at=now - timedelta(minutes=2),
        metadata_={},
    )
    message_2 = Message(
        session_id="session-1",
        role="assistant",
        content="世界",
        type="text",
        created_at=now - timedelta(minutes=1),
        metadata_={"usage": {"input_tokens": 3, "output_tokens": 4}},
    )
    task_1 = Task(
        session_id="session-1",
        title="Task One",
        status="running",
        metadata_={"progress_note": "step 1"},
        updated_at=now,
    )
    task_2 = Task(
        session_id="session-old",
        title="Task Two",
        status="success",
        metadata_={"progress_note": "done"},
        updated_at=now - timedelta(minutes=5),
    )
    schedule = Schedule(
        id="schedule-1",
        name="Nightly",
        cron_expression="0 0 * * *",
        enabled=True,
    )
    session.add(older_session)
    session.add(active_session)
    session.add(message_1)
    session.add(message_2)
    session.add(task_1)
    session.add(task_2)
    session.add(schedule)
    session.commit()

    with client.websocket_connect(websocket_path()) as websocket:
        response = send_rpc(
            websocket,
            "create_session",
            {"session_id": "session-new", "title": "Brand New"},
            request_id=11,
        )
        assert response["result"] == {"id": "session-new", "title": "Brand New"}

        response = send_rpc(websocket, "list_sessions", {"limit": 10}, request_id=12)
        sessions = response["result"]["sessions"]
        assert [item["id"] for item in sessions][:2] == ["session-new", "session-1"]
        assert response["result"]["next_cursor"] is None

        response = send_rpc(
            websocket,
            "update_session",
            {"session_id": "session-1", "title": "Renamed Session"},
            request_id=13,
        )
        assert response["result"] == {"status": "success"}

        response = send_rpc(
            websocket,
            "list_messages",
            {"session_id": "session-1", "limit": 10},
            request_id=14,
        )
        assert [message["content"] for message in response["result"]["messages"]] == ["你好", "世界"]
        assert response["result"]["next_cursor"] is None

        response = send_rpc(websocket, "list_tasks", {"session_id": "session-1"}, request_id=15)
        assert response["result"] == {
            "tasks": [
                {
                    "id": task_1.id,
                    "session_id": "session-1",
                    "parent_id": None,
                    "title": "Task One",
                    "status": "running",
                    "progress": "step 1",
                    "updated_at": task_1.updated_at.isoformat(),
                }
            ],
            "next_cursor": None,
            "summary": {
                "pending": 0,
                "running": 1,
                "success": 0,
                "failed": 0,
                "canceled": 0,
                "total": 1,
            },
        }

        response = send_rpc(websocket, "get_task", {"task_id": task_1.id}, request_id=151)
        assert response["result"]["task"]["instruction"] == ""

        response = send_rpc(
            websocket,
            "update_task",
            {
                "task_id": task_1.id,
                "title": "Task One Updated",
                "status": "success",
                "progress_note": "done",
                "instruction": "Run the task",
                "payload": {"priority": "high"},
            },
            request_id=152,
        )
        assert response["result"] == {"status": "success"}

        response = send_rpc(websocket, "get_task", {"task_id": task_1.id}, request_id=153)
        assert response["result"]["task"]["title"] == "Task One Updated"
        assert response["result"]["task"]["status"] == "success"
        assert response["result"]["task"]["instruction"] == "Run the task"
        assert response["result"]["task"]["payload"] == {"priority": "high"}

        response = send_rpc(websocket, "list_schedules", request_id=16)
        assert response["result"] == {
            "schedules": [
                {
                    "id": "schedule-1",
                    "name": "Nightly",
                    "cron": "0 0 * * *",
                    "enabled": True,
                    "last_run_at": None,
                    "next_run_at": None,
                    "updated_at": schedule.updated_at.isoformat(),
                }
            ],
            "next_cursor": None,
        }

        response = send_rpc(websocket, "get_schedule", {"schedule_id": "schedule-1"}, request_id=161)
        assert response["result"]["schedule"]["instruction"] == ""

        response = send_rpc(
            websocket,
            "update_schedule",
            {
                "schedule_id": "schedule-1",
                "name": "Nightly Updated",
                "cron": "0 8 * * *",
                "enabled": False,
                "instruction": "Run every morning",
            },
            request_id=162,
        )
        assert response["result"] == {"status": "success"}

        response = send_rpc(websocket, "get_schedule", {"schedule_id": "schedule-1"}, request_id=163)
        assert response["result"]["schedule"]["name"] == "Nightly Updated"
        assert response["result"]["schedule"]["cron"] == "0 8 * * *"
        assert response["result"]["schedule"]["enabled"] is False
        assert response["result"]["schedule"]["instruction"] == "Run every morning"

        response = send_rpc(websocket, "delete_task", {"task_id": task_1.id}, request_id=164)
        assert response["result"] == {"status": "success"}

        response = send_rpc(websocket, "delete_schedule", {"schedule_id": "schedule-1"}, request_id=165)
        assert response["result"] == {"status": "success"}

        response = send_rpc(
            websocket,
            "delete_session",
            {"session_id": "session-1"},
            request_id=17,
        )
        assert response["result"] == {"status": "success"}

        response = send_rpc(
            websocket,
            "delete_session",
            {"session_id": "missing-session"},
            request_id=18,
        )
        assert response["result"] == {"status": "error", "message": "Session not found"}


def test_websocket_list_endpoints_use_cursor_pagination(client, session):
    now = datetime(2026, 4, 13, 12, 0, tzinfo=timezone.utc)

    session.add_all([
        Session(id="session-b", title="Session B", updated_at=now),
        Session(id="session-a", title="Session A", updated_at=now),
        Session(id="session-old", title="Session Old", updated_at=now - timedelta(minutes=1)),
        Message(
            id="message-a",
            session_id="session-b",
            role="user",
            content="first",
            type="text",
            created_at=now - timedelta(minutes=2),
        ),
        Message(
            id="message-b",
            session_id="session-b",
            role="assistant",
            content="second",
            type="text",
            created_at=now,
        ),
        Message(
            id="message-c",
            session_id="session-b",
            role="assistant",
            content="third",
            type="text",
            created_at=now,
        ),
        Task(
            id="task-b",
            session_id="session-b",
            title="Task B",
            status="running",
            updated_at=now,
        ),
        Task(
            id="task-a",
            session_id="session-b",
            title="Task A",
            status="pending",
            updated_at=now,
        ),
        Task(
            id="task-old",
            session_id="session-b",
            title="Task Old",
            status="success",
            updated_at=now - timedelta(minutes=1),
        ),
        Schedule(
            id="schedule-b",
            name="Schedule B",
            cron_expression="0 1 * * *",
            updated_at=now,
        ),
        Schedule(
            id="schedule-a",
            name="Schedule A",
            cron_expression="0 2 * * *",
            updated_at=now,
        ),
        Schedule(
            id="schedule-old",
            name="Schedule Old",
            cron_expression="0 3 * * *",
            updated_at=now - timedelta(minutes=1),
        ),
    ])
    session.commit()

    with client.websocket_connect(websocket_path()) as websocket:
        first_sessions = send_rpc(websocket, "list_sessions", {"limit": 1}, request_id=20)["result"]
        assert [item["id"] for item in first_sessions["sessions"]] == ["session-b"]
        assert first_sessions["next_cursor"] is not None

        second_sessions = send_rpc(
            websocket,
            "list_sessions",
            {"limit": 1, "cursor": first_sessions["next_cursor"]},
            request_id=21,
        )["result"]
        assert [item["id"] for item in second_sessions["sessions"]] == ["session-a"]
        assert second_sessions["next_cursor"] is not None

        first_messages = send_rpc(
            websocket,
            "list_messages",
            {"session_id": "session-b", "limit": 1},
            request_id=22,
        )["result"]
        assert [item["content"] for item in first_messages["messages"]] == ["third"]
        assert first_messages["next_cursor"] is not None

        second_messages = send_rpc(
            websocket,
            "list_messages",
            {"session_id": "session-b", "limit": 1, "cursor": first_messages["next_cursor"]},
            request_id=23,
        )["result"]
        assert [item["content"] for item in second_messages["messages"]] == ["second"]
        assert second_messages["next_cursor"] is not None

        first_tasks = send_rpc(
            websocket,
            "list_tasks",
            {"session_id": "session-b", "limit": 1},
            request_id=24,
        )["result"]
        assert [item["id"] for item in first_tasks["tasks"]] == ["task-b"]
        assert first_tasks["next_cursor"] is not None

        second_tasks = send_rpc(
            websocket,
            "list_tasks",
            {"session_id": "session-b", "limit": 1, "cursor": first_tasks["next_cursor"]},
            request_id=25,
        )["result"]
        assert [item["id"] for item in second_tasks["tasks"]] == ["task-a"]
        assert second_tasks["next_cursor"] is not None

        first_schedules = send_rpc(websocket, "list_schedules", {"limit": 1}, request_id=26)["result"]
        assert [item["id"] for item in first_schedules["schedules"]] == ["schedule-b"]
        assert first_schedules["next_cursor"] is not None

        second_schedules = send_rpc(
            websocket,
            "list_schedules",
            {"limit": 1, "cursor": first_schedules["next_cursor"]},
            request_id=27,
        )["result"]
        assert [item["id"] for item in second_schedules["schedules"]] == ["schedule-a"]
        assert second_schedules["next_cursor"] is not None

        response = send_rpc(
            websocket,
            "update_session",
            {"session_id": "missing-session", "title": "Nope"},
            request_id=19,
        )
        assert response["result"] == {"status": "error", "message": "Session not found"}
