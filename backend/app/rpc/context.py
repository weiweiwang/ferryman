from __future__ import annotations

import asyncio
from types import SimpleNamespace

from fastapi import WebSocket


def build_rpc_context(websocket: WebSocket, send_lock: asyncio.Lock) -> SimpleNamespace:
    app_state = websocket.app.state
    return SimpleNamespace(
        runtime=app_state.runtime,
        bearer_token=app_state.bearer_token,
        schedule_manager=app_state.schedule_manager,
        app_state=app_state,
        request_ws=websocket,
        send_lock=send_lock,
    )

