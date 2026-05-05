from __future__ import annotations

from jsonrpcserver import Success, method


@method
async def ping(context):
    return Success("pong")

