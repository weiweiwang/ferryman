from __future__ import annotations

import inspect
import json
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from functools import wraps
from typing import Any

from asgi_correlation_id import correlation_id
from pydantic import ValidationError
from pydantic_ai import RunContext
from pydantic_ai.agent import Agent
from pydantic_ai.capabilities.abstract import AbstractCapability
from pydantic_ai.exceptions import ModelRetry, SkipToolExecution
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.tools import ToolDefinition

from app.core.deps import AgentDeps
from app.core.tool_errors import RetryableToolError
from app.core.tool_results import build_tool_error_result, build_tool_success_result
from app.core.toolkits.base import Toolkit
from app.core.toolkits.command import CommandToolkit
from app.core.toolkits.email import EmailToolkit
from app.core.toolkits.file import FileToolkit
from app.core.toolkits.image import ImageToolkit
from app.core.toolkits.skill import SkillToolkit
from app.core.toolkits.task import TaskToolkit
from app.core.toolkits.time import TimeToolkit
from app.core.toolkits.web import WebToolkit

logger = logging.getLogger(__name__)

ToolFunction = Callable[..., Awaitable[object]]
TOOL_VALIDATION_ERROR_KEY = "_tool_validation_error"

DEFAULT_TOOLKITS: tuple[type[Toolkit], ...] = (
    SkillToolkit,
    FileToolkit,
    WebToolkit,
    TaskToolkit,
    TimeToolkit,
    EmailToolkit,
    ImageToolkit,
    CommandToolkit,
)


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


def _schema_accepts_type(schema: object, expected_type: str) -> bool:
    if not isinstance(schema, dict):
        return False

    schema_type = schema.get("type")
    if schema_type == expected_type:
        return True
    if isinstance(schema_type, list) and expected_type in schema_type:
        return True

    for key in ("anyOf", "oneOf"):
        variants = schema.get(key)
        if isinstance(variants, list) and any(
            _schema_accepts_type(item, expected_type) for item in variants
        ):
            return True

    variants = schema.get("allOf")
    if isinstance(variants, list) and all(
        _schema_accepts_type(item, expected_type) for item in variants
    ):
        return True
    return False


def _coerce_tool_args_for_validation(args: str | dict[str, Any], schema: object) -> str | dict[str, Any]:
    """Coerce model-produced tool args into shapes expected by the tool schema."""
    if isinstance(args, str):
        try:
            parsed = json.loads(args)
        except json.JSONDecodeError:
            return args
        if not isinstance(parsed, dict):
            return args
        args = parsed

    if not isinstance(args, dict) or not isinstance(schema, dict):
        return args

    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return args

    normalized: dict[str, Any] | None = None
    for key, value in args.items():
        field_schema = properties.get(key)
        if not isinstance(value, str) or not isinstance(field_schema, dict):
            continue

        raw_value = value.strip()
        if not raw_value or raw_value[0] not in "[{":
            continue

        try:
            parsed_value = json.loads(raw_value)
        except json.JSONDecodeError:
            continue

        if isinstance(parsed_value, list) and _schema_accepts_type(field_schema, "array"):
            normalized = dict(args) if normalized is None else normalized
            normalized[key] = parsed_value
        elif isinstance(parsed_value, dict) and _schema_accepts_type(field_schema, "object"):
            normalized = dict(args) if normalized is None else normalized
            normalized[key] = parsed_value

    return normalized or args


class FerrymanToolValidationCapability(AbstractCapability[AgentDeps]):
    """Normalize model tool args and return validation failures as tool results."""

    async def before_tool_validate(
        self,
        ctx: RunContext[AgentDeps],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: str | dict[str, Any],
    ) -> str | dict[str, Any]:
        return _coerce_tool_args_for_validation(args, tool_def.parameters_json_schema)

    async def on_tool_validate_error(
        self,
        ctx: RunContext[AgentDeps],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: str | dict[str, Any],
        error: ValidationError | ModelRetry,
    ) -> dict[str, Any]:
        return {TOOL_VALIDATION_ERROR_KEY: str(error)}

    async def before_tool_execute(
        self,
        ctx: RunContext[AgentDeps],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: dict[str, Any],
    ) -> dict[str, Any]:
        validation_error = args.get(TOOL_VALIDATION_ERROR_KEY)
        if validation_error:
            raise SkipToolExecution(
                build_tool_error_result(
                    call.tool_name,
                    message=str(validation_error),
                    error_type="tool_validation_error",
                    retryable=True,
                    summary=(
                        f"{call.tool_name} could not run because tool arguments failed validation."
                    ),
                )
            )
        return args


class ToolManager:
    """Register toolkits and wrap tool execution behavior."""

    def __init__(self, default_toolkits: Sequence[type[Toolkit]] = DEFAULT_TOOLKITS) -> None:
        self._default_toolkits = default_toolkits

    def register_default_toolkits(self, agent: Agent) -> None:
        for toolkit_class in self._default_toolkits:
            self.register_toolkit(agent, toolkit_class)

    @staticmethod
    def get_capabilities() -> list[AbstractCapability[AgentDeps]]:
        return [FerrymanToolValidationCapability()]

    def register_toolkit(self, agent: Agent, toolkit_class: type[Toolkit]) -> None:
        """Register all tools from a toolkit class using its get_tools() method."""
        for tool_func in toolkit_class.get_tools():
            agent.tool(self.wrap_tool(tool_func))

    def wrap_tool(self, bound_tool_func: ToolFunction) -> ToolFunction:
        @wraps(bound_tool_func)
        async def wrapped_tool(ctx: RunContext[AgentDeps], *args, **kwargs):
            start_time = time.time()
            tool_name = bound_tool_func.__name__
            run_id = correlation_id.get() or "unknown-run"
            input_summary = self._build_input_summary(ctx, bound_tool_func, tool_name, run_id, args, kwargs)

            await ctx.deps.emit_tool_event(
                run_id=run_id,
                tool_name=tool_name,
                phase="start",
                input=input_summary,
            )

            try:
                raw_result = await bound_tool_func(ctx, *args, **kwargs)
                result = build_tool_success_result(tool_name, raw_result)
                await ctx.deps.emit_tool_event(
                    run_id=run_id,
                    tool_name=tool_name,
                    phase="complete",
                    duration_ms=self._duration_ms(start_time),
                )
                return result
            except RetryableToolError as e:
                await ctx.deps.emit_tool_event(
                    run_id=run_id,
                    tool_name=tool_name,
                    phase="error",
                    duration_ms=self._duration_ms(start_time),
                )
                if getattr(ctx, "last_attempt", False):
                    logger.warning(
                        f"Soft-failing retryable tool error from {tool_name} "
                        f"on last attempt for session {ctx.deps.session_id}: {e}"
                    )
                    return build_tool_error_result(
                        tool_name,
                        message=str(e),
                        error_type=e.error_type,
                        retryable=False,
                        summary=f"{tool_name} failed after exhausting retries.",
                    )
                raise ModelRetry(str(e)) from e
            except ModelRetry as e:
                await ctx.deps.emit_tool_event(
                    run_id=run_id,
                    tool_name=tool_name,
                    phase="error",
                    duration_ms=self._duration_ms(start_time),
                )
                if getattr(ctx, "last_attempt", False):
                    logger.warning(
                        f"Soft-failing tool {tool_name} after retry exhaustion "
                        f"for session {ctx.deps.session_id}: {e}"
                    )
                    return build_tool_error_result(
                        tool_name,
                        message=str(e),
                        error_type="model_retry_exhausted",
                        retryable=False,
                        summary=f"{tool_name} failed after exhausting retries.",
                    )
                raise
            except Exception as e:
                await ctx.deps.emit_tool_event(
                    run_id=run_id,
                    tool_name=tool_name,
                    phase="error",
                    duration_ms=self._duration_ms(start_time),
                )
                logger.exception(f"Tool {tool_name} failed unexpectedly in session {ctx.deps.session_id}")
                return build_tool_error_result(
                    tool_name,
                    message=str(e),
                    error_type=type(e).__name__,
                    retryable=False,
                    summary=f"{tool_name} failed due to an unexpected error.",
                )

        return wrapped_tool

    @staticmethod
    def _duration_ms(start_time: float) -> int:
        return int((time.time() - start_time) * 1000)

    def _build_input_summary(
        self,
        ctx: RunContext[AgentDeps],
        bound_tool_func: ToolFunction,
        tool_name: str,
        run_id: str,
        args: tuple[object, ...],
        kwargs: dict[str, object],
    ) -> dict[str, object]:
        input_summary: dict[str, object] = {}
        try:
            signature = inspect.signature(bound_tool_func)
            bound_args = signature.bind_partial(ctx, *args, **kwargs)
            bound_args.apply_defaults()
            merged_args = {
                name: value for name, value in bound_args.arguments.items() if name != "ctx"
            }

            for key, value in merged_args.items():
                input_summary[key] = summarize_tool_input_value(key, value)

            self._replace_file_input_with_resolved_path(ctx, tool_name, run_id, merged_args, input_summary)

            raw_input = json.dumps(input_summary, default=str)
            if len(raw_input) > 2000:
                preserved_keys = ("url", "path", "command", "title", "skill_name")
                input_summary = {
                    key: value for key, value in input_summary.items() if key in preserved_keys
                }
                input_summary["_truncated"] = True
                input_summary["_size"] = len(raw_input)
        except Exception as e:
            logger.exception(f"failed to build event json:{e}")
            input_summary = {"_serialization_error": True}

        return input_summary

    @staticmethod
    def _replace_file_input_with_resolved_path(
        ctx: RunContext[AgentDeps],
        tool_name: str,
        run_id: str,
        merged_args: dict[str, object],
        input_summary: dict[str, object],
    ) -> None:
        raw_path_value: object = None
        if tool_name in {"read_file", "write_file"}:
            raw_path_value = merged_args.get("file_path")
        elif tool_name == "list_files":
            raw_path_value = merged_args.get("directory", ".")

        if not isinstance(raw_path_value, str):
            return

        raw_path = raw_path_value
        try:
            if tool_name in {"read_file", "list_files"}:
                resolved_path = FileToolkit.resolve_read_path(
                    ctx.deps,
                    ctx.deps.session_id,
                    raw_path,
                    ctx.deps.skill_name,
                )
            else:
                resolved_path = FileToolkit.resolve_session_path(
                    ctx.deps,
                    ctx.deps.session_id,
                    raw_path,
                )
            input_summary.pop("file_path", None)
            input_summary.pop("directory", None)
            input_summary["path"] = str(resolved_path)
        except Exception as e:
            logger.exception({
                "message": {
                    "event": "tool_input_path_resolution_failed",
                    "run_id": run_id,
                    "session_id": ctx.deps.session_id,
                    "skill_name": ctx.deps.skill_name,
                    "tool_name": tool_name,
                    "raw_path": raw_path,
                    "error": str(e),
                }
            })
