from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict
from pydantic_ai.messages import BinaryImage, ToolReturn

TOOL_RESULT_KEYS = frozenset({"tool_name", "status", "summary", "data", "error"})
ERROR_STATUSES = frozenset({"error", "failed", "failure"})
SCRIPT_STDOUT_LIMIT = 4000
SCRIPT_STDERR_SUCCESS_LIMIT = 800
SCRIPT_STDERR_ERROR_LIMIT = 4000


class ToolErrorPayload(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    type: str
    message: str
    retryable: bool


class ToolResultEnvelope(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    tool_name: str
    status: Literal["success", "error"]
    summary: str
    data: object = None
    error: ToolErrorPayload | None = None


def _normalize_data(value: object) -> object:
    if hasattr(value, "model_dump"):
        value = value.model_dump()

    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, dict):
        return {str(key): _normalize_data(item) for key, item in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [_normalize_data(item) for item in value]

    return str(value)


def is_tool_result_envelope(value: object) -> bool:
    return isinstance(value, dict) and TOOL_RESULT_KEYS.issubset(value.keys())


def _extract_embedded_error_message(value: object) -> str | None:
    if not isinstance(value, dict):
        return None

    error = value.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if message:
            return str(message)
    elif error:
        return str(error)

    message = value.get("message") or value.get("summary") or value.get("detail")
    if message:
        return str(message)

    if value.get("ok") is False or value.get("success") is False:
        return "Tool reported failure."

    status = value.get("status")
    if isinstance(status, str) and status.strip().lower() in ERROR_STATUSES:
        return "Tool reported failure."

    return None


def _looks_like_embedded_error(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    if value.get("ok") is False or value.get("success") is False:
        return True
    status = value.get("status")
    return isinstance(status, str) and status.strip().lower() in ERROR_STATUSES


def build_tool_result_envelope(
    tool_name: str,
    *,
    status: str,
    data: object = None,
    error: dict[str, object] | None = None,
    summary: str | None = None,
) -> ToolResultEnvelope:
    return ToolResultEnvelope(
        tool_name=tool_name,
        status=status,
        summary=summary or (
            f"{tool_name} completed successfully."
            if status == "success"
            else f"{tool_name} failed."
        ),
        data=data,
        error=ToolErrorPayload(**error) if error else None,
    )


def dump_tool_result_envelope(envelope: ToolResultEnvelope | dict[str, object]) -> str:
    if isinstance(envelope, dict):
        envelope = ToolResultEnvelope.model_validate(envelope)
    return envelope.model_dump_json(ensure_ascii=False)


def build_tool_success_result(tool_name: str, raw_result: object) -> str | ToolReturn:
    if isinstance(raw_result, ToolReturn):
        normalized = _normalize_data(raw_result.return_value)
        envelope = (
            ToolResultEnvelope.model_validate(normalized)
            if is_tool_result_envelope(normalized)
            else _build_normalized_envelope(tool_name, normalized)
        )
        return ToolReturn(
            return_value=dump_tool_result_envelope(envelope),
            content=raw_result.content,
            metadata=raw_result.metadata,
        )

    if isinstance(raw_result, BinaryImage):
        envelope = build_tool_result_envelope(
            tool_name,
            status="success",
            data={
                "kind": "binary_image",
                "media_type": raw_result.media_type,
                "identifier": raw_result.identifier,
            },
            summary=f"{tool_name} produced an image result.",
        )
        return ToolReturn(
            return_value=dump_tool_result_envelope(envelope),
            content=[raw_result],
            metadata=envelope.model_dump(mode="json"),
        )

    normalized = _compact_tool_data_for_model(tool_name, _normalize_data(raw_result))
    if is_tool_result_envelope(normalized):
        envelope = ToolResultEnvelope.model_validate(normalized)
    else:
        envelope = _build_normalized_envelope(tool_name, normalized)
    return dump_tool_result_envelope(envelope)


def build_tool_error_result(
    tool_name: str,
    *,
    message: str,
    error_type: str,
    retryable: bool,
    summary: str | None = None,
    data: object = None,
) -> str:
    envelope = build_tool_result_envelope(
        tool_name,
        status="error",
        summary=summary,
        data=_normalize_data(data),
        error={
            "type": error_type,
            "message": message,
            "retryable": retryable,
        },
    )
    return dump_tool_result_envelope(envelope)


def _build_normalized_envelope(tool_name: str, normalized: object) -> ToolResultEnvelope:
    if _looks_like_embedded_error(normalized):
        return build_tool_result_envelope(
            tool_name,
            status="error",
            summary=f"{tool_name} reported an error.",
            data=normalized,
            error={
                "type": "tool_result_error",
                "message": _extract_embedded_error_message(normalized) or "Tool reported failure.",
                "retryable": False,
            },
        )

    return build_tool_result_envelope(tool_name, status="success", data=normalized)


def _compact_tool_data_for_model(tool_name: str, normalized: object) -> object:
    if tool_name != "run_skill_script" or not isinstance(normalized, dict):
        return normalized

    stdout = str(normalized.get("stdout") or "")
    stderr = str(normalized.get("stderr") or "")
    ok = normalized.get("ok") is True

    compact: dict[str, object] = {
        "ok": normalized.get("ok"),
        "script_name": normalized.get("script_name"),
        "exit_code": normalized.get("exit_code"),
        "timed_out": normalized.get("timed_out"),
        "stdout": _truncate_text(stdout, SCRIPT_STDOUT_LIMIT),
        "stdout_chars": len(stdout),
        "stdout_truncated": len(stdout) > SCRIPT_STDOUT_LIMIT,
        "stderr": _truncate_text(
            stderr,
            SCRIPT_STDERR_SUCCESS_LIMIT if ok else SCRIPT_STDERR_ERROR_LIMIT,
        ),
        "stderr_chars": len(stderr),
        "stderr_truncated": len(stderr) > (SCRIPT_STDERR_SUCCESS_LIMIT if ok else SCRIPT_STDERR_ERROR_LIMIT),
    }

    cwd = normalized.get("cwd")
    if cwd:
        compact["cwd"] = cwd

    return compact


def _truncate_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."
