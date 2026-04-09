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
    with client.websocket_connect(websocket_path()) as websocket:
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
        assert openai_config is not None
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
        assert "anthropic" in response["result"]
        assert "gemini" in response["result"]


def test_websocket_list_skills(client, monkeypatch):
    app.state.kernel.skills = {
        "b-skill": SimpleNamespace(
            name="b-skill",
            description="Second skill",
            version="1.1.0",
            author="Ferryman",
        ),
        "a-skill": SimpleNamespace(
            name="a-skill",
            description="First skill",
            version="1.0.0",
            author="Tester",
        ),
    }

    with client.websocket_connect(websocket_path()) as websocket:
        response = send_rpc(websocket, "list_skills", request_id=7)
        assert response["result"] == [
            {
                "name": "a-skill",
                "description": "First skill",
                "version": "1.0.0",
                "author": "Tester",
            },
            {
                "name": "b-skill",
                "description": "Second skill",
                "version": "1.1.0",
                "author": "Ferryman",
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
            "get_messages",
            {"session_id": "session-1", "limit": 10},
            request_id=14,
        )
        assert [message["content"] for message in response["result"]["messages"]] == ["你好", "世界"]
        assert response["result"]["next_cursor"] is None

        response = send_rpc(websocket, "list_tasks", {"session_id": "session-1"}, request_id=15)
        assert response["result"] == [
            {
                "id": task_1.id,
                "title": "Task One",
                "status": "running",
                "progress": "step 1",
                "updated_at": task_1.updated_at.isoformat(),
            }
        ]

        response = send_rpc(websocket, "list_schedules", request_id=16)
        assert response["result"] == [
            {
                "id": "schedule-1",
                "name": "Nightly",
                "cron": "0 0 * * *",
                "enabled": True,
            }
        ]

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

        response = send_rpc(
            websocket,
            "update_session",
            {"session_id": "missing-session", "title": "Nope"},
            request_id=19,
        )
        assert response["result"] == {"status": "error", "message": "Session not found"}
