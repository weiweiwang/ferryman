from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Optional

from fastapi import WebSocket

from app.models.events import FerrymanEventEnvelope

logger = logging.getLogger(__name__)


async def emit_refresh_event(
    emit_event_cb: Optional[Callable[[FerrymanEventEnvelope], Awaitable[None]]],
    *,
    entity: str,
    action: str,
    entity_id: Optional[str] = None,
    delta: Optional[dict[str, object]] = None,
    session_id: Optional[str] = None,
) -> None:
    if not emit_event_cb:
        return

    from app.models.events import DataEntity, EntityAction, EventNamespace, RefreshPayload

    event = FerrymanEventEnvelope(
        namespace=EventNamespace.DATA,
        event="refresh",
        session_id=session_id,
        payload=RefreshPayload(
            entity=DataEntity(entity),
            action=EntityAction(action),
            entity_id=entity_id,
            delta=delta,
        ),
    )
    await emit_event_cb(event)


async def send_text_locked(websocket: WebSocket, send_lock: asyncio.Lock, payload: str) -> None:
    async with send_lock:
        await websocket.send_text(payload)


async def send_event_notification(
    websocket: WebSocket,
    send_lock: asyncio.Lock,
    event_model: FerrymanEventEnvelope,
) -> None:
    await send_text_locked(
        websocket,
        send_lock,
        json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "ferryman_event",
                "params": event_model.model_dump(mode="json", exclude_none=True),
            }
        ),
    )
    payload = getattr(event_model, "payload", None)
    logger.debug({
        "message": {
            "event": "ws_event_sent",
            "ws_event": getattr(event_model, "event", None),
            "namespace": getattr(event_model, "namespace", None),
            "session_id": getattr(event_model, "session_id", None),
            "run_id": getattr(payload, "run_id", None),
            "tool_name": getattr(payload, "tool_name", None),
            "phase": getattr(payload, "phase", None),
            "event_id": getattr(payload, "event_id", None),
            "seq": getattr(payload, "seq", None),
        }
    })


def build_emit_ws_event(websocket: WebSocket, send_lock: asyncio.Lock) -> Callable[[FerrymanEventEnvelope], Awaitable[None]]:
    async def emit_ws_event(event_model: FerrymanEventEnvelope) -> None:
        try:
            if websocket.client_state.name == "CONNECTED":
                await send_event_notification(websocket, send_lock, event_model)
        except Exception as e:
            logger.error(f"Failed to emit WS event {getattr(event_model, 'event', 'unknown')}: {e}")

    return emit_ws_event

