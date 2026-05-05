import logging
import os
from contextlib import asynccontextmanager
from logging.config import dictConfig
from typing import Optional

from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import FastAPI

from app.core.config import get_settings
from app.core.runtime import FerrymanRuntime
from app.rpc.registry import register_rpc_methods
from app.rpc.websocket import register_websocket

logger = logging.getLogger(__name__)
DEFAULT_FERRYMAN_BEARER_TOKEN = "dev-token"


def configure_logging(log_level: Optional[str] = None) -> None:
    settings = get_settings()
    log_level = (log_level or settings.log_level).upper()
    log_dir = settings.log_dir
    log_file = log_dir / "ferryman.log"

    os.makedirs(log_dir, exist_ok=True)

    dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "correlation_id": {
                "()": "asgi_correlation_id.CorrelationIdFilter",
                "uuid_length": 32,
                "default_value": "-",
            },
        },
        "formatters": {
            "json": {
                "()": "pythonjsonlogger.orjson.OrjsonFormatter",
                "format": "%(asctime)s %(levelname)s %(name)s %(module)s %(funcName)s:%(lineno)d [%(correlation_id)s] %(message)s",
                "rename_fields": {"levelname": "severity", "asctime": "timestamp"},
            },
            "standard": {
                "format": "%(asctime)s [%(levelname)s] %(name)s [%(correlation_id)s]: %(message)s",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "filters": ["correlation_id"],
                "formatter": "json",
            },
            "file": {
                "class": "logging.handlers.TimedRotatingFileHandler",
                "filename": str(log_file),
                "when": "D",
                "interval": 1,
                "backupCount": 3,
                "filters": ["correlation_id"],
                "formatter": "json",
                "encoding": "utf-8",
            },
        },
        "loggers": {
            "": {
                "handlers": ["console", "file"],
                "level": log_level,
            },
            "httpx": {
                "level": "WARNING",
                "handlers": ["console", "file"],
                "propagate": False,
            },
            "httpcore": {
                "level": "WARNING",
                "handlers": ["console", "file"],
                "propagate": False,
            },
            "trafilatura": {
                "level": "WARNING",
                "handlers": ["console", "file"],
                "propagate": False,
            },
            "pydantic_ai": {
                "level": log_level,
                "handlers": ["console", "file"],
                "propagate": False,
            },
        },
    })


@asynccontextmanager
async def lifespan(fastapi_app: FastAPI):
    configure_logging()
    logger.info("🚀 Ferryman Sidecar starting...")

    fastapi_app.state.runtime = FerrymanRuntime(get_settings())
    fastapi_app.state.bearer_token = os.environ.get("FERRYMAN_BEARER_TOKEN") or DEFAULT_FERRYMAN_BEARER_TOKEN
    fastapi_app.state.execute_runs = {}
    fastapi_app.state.session_run_index = {}

    fastapi_app.state.runtime.skill_manager.scan_skills()
    fastapi_app.state.schedule_manager = fastapi_app.state.runtime.schedule_manager
    await fastapi_app.state.schedule_manager.start()

    yield
    await fastapi_app.state.schedule_manager.shutdown()
    await fastapi_app.state.runtime.browser_manager.shutdown()
    logger.info("🛑 Ferryman Sidecar shutting down...")


register_rpc_methods()

app = FastAPI(title="Ferryman Sidecar", lifespan=lifespan)
app.add_middleware(CorrelationIdMiddleware, update_request_header=True)  # type:ignore
register_websocket(app)


if __name__ == "__main__":
    from app.sidecar import main

    main()
