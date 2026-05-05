from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from asgi_correlation_id import correlation_id
from jsonrpcserver import Success, method
from sqlalchemy import func
from sqlmodel import desc, select

from app.core.db import get_session
from app.models.database import Message, Session
from app.models.events import FerrymanEventEnvelope
from app.rpc.events import build_emit_ws_event, emit_refresh_event

logger = logging.getLogger(__name__)


def load_persisted_chat_run_event(session_id: str, run_id: str) -> FerrymanEventEnvelope | None:
    from app.models.events import ChatFinalPayload, EventNamespace

    with get_session() as db_session:
        assistant_message = db_session.exec(
            select(Message)
            .where(
                Message.session_id == session_id,
                Message.role == "assistant",
                func.json_extract(Message.metadata_, "$.run.id") == run_id,
            )
            .order_by(desc(Message.created_at))
        ).first()

        if not assistant_message:
            return None

        metadata = dict(assistant_message.metadata_ or {})
        usage = metadata.get("usage") or {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        return FerrymanEventEnvelope(
            namespace=EventNamespace.AGENT,
            event="chat_final",
            session_id=session_id,
            payload=ChatFinalPayload(
                run_id=run_id,
                messages=[
                    {
                        "role": "assistant",
                        "content": assistant_message.content,
                        "metadata": metadata,
                    }
                ],
                usage=usage,
            ),
        )


def persist_failed_chat_run(
    session_id: str,
    run_id: str,
    error_message: str,
    instruction: str | None = None,
) -> FerrymanEventEnvelope:
    from app.models.events import ChatFinalPayload, EventNamespace

    failure_content = f"Run failed: {error_message}"
    failure_metadata = {
        "run": {
            "id": run_id,
            "status": "failed",
            "scope": "master",
            "error": error_message,
        }
    }

    with get_session() as db_session:
        session_obj = db_session.get(Session, session_id)
        if not session_obj:
            session_obj = Session(id=session_id, title="")
            db_session.add(session_obj)
            db_session.flush()

        user_message = db_session.exec(
            select(Message)
            .where(
                Message.session_id == session_id,
                Message.role == "user",
                func.json_extract(Message.metadata_, "$.run.id") == run_id,
            )
            .order_by(desc(Message.created_at))
        ).first()
        if user_message:
            user_meta = dict(user_message.metadata_ or {})
            user_meta["run"] = failure_metadata["run"]
            user_message.metadata_ = user_meta
            db_session.add(user_message)
        elif instruction is not None:
            db_session.add(
                Message(
                    session_id=session_id,
                    role="user",
                    content=instruction,
                    type="text",
                    metadata_=failure_metadata,
                )
            )

        assistant_message = db_session.exec(
            select(Message)
            .where(
                Message.session_id == session_id,
                Message.role == "assistant",
                func.json_extract(Message.metadata_, "$.run.id") == run_id,
            )
            .order_by(desc(Message.created_at))
        ).first()
        if not assistant_message:
            db_session.add(
                Message(
                    session_id=session_id,
                    role="assistant",
                    content=failure_content,
                    type="text",
                    metadata_=failure_metadata,
                )
            )

        session_obj.updated_at = datetime.now(timezone.utc)
        db_session.add(session_obj)
        db_session.commit()

    persisted_event = load_persisted_chat_run_event(session_id, run_id)
    if persisted_event is not None:
        return persisted_event

    return FerrymanEventEnvelope(
        namespace=EventNamespace.AGENT,
        event="chat_final",
        session_id=session_id,
        payload=ChatFinalPayload(
            run_id=run_id,
            messages=[
                {
                    "role": "assistant",
                    "content": failure_content,
                    "metadata": failure_metadata,
                }
            ],
            usage={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        ),
    )


def persist_canceled_chat_run(session_id: str, run_id: str) -> FerrymanEventEnvelope:
    from app.models.events import ChatFinalPayload, EventNamespace

    canceled_message = {
        "role": "assistant",
        "content": "Run canceled.",
        "metadata": {
            "run": {
                "id": run_id,
                "status": "canceled",
                "scope": "master",
            }
        },
    }

    with get_session() as db_session:
        session_obj = db_session.get(Session, session_id)
        if not session_obj:
            session_obj = Session(id=session_id, title="")
            db_session.add(session_obj)
            db_session.flush()

        user_message = db_session.exec(
            select(Message)
            .where(
                Message.session_id == session_id,
                Message.role == "user",
                func.json_extract(Message.metadata_, "$.run.id") == run_id,
            )
            .order_by(desc(Message.created_at))
        ).first()
        if user_message:
            user_meta = dict(user_message.metadata_ or {})
            user_meta["run"] = {
                "id": run_id,
                "status": "canceled",
                "scope": "master",
            }
            user_message.metadata_ = user_meta
            db_session.add(user_message)

        if session_obj:
            session_obj.updated_at = datetime.now(timezone.utc)
            db_session.add(session_obj)

        db_session.commit()

    return FerrymanEventEnvelope(
        namespace=EventNamespace.AGENT,
        event="chat_final",
        session_id=session_id,
        payload=ChatFinalPayload(
            run_id=run_id,
            messages=[canceled_message],
            usage={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        ),
    )


def has_persisted_pending_chat_run(session_id: str, run_id: str) -> bool:
    with get_session() as db_session:
        return db_session.exec(
            select(Message.id).where(
                Message.session_id == session_id,
                Message.role == "user",
                func.json_extract(Message.metadata_, "$.run.id") == run_id,
                func.json_extract(Message.metadata_, "$.run.status") == "pending",
            )
        ).first() is not None


async def background_generate_title(runtime, session_id: str, instruction: str, emit_event_cb=None):
    try:
        from pydantic_ai.agent import Agent

        logger.info(f"Generating auto-title for session {session_id}")

        llm = runtime.model_manager.create_active_model()
        agent = Agent(
            llm,
            system_prompt=(
                "You are a helpful assistant. Summarize the user's instruction into a very short chat title "
                "(MAX 5 words). Output ONLY the title, no quotes, no extra text."
            ),
        )
        result = await agent.run(f"User instruction: {instruction}")

        generated_title = result.output.strip(' \'"')
        logger.info(f"Generated title for session {session_id}: {generated_title}")

        with get_session() as db_session:
            session_obj = db_session.get(Session, session_id)
            if session_obj and not session_obj.title:
                session_obj.title = generated_title
                session_obj.updated_at = datetime.now(timezone.utc)
                db_session.add(session_obj)
                db_session.commit()
                await emit_refresh_event(
                    emit_event_cb,
                    entity="session",
                    action="updated",
                    entity_id=session_id,
                    delta={"title": generated_title},
                    session_id=session_id,
                )
    except Exception as e:
        logger.error(f"Failed to auto-generate title for session {session_id}: {e}")


async def background_execute_run(
    *,
    context,
    instruction: str,
    session_id: str,
    run_id: str,
    emit_event_cb,
) -> None:
    app_state = context.app_state
    correlation_token = correlation_id.set(run_id)
    try:
        try:
            result = await context.runtime.run_master_agent(
                instruction=instruction,
                session_id=session_id,
                emit_event_cb=emit_event_cb,
            )
        except Exception as exc:
            logger.exception(f"Background execute run failed for session {session_id}")
            failed_event = persist_failed_chat_run(
                session_id=session_id,
                run_id=run_id,
                error_message=str(exc),
                instruction=instruction,
            )
            await emit_event_cb(failed_event)
            return

        try:
            final_event = FerrymanEventEnvelope.model_validate(result)
        except Exception as exc:
            logger.exception(f"Failed to validate final event for session {session_id}")
            fallback_event = load_persisted_chat_run_event(session_id, run_id)
            if fallback_event is None:
                fallback_event = persist_failed_chat_run(
                    session_id=session_id,
                    run_id=run_id,
                    error_message=str(exc),
                    instruction=instruction,
                )
            await emit_event_cb(fallback_event)
            return

        await emit_event_cb(final_event)

        need_title_gen = False
        with get_session() as db_session:
            session_obj = db_session.get(Session, session_id)
            if session_obj and not session_obj.title:
                need_title_gen = True

        if need_title_gen:
            asyncio.create_task(
                background_generate_title(context.runtime, session_id, instruction, emit_event_cb)
            )
    except asyncio.CancelledError:
        canceled_event = persist_canceled_chat_run(session_id, run_id)
        await emit_event_cb(canceled_event)
        raise
    finally:
        correlation_id.reset(correlation_token)
        app_state.execute_runs.pop(run_id, None)
        if app_state.session_run_index.get(session_id) == run_id:
            app_state.session_run_index.pop(session_id, None)
        try:
            await emit_refresh_event(
                emit_event_cb,
                entity="session",
                action="updated",
                entity_id=session_id,
                session_id=session_id,
            )
        except Exception:
            logger.exception(f"Failed to emit session refresh for {session_id}")


@method
async def execute(context, instruction: str, session_id: str = "default"):
    """Start a background Agent run and return immediately with its run_id."""
    if context and hasattr(context, "runtime"):
        active_run_id = context.app_state.session_run_index.get(session_id)
        if active_run_id:
            active_entry = context.app_state.execute_runs.get(active_run_id)
            if active_entry and not active_entry["task"].done():
                return Success({
                    "status": "busy",
                    "run_id": active_run_id,
                    "session_id": session_id,
                    "message": "Current session already has an active run.",
                })

        websocket = getattr(context, "request_ws", None)
        send_lock = getattr(context, "send_lock", None)
        if websocket is None or send_lock is None:
            return Success({"status": "error", "message": "WebSocket context unavailable"})

        run_id = uuid4().hex
        emit_ws_event = build_emit_ws_event(websocket, send_lock)
        task = asyncio.create_task(
            background_execute_run(
                context=context,
                instruction=instruction,
                session_id=session_id,
                run_id=run_id,
                emit_event_cb=emit_ws_event,
            )
        )
        context.app_state.execute_runs[run_id] = {
            "task": task,
            "session_id": session_id,
            "instruction": instruction,
        }
        context.app_state.session_run_index[session_id] = run_id
        return Success({"status": "started", "run_id": run_id, "session_id": session_id})

    return Success({"status": "error", "message": "Runtime not initialized"})


@method
async def cancel_run(context, run_id: str, session_id: Optional[str] = None):
    """Cancel an active chat run."""
    if not context:
        return Success({"status": "error", "message": "Context unavailable"})

    entry = context.app_state.execute_runs.get(run_id)
    if not entry:
        if session_id and has_persisted_pending_chat_run(session_id, run_id):
            logger.warning(
                f"Canceling persisted pending run {run_id} for session {session_id} "
                "after active run was not found"
            )
            canceled_event = persist_canceled_chat_run(session_id, run_id)
            websocket = getattr(context, "request_ws", None)
            send_lock = getattr(context, "send_lock", None)
            emit_ws_event = (
                build_emit_ws_event(websocket, send_lock)
                if websocket is not None and send_lock is not None
                else None
            )
            if websocket is not None and send_lock is not None:
                await emit_ws_event(canceled_event)
            await emit_refresh_event(
                emit_ws_event,
                entity="session",
                action="updated",
                entity_id=session_id,
                session_id=session_id,
            )
            return Success({"status": "canceled", "run_id": run_id, "session_id": session_id})
        return Success({"status": "not_found", "run_id": run_id})

    if session_id and entry["session_id"] != session_id:
        return Success({
            "status": "error",
            "message": "run_id does not match session_id",
            "run_id": run_id,
        })

    task = entry["task"]
    if task.done():
        return Success({
            "status": "already_finished",
            "run_id": run_id,
            "session_id": entry["session_id"],
        })

    task.cancel()
    return Success({"status": "canceling", "run_id": run_id, "session_id": entry["session_id"]})

