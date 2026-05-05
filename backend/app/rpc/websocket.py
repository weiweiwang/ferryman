from __future__ import annotations

import asyncio
import json
import logging
import secrets

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status
from jsonrpcserver import async_dispatch

from app.models.schemas import JsonRpcError, JsonRpcErrorCode, JsonRpcErrorResponse
from app.rpc.context import build_rpc_context
from app.rpc.events import send_text_locked

logger = logging.getLogger(__name__)


def is_websocket_authorized(websocket: WebSocket) -> bool:
    presented_token = websocket.query_params.get("access_token")
    expected_token = getattr(websocket.app.state, "bearer_token", None)
    if not presented_token or not expected_token:
        return False
    return secrets.compare_digest(presented_token, expected_token)


async def websocket_endpoint(websocket: WebSocket):
    if not is_websocket_authorized(websocket):
        logger.warning("Unauthorized WebSocket connection rejected")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Unauthorized")
        return

    await websocket.accept()
    logger.info("🔌 WebSocket connection established")
    send_lock = asyncio.Lock()

    try:
        while True:
            try:
                data = await websocket.receive_text()
            except WebSocketDisconnect:
                logger.warning("❌ WebSocket disconnected")
                break

            try:
                response = await async_dispatch(data, context=build_rpc_context(websocket, send_lock))
                if response:
                    await send_text_locked(websocket, send_lock, str(response))
            except Exception:
                logger.exception("⚠️ JSON-RPC dispatch failed")
                request_id = None
                try:
                    parsed = json.loads(data)
                    if isinstance(parsed, dict):
                        candidate_id = parsed.get("id")
                        if isinstance(candidate_id, (str, int)):
                            request_id = candidate_id
                except Exception:
                    request_id = None

                error_payload = JsonRpcErrorResponse(
                    error=JsonRpcError(
                        code=JsonRpcErrorCode.INTERNAL_ERROR,
                        message="Internal server error",
                    ),
                    id=request_id,
                )
                await send_text_locked(websocket, send_lock, error_payload.model_dump_json())
    except WebSocketDisconnect:
        logger.info("❌ WebSocket disconnected")
    except Exception:
        logger.exception("⚠️ WebSocket connection-level error")
        if websocket.client_state.name != "DISCONNECTED":
            await websocket.close()


def register_websocket(app: FastAPI) -> None:
    app.websocket("/ws")(websocket_endpoint)
