from __future__ import annotations

from collections import deque
from pathlib import Path

from jsonrpcserver import Success, method

from app.core.config import get_settings


def get_backend_log_paths() -> dict[str, str]:
    settings = get_settings()
    log_dir = settings.log_dir
    return {
        "app": str(log_dir / "ferryman.log"),
        "sidecar": str(log_dir / "ferryman-tauri.log"),
    }


def tail_lines(path: Path, lines: int = 200) -> str:
    if not path.exists():
        return ""

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return "".join(deque(handle, maxlen=lines))


@method
async def get_backend_log_info(context):
    paths = get_backend_log_paths()
    return Success({
        "paths": paths,
        "active_log": paths["app"],
    })


@method
async def read_backend_logs(context, source: str = "app", lines: int = 200):
    paths = get_backend_log_paths()
    target = Path(paths.get(source, paths["app"]))
    requested_lines = max(20, min(lines, 1000))
    return Success({
        "source": source if source in paths else "app",
        "path": str(target),
        "content": tail_lines(target, requested_lines),
    })
