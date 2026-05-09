from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Sequence
from functools import wraps
from typing import Any

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
            tool_name = bound_tool_func.__name__

            try:
                raw_result = await bound_tool_func(ctx, *args, **kwargs)
                return build_tool_success_result(tool_name, raw_result)
            except RetryableToolError as e:
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
                logger.exception(f"Tool {tool_name} failed unexpectedly in session {ctx.deps.session_id}")
                return build_tool_error_result(
                    tool_name,
                    message=str(e),
                    error_type=type(e).__name__,
                    retryable=False,
                    summary=f"{tool_name} failed due to an unexpected error.",
                )

        return wrapped_tool
