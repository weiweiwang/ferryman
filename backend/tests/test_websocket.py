import json
import time
import asyncio
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from starlette.websockets import WebSocketDisconnect
from sqlmodel import select

from app.main import app
from app.core.run_registry import RunAlreadyActiveError
from app.models.database import MessageModel, ScheduleModel, SessionModel, TaskModel
from app.models.schemas import AgentRunResult, Usage
from app.rpc.agent_runs import persist_canceled_chat_run
from app.rpc.sessions import list_messages, reconcile_stale_pending_runs_on_startup
import app.rpc.websocket as websocket_rpc


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


def send_rpc_until_response(websocket, method: str, params: dict | None = None, request_id: int = 1) -> tuple[dict, list[dict]]:
    websocket.send_text(json.dumps({
        "jsonrpc": "2.0",
        "method": method,
        "params": params or {},
        "id": request_id,
    }))
    notifications: list[dict] = []
    while True:
        message = json.loads(websocket.receive_text())
        if message.get("id") == request_id:
            return message, notifications
        notifications.append(message)


def persist_session(db_session, session_id: str, title: str | None = None) -> None:
    db_session.add(SessionModel(id=session_id, title=title or session_id))
    db_session.commit()


def test_websocket_rejects_invalid_token(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(websocket_path("wrong-token")):
            pass


def test_websocket_ping(client):
    with client.websocket_connect(websocket_path()) as websocket:
        response = send_rpc(websocket, "ping")
        assert response["result"] == "pong"
        assert response["id"] == 1


def test_websocket_session_insights_include_workspace(client, session):
    persist_session(session, "session-insights")

    with client.websocket_connect(websocket_path()) as websocket:
        response = send_rpc(
            websocket,
            "get_session_insights",
            {"session_id": "session-insights", "range_key": "last_30_days", "timezone": "UTC"},
        )

    assert response["result"]["session_id"] == "session-insights"
    assert response["result"]["session_workspace"].endswith("/workspaces/session-insights")


def test_websocket_invalid_json_does_not_disconnect(client):
    with client.websocket_connect(websocket_path()) as websocket:
        websocket.send_text("{bad-json")
        response = json.loads(websocket.receive_text())
        assert response["error"]["code"] in {-32700, -32600}

        follow_up = send_rpc(websocket, "ping", request_id=2)
        assert follow_up["result"] == "pong"
        assert follow_up["id"] == 2


def test_websocket_dispatch_exception_returns_error_and_keeps_connection(client, monkeypatch):
    original_dispatch = websocket_rpc.async_dispatch
    fail_once = {"value": True}

    async def flaky_dispatch(*args, **kwargs):
        if fail_once["value"]:
            fail_once["value"] = False
            raise RuntimeError("dispatch failed")
        return await original_dispatch(*args, **kwargs)

    monkeypatch.setattr(websocket_rpc, "async_dispatch", flaky_dispatch)

    with client.websocket_connect(websocket_path()) as websocket:
        first = send_rpc(websocket, "ping", request_id=3)
        assert first["error"] == {"code": -32603, "message": "Internal server error"}
        assert first["id"] == 3

        second = send_rpc(websocket, "ping", request_id=4)
        assert second["result"] == "pong"
        assert second["id"] == 4


def test_websocket_llm_and_model_config_flow(client):
    from app.core.model_manager import ModelManager

    original_fetcher = ModelManager._fetch_provider_models
    original_validator = ModelManager.validate_provider_config

    def fake_fetcher(provider: str, api_key: str, base_url: str, list_mode: str):
        if provider == "openai":
            return ["gpt-4o"]
        if provider == "deepseek":
            return ["deepseek-v4-pro", "deepseek-v4-flash"]
        if provider == "kimi":
            return ["kimi-k2.5"]
        return []

    def fake_validator(self, provider: str, api_key: str, base_url: str = "", model: str = ""):
        if api_key == "bad-key":
            return "Invalid API key."
        return None

    ModelManager._fetch_provider_models = staticmethod(fake_fetcher)
    ModelManager.validate_provider_config = fake_validator

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
            deepseek_config = next((c for c in response["result"] if c["provider"] == "deepseek"), None)
            kimi_config = next((c for c in response["result"] if c["provider"] == "kimi"), None)
            assert openai_config is not None
            assert deepseek_config is not None
            assert kimi_config is not None
            assert deepseek_config["metadata"]["label"] == "DeepSeek"
            assert deepseek_config["metadata"]["placeholder_base_url"] == "https://api.deepseek.com"
            assert kimi_config["metadata"]["label"] == "Kimi"
            assert kimi_config["metadata"]["placeholder_base_url"] == "https://api.moonshot.cn/v1"
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

            response = send_rpc(websocket, "get_model_readiness", request_id=6)
            assert response["result"] == {
                "ready": True,
                "active_model": "openai:gpt-4o",
                "issue": None,
            }

            response = send_rpc(websocket, "get_model_routing", request_id=61)
            assert response["result"]["enabled"] is False
            assert response["result"]["classifier_model"] == "gemini:gemini-3.1-flash-lite-preview"

            response = send_rpc(
                websocket,
                "set_model_routing",
                {"enabled": True},
                request_id=62,
            )
            assert response["result"]["status"] == "success"
            assert response["result"]["config"]["enabled"] is True

            response = send_rpc(websocket, "get_model_routing", request_id=63)
            assert response["result"]["enabled"] is True

            response = send_rpc(websocket, "get_available_models", request_id=7)
            assert "openai" in response["result"]
            assert "anthropic" not in response["result"]
            assert "gemini" not in response["result"]
            assert "qwen" not in response["result"]
            assert "deepseek" not in response["result"]
            assert "kimi" not in response["result"]
            assert "doubao" not in response["result"]

            response = send_rpc(
                websocket,
                "set_llm_config",
                {
                    "provider": "deepseek",
                    "api_key": "sk-deepseek",
                },
                request_id=11,
            )
            assert response["result"] == {"status": "success"}

            response = send_rpc(websocket, "get_available_models", request_id=12)
            assert response["result"]["deepseek"] == ["deepseek-v4-pro", "deepseek-v4-flash"]

            response = send_rpc(
                websocket,
                "set_llm_config",
                {
                    "provider": "kimi",
                    "api_key": "sk-kimi",
                },
                request_id=8,
            )
            assert response["result"] == {"status": "success"}

            response = send_rpc(websocket, "get_available_models", request_id=8)
            assert response["result"]["kimi"] == ["kimi-k2.5"]

            response = send_rpc(
                websocket,
                "set_llm_config",
                {
                    "provider": "openai",
                    "api_key": "bad-key",
                    "base_url": "https://test.api",
                },
                request_id=200,
            )
            assert response["result"] == {"status": "error", "message": "Invalid API key."}

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
            ModelManager._fetch_provider_models = original_fetcher
            ModelManager.validate_provider_config = original_validator


def test_websocket_list_skills(client, monkeypatch):
    app.state.runtime.skill_manager.skills.clear()
    app.state.runtime.skill_manager.skills.update({
        "b-skill": SimpleNamespace(
            name="b-skill",
            description="Second skill",
            version="1.1.0",
            author="Ferryman",
            updated=date(2026, 4, 14),
        ),
        "a-skill": SimpleNamespace(
            name="a-skill",
            description="First skill",
            version="1.0.0",
            author="Tester",
            created=date(2026, 4, 10),
            updated=date(2026, 4, 11),
        ),
        "legacy-skill": SimpleNamespace(
            name="legacy-skill",
            description="Older skill metadata without timestamps",
            version="0.9.0",
            author="Legacy",
        ),
    })

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

    monkeypatch.setattr("app.rpc.logs.get_backend_log_paths", lambda: fake_paths)
    monkeypatch.setattr("app.rpc.logs.tail_lines", lambda path, lines: f"{path.name}:{lines}")

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


def test_websocket_execute_starts_background_run_and_emits_final_event(client, monkeypatch, session):
    persist_session(session, "session-1")

    async def fake_run_master_agent(instruction: str, session_id: str, *, run_id: str, emit_event_cb=None):
        await asyncio.sleep(0)
        return {
            "namespace": "agent",
            "event": "chat_final",
            "session_id": session_id,
            "ts": "2026-04-09T00:00:00Z",
            "payload": {
                "run_id": run_id,
                "messages": [{"role": "assistant", "content": "处理完成"}],
                "usage": {"input_tokens": 12, "output_tokens": 34, "total_tokens": 46}
            }
        }

    monkeypatch.setattr(app.state.runtime, "run_master_agent", fake_run_master_agent)

    with client.websocket_connect(websocket_path()) as websocket:
        response, notifications = send_rpc_until_response(
            websocket,
            "execute",
            {"instruction": "测试执行", "session_id": "session-1"},
            request_id=10,
        )
        assert response["result"]["status"] == "started"
        assert response["result"]["session_id"] == "session-1"
        assert isinstance(response["result"]["run_id"], str)
        assert len(response["result"]["run_id"]) == 22

        event = notifications[0] if notifications else json.loads(websocket.receive_text())
        assert event["method"] == "ferryman_event"
        assert event["params"] == {
            "namespace": "agent",
            "event": "chat_final",
            "session_id": "session-1",
            "ts": "2026-04-09T00:00:00Z",
            "payload": {
                "run_id": response["result"]["run_id"],
                "messages": [{"role": "assistant", "content": "处理完成"}],
                "usage": {"input_tokens": 12, "output_tokens": 34, "total_tokens": 46}
            }
        }


def test_websocket_execute_emits_failed_terminal_event_on_unexpected_background_error(client, monkeypatch, session):
    persist_session(session, "session-background-fail")

    async def fake_run_master_agent(instruction: str, session_id: str, *, run_id: str, emit_event_cb=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(app.state.runtime, "run_master_agent", fake_run_master_agent)

    with client.websocket_connect(websocket_path()) as websocket:
        response, notifications = send_rpc_until_response(
            websocket,
            "execute",
            {"instruction": "会炸掉", "session_id": "session-background-fail"},
            request_id=11,
        )
        run_id = response["result"]["run_id"]
        assert len(run_id) == 22
        assert response["result"] == {
            "status": "started",
            "run_id": run_id,
            "session_id": "session-background-fail",
        }

        event = notifications[0] if notifications else json.loads(websocket.receive_text())
        assert event["method"] == "ferryman_event"
        assert event["params"]["namespace"] == "agent"
        assert event["params"]["event"] == "chat_final"
        assert event["params"]["session_id"] == "session-background-fail"
        assert event["params"]["payload"] == {
            "run_id": run_id,
            "messages": [
                {
                    "role": "assistant",
                    "content": "Run failed: boom",
                    "metadata": {
                        "run": {
                            "id": run_id,
                            "status": "failed",
                            "error": "boom",
                        }
                    },
                }
            ],
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        }

    session.expire_all()
    persisted_messages = session.exec(
        select(MessageModel)
        .where(MessageModel.session_id == "session-background-fail")
        .order_by(MessageModel.created_at)
    ).all()

    assert [message.role for message in persisted_messages] == ["user", "assistant"]
    assert persisted_messages[0].content == "会炸掉"
    assert persisted_messages[0].metadata_["run"] == {
        "id": run_id,
        "status": "failed",
        "error": "boom",
    }
    assert persisted_messages[1].content == "Run failed: boom"


def test_persist_canceled_chat_run_updates_existing_run_metadata_only(session):
    session.add(
        SessionModel(
            id="session-cancel-persist",
            title="Cancel Persist",
            updated_at=datetime(2026, 4, 15, 0, 0, tzinfo=timezone.utc),
        )
    )
    session.add(
        MessageModel(
            session_id="session-cancel-persist",
            role="user",
            content="请停止",
            type="text",
            metadata_={
                "run": {
                    "id": "run-persist-1",
                    "status": "pending",
                }
            },
        )
    )
    session.commit()

    event = persist_canceled_chat_run("session-cancel-persist", "run-persist-1")

    session.expire_all()
    messages = session.exec(
        select(MessageModel)
        .where(MessageModel.session_id == "session-cancel-persist")
        .order_by(MessageModel.created_at)
    ).all()

    assert len(messages) == 1
    assert messages[0].role == "user"
    assert messages[0].metadata_["run"] == {
        "id": "run-persist-1",
        "status": "canceled",
    }
    assert event.model_dump(mode="json")["payload"] == {
        "run_id": "run-persist-1",
        "messages": [
            {
                "role": "assistant",
                "content": "Run canceled.",
                "metadata": {
                    "run": {
                        "id": "run-persist-1",
                        "status": "canceled",
                    }
                },
            }
        ],
        "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
    }


def test_websocket_cancel_run_recovers_persisted_pending_run_after_restart(client, session):
    session.add(SessionModel(id="session-stale-cancel", title="Stale Cancel"))
    session.add(
        MessageModel(
            session_id="session-stale-cancel",
            role="user",
            content="这个run是在sidecar重启前开始的",
            type="text",
            metadata_={
                "run": {
                    "id": "run-stale-1",
                    "status": "pending",
                }
            },
        )
    )
    session.commit()

    with client.websocket_connect(websocket_path()) as websocket:
        cancel_response, cancel_notifications = send_rpc_until_response(
            websocket,
            "cancel_run",
            {"run_id": "run-stale-1", "session_id": "session-stale-cancel"},
            request_id=23,
        )

        assert cancel_response["result"] == {
            "status": "canceled",
            "run_id": "run-stale-1",
            "session_id": "session-stale-cancel",
        }
        assert any(
            event.get("params", {}).get("event") == "chat_final"
            and event["params"]["payload"]["run_id"] == "run-stale-1"
            for event in cancel_notifications
        )

    session.expire_all()
    message = session.exec(
        select(MessageModel).where(
            MessageModel.session_id == "session-stale-cancel",
            MessageModel.role == "user",
        )
    ).one()
    assert message.metadata_["run"] == {
        "id": "run-stale-1",
        "status": "canceled",
    }


def test_startup_reconcile_finalizes_stale_pending_run(session):
    session.add(SessionModel(id="session-stale-pending", title="Stale Pending"))
    session.add(
        MessageModel(
            session_id="session-stale-pending",
            role="user",
            content="这个run在sidecar重启前丢失了",
            type="text",
            metadata_={
                "run": {
                    "id": "run-stale-pending-1",
                    "status": "pending",
                }
            },
        )
    )
    session.commit()

    reconcile_stale_pending_runs_on_startup()

    session.expire_all()
    persisted_messages = session.exec(
        select(MessageModel)
        .where(MessageModel.session_id == "session-stale-pending")
        .order_by(MessageModel.created_at)
    ).all()
    assert [message.metadata_["run"]["status"] for message in persisted_messages] == ["failed", "failed"]
    assert persisted_messages[0].metadata_["run"] == {
        "id": "run-stale-pending-1",
        "status": "failed",
        "error": "Run interrupted before completion.",
    }
    assert persisted_messages[1].content == "Run failed: Run interrupted before completion."


def test_websocket_list_messages_does_not_finalize_stale_pending_run(client, session):
    session.add(SessionModel(id="session-stale-pending-read", title="Stale Pending Read"))
    session.add(
        MessageModel(
            session_id="session-stale-pending-read",
            role="user",
            content="读消息不能修改run状态",
            type="text",
            metadata_={
                "run": {
                    "id": "run-stale-pending-read-1",
                    "status": "pending",
                }
            },
        )
    )
    session.commit()

    with client.websocket_connect(websocket_path()) as websocket:
        response = send_rpc(
            websocket,
            "list_messages",
            {"session_id": "session-stale-pending-read", "limit": 10},
            request_id=24,
        )

    messages = response["result"]["messages"]
    assert [message["role"] for message in messages] == ["user"]
    assert messages[0]["metadata"]["run"] == {
        "id": "run-stale-pending-read-1",
        "status": "pending",
    }

    session.expire_all()
    persisted_messages = session.exec(
        select(MessageModel)
        .where(MessageModel.session_id == "session-stale-pending-read")
        .order_by(MessageModel.created_at)
    ).all()
    assert len(persisted_messages) == 1
    assert persisted_messages[0].metadata_["run"]["status"] == "pending"


def test_websocket_list_messages_keeps_schedule_pending_run(client, session):
    session.add(
        SessionModel(
            id="schedule-active-pending",
            title="Active Schedule",
            metadata_={"kind": "schedule", "schedule_id": "schedule-active-pending"},
        )
    )
    session.add(
        MessageModel(
            session_id="schedule-active-pending",
            role="user",
            content="这个定时任务还在运行",
            type="text",
            metadata_={
                "run": {
                    "id": "run-active-schedule-1",
                    "status": "pending",
                }
            },
        )
    )
    session.commit()

    with client.websocket_connect(websocket_path()) as websocket:
        response = send_rpc(
            websocket,
            "list_messages",
            {"session_id": "schedule-active-pending", "limit": 10},
            request_id=25,
        )

    messages = response["result"]["messages"]
    assert [message["role"] for message in messages] == ["user"]
    assert messages[0]["metadata"]["run"]["status"] == "pending"

    session.expire_all()
    persisted_message = session.exec(
        select(MessageModel).where(MessageModel.session_id == "schedule-active-pending")
    ).one()
    assert persisted_message.metadata_["run"]["status"] == "pending"


def test_websocket_execute_can_be_canceled_while_socket_stays_responsive(client, monkeypatch, session):
    persist_session(session, "session-cancel")
    blocker = asyncio.Event()

    async def fake_run_master_agent(instruction: str, session_id: str, *, run_id: str, emit_event_cb=None):
        await blocker.wait()
        return {
            "namespace": "agent",
            "event": "chat_final",
            "session_id": session_id,
            "ts": "2026-04-09T00:00:00Z",
            "payload": {
                "run_id": "should-not-finish",
                "messages": [{"role": "assistant", "content": "不应到达"}],
                "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
            }
        }

    monkeypatch.setattr(app.state.runtime, "run_master_agent", fake_run_master_agent)

    with client.websocket_connect(websocket_path()) as websocket:
        start_response, start_notifications = send_rpc_until_response(
            websocket,
            "execute",
            {"instruction": "测试取消", "session_id": "session-cancel"},
            request_id=20,
        )
        run_id = start_response["result"]["run_id"]
        assert len(run_id) == 22
        assert start_response["result"] == {
            "status": "started",
            "run_id": run_id,
            "session_id": "session-cancel",
        }

        ping_response = send_rpc(websocket, "ping", request_id=21)
        assert ping_response["result"] == "pong"

        cancel_response, cancel_notifications = send_rpc_until_response(
            websocket,
            "cancel_run",
            {"run_id": run_id, "session_id": "session-cancel"},
            request_id=22,
        )
        assert cancel_response["result"] == {
            "status": "canceling",
            "run_id": run_id,
            "session_id": "session-cancel",
        }

        event = (start_notifications + cancel_notifications)[0] if (start_notifications + cancel_notifications) else json.loads(websocket.receive_text())
        assert event["method"] == "ferryman_event"
        assert event["params"]["namespace"] == "agent"
        assert event["params"]["event"] == "chat_final"
        assert event["params"]["session_id"] == "session-cancel"
        assert event["params"]["payload"] == {
            "run_id": run_id,
            "messages": [
                {
                    "role": "assistant",
                    "content": "Run canceled.",
                    "metadata": {
                        "run": {
                            "id": run_id,
                            "status": "canceled",
                        }
                    },
                }
            ],
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        }


def test_websocket_execute_returns_busy_when_session_already_has_active_run(client, monkeypatch, session):
    persist_session(session, "session-busy")
    blocker = asyncio.Event()

    async def fake_run_master_agent(instruction: str, session_id: str, *, run_id: str, emit_event_cb=None):
        await blocker.wait()
        return {
            "namespace": "agent",
            "event": "chat_final",
            "session_id": session_id,
            "ts": "2026-04-09T00:00:00Z",
            "payload": {
                "run_id": "should-not-complete",
                "messages": [{"role": "assistant", "content": "done"}],
                "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            },
        }

    monkeypatch.setattr(app.state.runtime, "run_master_agent", fake_run_master_agent)

    with client.websocket_connect(websocket_path()) as websocket:
        start_response, _ = send_rpc_until_response(
            websocket,
            "execute",
            {"instruction": "first run", "session_id": "session-busy"},
            request_id=30,
        )
        run_id = start_response["result"]["run_id"]
        assert len(run_id) == 22
        assert start_response["result"] == {
            "status": "started",
            "run_id": run_id,
            "session_id": "session-busy",
        }

        busy_response = send_rpc(
            websocket,
            "execute",
            {"instruction": "second run", "session_id": "session-busy"},
            request_id=31,
        )
        assert busy_response["result"] == {
            "status": "busy",
            "run_id": run_id,
            "session_id": "session-busy",
            "message": "Current session already has an active run.",
        }

        session_response = send_rpc(
            websocket,
            "get_session",
            {"session_id": "session-busy"},
            request_id=35,
        )
        assert session_response["result"]["active_run"]["run_id"] == run_id
        assert session_response["result"]["active_run"]["status"] == "running"
        assert datetime.fromisoformat(session_response["result"]["active_run"]["started_at"]).tzinfo is not None

        cancel_response, _ = send_rpc_until_response(
            websocket,
            "cancel_run",
            {"run_id": run_id, "session_id": "session-busy"},
            request_id=32,
        )
        assert cancel_response["result"] == {
            "status": "canceling",
            "run_id": run_id,
            "session_id": "session-busy",
        }


def test_websocket_execute_returns_busy_when_registry_detects_race(client, monkeypatch, session):
    persist_session(session, "session-busy-race")

    def raise_busy(*args, **kwargs):
        raise RunAlreadyActiveError(session_id="session-busy-race", run_id="run-existing-race")

    monkeypatch.setattr(app.state.runtime.run_registry, "start_run", raise_busy)

    with client.websocket_connect(websocket_path()) as websocket:
        response = send_rpc(
            websocket,
            "execute",
            {"instruction": "second run", "session_id": "session-busy-race"},
            request_id=36,
        )

    assert response["result"] == {
        "status": "busy",
        "run_id": "run-existing-race",
        "session_id": "session-busy-race",
        "message": "Current session already has an active run.",
    }


def test_websocket_execute_requires_existing_session(client):
    with client.websocket_connect(websocket_path()) as websocket:
        missing_param_response = send_rpc(
            websocket,
            "execute",
            {"instruction": "hello"},
            request_id=33,
        )
        assert missing_param_response["result"] == {
            "status": "error",
            "message": "Session is required",
        }

        missing_session_response = send_rpc(
            websocket,
            "execute",
            {"instruction": "hello", "session_id": "missing-session"},
            request_id=34,
        )
        assert missing_session_response["result"] == {
            "status": "error",
            "message": "Session not found",
        }


def test_websocket_create_session_without_title_defaults_to_empty_string(client, session):
    with client.websocket_connect(websocket_path()) as websocket:
        response = send_rpc(
            websocket,
            "create_session",
            {},
            request_id=10,
        )
        created_id = response["result"]["id"]
        assert response["result"] == {"id": created_id, "title": ""}
        assert len(created_id) == 22

    created = session.get(SessionModel, created_id)
    assert created is not None
    assert created.title == ""


def test_websocket_session_message_and_task_flows(client, session):
    now = datetime.now(timezone.utc)
    older_session = SessionModel(
        id="session-old",
        title="Older Session",
        updated_at=now - timedelta(hours=1),
    )
    active_session = SessionModel(
        id="session-1",
        title="Session One",
        input_tokens=11,
        output_tokens=7,
        updated_at=now,
    )
    message_1 = MessageModel(
        session_id="session-1",
        role="user",
        content="你好",
        type="text",
        created_at=now - timedelta(minutes=2),
        metadata_={},
    )
    message_2 = MessageModel(
        session_id="session-1",
        role="assistant",
        content="世界",
        type="text",
        created_at=now - timedelta(minutes=1),
        metadata_={"usage": {"input_tokens": 3, "output_tokens": 4}},
    )
    task_1 = TaskModel(
        session_id="session-1",
        title="Task One",
        status="running",
        metadata_={"progress_note": "step 1"},
        updated_at=now,
    )
    task_2 = TaskModel(
        session_id="session-old",
        title="Task Two",
        status="success",
        metadata_={"progress_note": "done"},
        updated_at=now - timedelta(minutes=5),
    )
    schedule = ScheduleModel(
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
            {"title": "Brand New"},
            request_id=11,
        )
        created_session_id = response["result"]["id"]
        assert response["result"] == {"id": created_session_id, "title": "Brand New"}
        assert len(created_session_id) == 22

        response = send_rpc(websocket, "list_sessions", {"limit": 10}, request_id=12)
        sessions = response["result"]["sessions"]
        assert [item["id"] for item in sessions][:2] == [created_session_id, "session-1"]
        assert sessions[0]["active_run"] is None
        assert sessions[1]["active_run"] is None
        assert response["result"]["next_cursor"] is None

        response = send_rpc(
            websocket,
            "get_session",
            {"session_id": "session-1"},
            request_id=19,
        )
        assert response["result"]["id"] == "session-1"
        assert response["result"]["active_run"] is None

        response = send_rpc(
            websocket,
            "update_session",
            {"session_id": "session-1", "title": "Renamed Session"},
            request_id=13,
        )
        assert response["result"]["id"] == "session-1"
        assert response["result"]["title"] == "Renamed Session"
        assert response["result"]["active_run"] is None
        assert response["result"]["updated_at"].endswith("Z")

        response = send_rpc(
            websocket,
            "list_messages",
            {"session_id": "session-1", "limit": 10},
            request_id=14,
        )
        assert [message["content"] for message in response["result"]["messages"]] == ["你好", "世界"]
        assert response["result"]["next_cursor"] is None

        response = send_rpc(websocket, "list_tasks", {"session_id": "session-1"}, request_id=15)
        task_payload = response["result"]["tasks"][0]
        assert task_payload["id"] == task_1.id
        assert task_payload["session_id"] == "session-1"
        assert task_payload["parent_id"] is None
        assert task_payload["title"] == "Task One"
        assert task_payload["status"] == "running"
        assert task_payload["metadata"] == {"progress_note": "step 1"}
        assert task_payload["args"] == {}
        assert task_payload["updated_at"] == now.isoformat().replace("+00:00", "Z")
        assert response["result"]["next_cursor"] is None
        assert response["result"]["summary"] == {
            "pending": 0,
            "running": 1,
            "success": 0,
            "failed": 0,
            "canceled": 0,
            "total": 1,
        }

        response = send_rpc(websocket, "get_task", {"task_id": task_1.id}, request_id=151)
        assert response["result"]["task"]["args"] == {}

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
        assert response["result"]["task"]["metadata"]["progress_note"] == "done"
        assert response["result"]["task"]["args"]["instruction"] == "Run the task"
        assert response["result"]["task"]["args"]["payload"] == {"priority": "high"}

        response = send_rpc(websocket, "list_schedules", request_id=16)
        schedule_payload = response["result"]["schedules"][0]
        assert schedule_payload["id"] == "schedule-1"
        assert schedule_payload["name"] == "Nightly"
        assert schedule_payload["cron_expression"] == "0 0 * * *"
        assert schedule_payload["args"] == {}
        assert schedule_payload["timezone"] == "UTC"
        assert schedule_payload["enabled"] is True
        assert schedule_payload["last_run_at"] is None
        assert schedule_payload["next_run_at"] is None
        assert schedule_payload["total_run_count"] == 0
        assert schedule_payload["updated_at"].endswith("Z")
        assert response["result"]["next_cursor"] is None

        response = send_rpc(websocket, "get_schedule", {"schedule_id": "schedule-1"}, request_id=161)
        assert response["result"]["schedule"]["args"] == {}
        assert response["result"]["schedule"]["timezone"] == "UTC"
        assert response["result"]["schedule"]["total_run_count"] == 0
        assert response["result"]["schedule"]["last_run_result"] is None

        response = send_rpc(
            websocket,
            "update_schedule",
            {
                "schedule_id": "schedule-1",
                "name": "Nightly Updated",
                "cron_expression": "0 8 * * *",
                "timezone": "Asia/Shanghai",
                "enabled": False,
                "instruction": "Run every morning",
            },
            request_id=162,
        )
        assert response["result"] == {"status": "success"}

        response = send_rpc(websocket, "get_schedule", {"schedule_id": "schedule-1"}, request_id=163)
        assert response["result"]["schedule"]["name"] == "Nightly Updated"
        assert response["result"]["schedule"]["cron_expression"] == "0 8 * * *"
        assert response["result"]["schedule"]["timezone"] == "Asia/Shanghai"
        assert response["result"]["schedule"]["enabled"] is False
        assert response["result"]["schedule"]["args"]["instruction"] == "Run every morning"

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
        SessionModel(id="session-b", title="Session B", updated_at=now),
        SessionModel(id="session-a", title="Session A", updated_at=now),
        SessionModel(id="session-old", title="Session Old", updated_at=now - timedelta(minutes=1)),
        MessageModel(
            id="message-a",
            session_id="session-b",
            role="user",
            content="first",
            type="text",
            created_at=now - timedelta(minutes=2),
        ),
        MessageModel(
            id="message-b",
            session_id="session-b",
            role="assistant",
            content="second",
            type="text",
            created_at=now,
        ),
        MessageModel(
            id="message-c",
            session_id="session-b",
            role="assistant",
            content="third",
            type="text",
            created_at=now,
        ),
        TaskModel(
            id="task-b",
            session_id="session-b",
            title="Task B",
            status="running",
            updated_at=now,
        ),
        TaskModel(
            id="task-a",
            session_id="session-b",
            title="Task A",
            status="pending",
            updated_at=now,
        ),
        TaskModel(
            id="task-old",
            session_id="session-b",
            title="Task Old",
            status="success",
            updated_at=now - timedelta(minutes=1),
        ),
        ScheduleModel(
            id="schedule-b",
            name="Schedule B",
            cron_expression="0 1 * * *",
            created_at=now - timedelta(minutes=1),
            updated_at=now,
        ),
        ScheduleModel(
            id="schedule-a",
            name="Schedule A",
            cron_expression="0 2 * * *",
            created_at=now,
            updated_at=now - timedelta(minutes=1),
        ),
        ScheduleModel(
            id="schedule-old",
            name="Schedule Old",
            cron_expression="0 3 * * *",
            created_at=now - timedelta(minutes=2),
            updated_at=now - timedelta(minutes=2),
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
        assert [item["id"] for item in first_schedules["schedules"]] == ["schedule-a"]
        assert first_schedules["next_cursor"] is not None

        second_schedules = send_rpc(
            websocket,
            "list_schedules",
            {"limit": 1, "cursor": first_schedules["next_cursor"]},
            request_id=27,
        )["result"]
        assert [item["id"] for item in second_schedules["schedules"]] == ["schedule-b"]
        assert second_schedules["next_cursor"] is not None

        response = send_rpc(
            websocket,
            "update_session",
            {"session_id": "missing-session", "title": "Nope"},
            request_id=19,
        )
        assert response["result"] == {"status": "error", "message": "Session not found"}


def test_websocket_list_messages_returns_latest_page_then_older_pages_in_display_order(client, session):
    base_time = datetime(2026, 4, 13, 12, 0, tzinfo=timezone.utc)
    session.add(SessionModel(id="session-message-pages", title="Message Pages", updated_at=base_time))
    session.add_all([
        MessageModel(
            id=f"message-{index:02d}",
            session_id="session-message-pages",
            role="user" if index % 2 else "assistant",
            content=f"message-{index:02d}",
            type="text",
            created_at=base_time + timedelta(minutes=index),
        )
        for index in range(1, 46)
    ])
    session.commit()

    with client.websocket_connect(websocket_path()) as websocket:
        latest_page = send_rpc(
            websocket,
            "list_messages",
            {"session_id": "session-message-pages", "limit": 20},
            request_id=30,
        )["result"]

        assert [item["content"] for item in latest_page["messages"]] == [
            f"message-{index:02d}" for index in range(26, 46)
        ]
        assert latest_page["next_cursor"] is not None

        older_page = send_rpc(
            websocket,
            "list_messages",
            {
                "session_id": "session-message-pages",
                "limit": 20,
                "cursor": latest_page["next_cursor"],
            },
            request_id=31,
        )["result"]

        assert [item["content"] for item in older_page["messages"]] == [
            f"message-{index:02d}" for index in range(6, 26)
        ]
        assert older_page["next_cursor"] is not None

        oldest_page = send_rpc(
            websocket,
            "list_messages",
            {
                "session_id": "session-message-pages",
                "limit": 20,
                "cursor": older_page["next_cursor"],
            },
            request_id=32,
        )["result"]

        assert [item["content"] for item in oldest_page["messages"]] == [
            f"message-{index:02d}" for index in range(1, 6)
        ]
        assert oldest_page["next_cursor"] is None


@pytest.mark.asyncio
async def test_list_messages_python_implementation_pages_in_memory_sqlite(session):
    base_time = datetime(2026, 4, 13, 12, 0, tzinfo=timezone.utc)
    session.add(SessionModel(id="session-message-python-pages", title="Message Python Pages", updated_at=base_time))
    session.add_all([
        MessageModel(
            id=f"message-python-{index:02d}",
            session_id="session-message-python-pages",
            role="user" if index % 2 else "assistant",
            content=f"message-python-{index:02d}",
            type="text",
            created_at=base_time + timedelta(minutes=index),
        )
        for index in range(1, 46)
    ])
    session.commit()

    latest_page_response = await list_messages(
        None,
        session_id="session-message-python-pages",
        limit=20,
    )
    latest_page = latest_page_response._value.result

    assert [item["content"] for item in latest_page["messages"]] == [
        f"message-python-{index:02d}" for index in range(26, 46)
    ]
    assert latest_page["next_cursor"] is not None

    older_page_response = await list_messages(
        None,
        session_id="session-message-python-pages",
        limit=20,
        cursor=latest_page["next_cursor"],
    )
    older_page = older_page_response._value.result

    assert [item["content"] for item in older_page["messages"]] == [
        f"message-python-{index:02d}" for index in range(6, 26)
    ]
    assert older_page["next_cursor"] is not None

    oldest_page_response = await list_messages(
        None,
        session_id="session-message-python-pages",
        limit=20,
        cursor=older_page["next_cursor"],
    )
    oldest_page = oldest_page_response._value.result

    assert [item["content"] for item in oldest_page["messages"]] == [
        f"message-python-{index:02d}" for index in range(1, 6)
    ]
    assert oldest_page["next_cursor"] is None


def test_websocket_update_schedule_syncs_schedule_manager(client, session):
    schedule = ScheduleModel(
        id="schedule-sync-update",
        name="Sync me",
        cron_expression="0 0 * * *",
        timezone="UTC",
        enabled=True,
        args={"instruction": "Initial instruction"},
    )
    session.add(schedule)
    session.commit()

    sync_schedule = AsyncMock()
    app.state.schedule_manager.sync_schedule = sync_schedule

    with client.websocket_connect(websocket_path()) as websocket:
        response = send_rpc(
            websocket,
            "update_schedule",
            {
                "schedule_id": "schedule-sync-update",
                "name": "Sync me updated",
                "cron_expression": "0 8 * * *",
                "timezone": "Asia/Shanghai",
                "instruction": "Updated instruction",
            },
            request_id=200,
        )

    assert response["result"] == {"status": "success"}
    sync_schedule.assert_awaited_once_with("schedule-sync-update")


def test_websocket_get_schedule_serializes_legacy_naive_datetime_as_explicit_utc(client, session):
    schedule = ScheduleModel(
        id="schedule-legacy-utc",
        name="Legacy UTC schedule",
        cron_expression="14 10 * * *",
        timezone="Asia/Shanghai",
        enabled=True,
        args={"instruction": "Keep UTC storage explicit."},
    )
    session.add(schedule)
    session.commit()

    session.execute(
        text(
            """
            UPDATE schedules
            SET next_run_at = :next_run_at,
                created_at = :created_at,
                updated_at = :updated_at
            WHERE id = :schedule_id
            """
        ),
        {
            "schedule_id": schedule.id,
            "next_run_at": "2026-04-19 02:14:00.000000",
            "created_at": "2026-04-19 02:10:45.476888",
            "updated_at": "2026-04-19 02:12:26.522405",
        },
    )
    session.commit()
    session.expire_all()

    with client.websocket_connect(websocket_path()) as websocket:
        response = send_rpc(websocket, "get_schedule", {"schedule_id": schedule.id}, request_id=204)

    payload = response["result"]["schedule"]
    assert payload["next_run_at"] == "2026-04-19T02:14:00Z"
    assert payload["created_at"] == "2026-04-19T02:10:45.476888Z"
    assert payload["updated_at"] == "2026-04-19T02:12:26.522405Z"


def test_websocket_delete_schedule_removes_scheduler_job(client, session):
    schedule = ScheduleModel(
        id="schedule-sync-delete",
        name="Delete me",
        cron_expression="0 0 * * *",
        timezone="UTC",
        enabled=True,
        args={"instruction": "Delete instruction"},
    )
    session.add(schedule)
    session.commit()

    remove_schedule = AsyncMock()
    app.state.schedule_manager.remove_schedule = remove_schedule

    with client.websocket_connect(websocket_path()) as websocket:
        response = send_rpc(
            websocket,
            "delete_schedule",
            {"schedule_id": "schedule-sync-delete"},
            request_id=201,
        )

    assert response["result"] == {"status": "success"}
    remove_schedule.assert_awaited_once_with("schedule-sync-delete")


def test_websocket_update_schedule_can_disable_invalid_persisted_schedule(client, session):
    schedule = ScheduleModel(
        id="schedule-invalid-disable",
        name="Broken schedule",
        cron_expression="not-a-cron",
        timezone="Mars/Base",
        enabled=True,
        args={"instruction": "Still disable me"},
        next_run_at=datetime.now(timezone.utc),
    )
    session.add(schedule)
    session.commit()

    sync_schedule = AsyncMock()
    app.state.schedule_manager.sync_schedule = sync_schedule

    with client.websocket_connect(websocket_path()) as websocket:
        response = send_rpc(
            websocket,
            "update_schedule",
            {
                "schedule_id": "schedule-invalid-disable",
                "enabled": False,
            },
            request_id=202,
        )

    session.expire_all()
    refreshed = session.get(ScheduleModel, "schedule-invalid-disable")

    assert response["result"] == {"status": "success"}
    assert refreshed is not None
    assert refreshed.enabled is False
    assert refreshed.next_run_at is None
    sync_schedule.assert_awaited_once_with("schedule-invalid-disable")


def test_websocket_update_schedule_reenables_schedule_and_restores_next_run(client, session):
    schedule = ScheduleModel(
        id="schedule-reenable",
        name="Re-enable me",
        cron_expression="0 8 * * *",
        timezone="UTC",
        enabled=False,
        args={"instruction": "Run again"},
        next_run_at=None,
    )
    session.add(schedule)
    session.commit()

    sync_schedule = AsyncMock()
    app.state.schedule_manager.sync_schedule = sync_schedule

    with client.websocket_connect(websocket_path()) as websocket:
        response = send_rpc(
            websocket,
            "update_schedule",
            {
                "schedule_id": "schedule-reenable",
                "enabled": True,
            },
            request_id=203,
        )

    session.expire_all()
    refreshed = session.get(ScheduleModel, "schedule-reenable")

    assert response["result"] == {"status": "success"}
    assert refreshed is not None
    assert refreshed.enabled is True
    assert refreshed.next_run_at is not None
    sync_schedule.assert_awaited_once_with("schedule-reenable")


def test_scheduler_runs_due_schedule_during_app_lifespan(session, monkeypatch):
    from apscheduler.triggers.date import DateTrigger

    calls: list[dict[str, str]] = []

    async def fake_run_master_agent(self, instruction: str, session_id: str, *, run_id: str, emit_event_cb=None):
        calls.append({"instruction": instruction, "session_id": session_id})
        return {"status": "success"}

    def fake_build_cron_trigger(cron_expression: str, timezone_name: str | None = None):
        return DateTrigger(run_date=datetime.now(timezone.utc) + timedelta(milliseconds=50))

    schedule = ScheduleModel(
        id="schedule-lifespan-run",
        name="Lifespan schedule",
        cron_expression="* * * * *",
        timezone="UTC",
        enabled=True,
        args={"instruction": "Run during lifespan"},
    )
    session.add(schedule)
    session.commit()

    monkeypatch.setattr("app.core.schedule_manager.build_cron_trigger", fake_build_cron_trigger)
    monkeypatch.setattr("app.core.runtime.FerrymanRuntime.run_master_agent", fake_run_master_agent)

    with TestClient(app):
        time.sleep(0.2)

    session.expire_all()
    refreshed = session.get(ScheduleModel, "schedule-lifespan-run")
    persisted_session = session.get(SessionModel, "schedule-lifespan-run")

    assert calls == [{"instruction": "Run during lifespan", "session_id": "schedule-lifespan-run"}]
    assert refreshed is not None
    assert refreshed.last_run_at is not None
    assert refreshed.total_run_count == 1
    assert refreshed.last_run_result is not None
    assert refreshed.last_run_result["status"] == "success"
    assert persisted_session is not None
