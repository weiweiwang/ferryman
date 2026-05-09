"""Build safe, compact payload fields for tool_activity websocket events."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.core.deps import AgentDeps
from app.core.toolkits.file import FileToolkit

logger = logging.getLogger(__name__)
TEXT_OUTPUT_LIMIT = 2000
NESTED_TEXT_LIMIT = 500


def summarize_tool_input_value(key: str, value: object) -> object:
    if hasattr(value, "model_dump"):
        value = value.model_dump()

    if key.lower() in {"api_key", "base_url"} or any(
        secret_key in key.lower() for secret_key in ("secret", "token", "password")
    ):
        return {"_summary": "redacted"}

    if isinstance(value, str):
        if key in {"content", "text", "body", "markdown", "html", "instruction", "prompt"}:
            return {"_summary": "omitted", "length": len(value)}
        if len(value) > 240:
            return f"{value[:237]}..."
        return value

    if isinstance(value, (bytes, bytearray)):
        return {"_summary": "binary", "length": len(value)}

    return value


def build_tool_activity_input(
    deps: AgentDeps,
    *,
    tool_name: str,
    args: str | dict[str, Any],
) -> dict[str, object]:
    input_summary = _summarize_tool_args(args)
    _replace_file_input_with_resolved_path(deps, tool_name, input_summary)

    raw_input = json.dumps(input_summary, default=str)
    if len(raw_input) > 2000:
        preserved_keys = ("url", "path", "command", "title", "skill_name")
        input_summary = {
            key: value for key, value in input_summary.items() if key in preserved_keys
        }
        input_summary["_truncated"] = True
        input_summary["_size"] = len(raw_input)

    return input_summary


def compact_tool_event_text(value: object, max_length: int = TEXT_OUTPUT_LIMIT) -> str | None:
    if value is None:
        return None

    if isinstance(value, str):
        text = value
    elif isinstance(value, (dict, list, tuple, set)):
        text = json.dumps(_sanitize_output_value(value), ensure_ascii=False, default=str)
    elif isinstance(value, (bytes, bytearray)):
        text = json.dumps(
            {"_summary": "binary", "length": len(value)},
            ensure_ascii=False,
        )
    else:
        text = str(value)

    text = text.strip()
    if not text:
        return None
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 3]}..."


def _summarize_tool_args(args: str | dict[str, Any]) -> dict[str, object]:
    if isinstance(args, str):
        try:
            parsed = json.loads(args)
        except json.JSONDecodeError:
            return {"_raw": summarize_tool_input_value("_raw", args)}
        if not isinstance(parsed, dict):
            return {"_raw": summarize_tool_input_value("_raw", parsed)}
        args = parsed

    return {
        str(key): summarize_tool_input_value(str(key), value)
        for key, value in args.items()
    }


def _sanitize_output_value(value: object) -> object:
    if hasattr(value, "model_dump"):
        value = value.model_dump()

    if isinstance(value, dict):
        sanitized: dict[str, object] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() in {"api_key", "base_url"} or any(
                secret_key in key_text.lower() for secret_key in ("secret", "token", "password")
            ):
                sanitized[key_text] = {"_summary": "redacted"}
            else:
                sanitized[key_text] = _sanitize_output_value(item)
        return sanitized

    if isinstance(value, str):
        if len(value) > NESTED_TEXT_LIMIT:
            return f"{value[: NESTED_TEXT_LIMIT - 3]}..."
        return value

    if isinstance(value, (bytes, bytearray)):
        return {"_summary": "binary", "length": len(value)}

    if isinstance(value, (list, tuple, set)):
        return [_sanitize_output_value(item) for item in value]

    return value


def _replace_file_input_with_resolved_path(
    deps: AgentDeps,
    tool_name: str,
    input_summary: dict[str, object],
) -> None:
    raw_path_value: object = None
    if tool_name in {"read_file", "write_file"}:
        raw_path_value = input_summary.get("file_path")
    elif tool_name == "list_files":
        raw_path_value = input_summary.get("directory", ".")

    if not isinstance(raw_path_value, str):
        return

    raw_path = raw_path_value
    try:
        if tool_name in {"read_file", "list_files"}:
            resolved_path = FileToolkit.resolve_read_path(
                deps,
                deps.session_id,
                raw_path,
                deps.skill_name,
            )
        else:
            resolved_path = FileToolkit.resolve_session_path(
                deps,
                deps.session_id,
                raw_path,
            )
        input_summary.pop("file_path", None)
        input_summary.pop("directory", None)
        input_summary["path"] = str(resolved_path)
    except Exception as e:
        logger.exception({
            "message": {
                "event": "tool_input_path_resolution_failed",
                "run_id": deps.run_id,
                "session_id": deps.session_id,
                "skill_name": deps.skill_name,
                "tool_name": tool_name,
                "raw_path": raw_path,
                "error": str(e),
            }
        })
