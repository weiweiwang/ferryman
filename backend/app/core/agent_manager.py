from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from pydantic_ai.agent import Agent
from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelResponse
from pydantic_ai.usage import UsageLimits

from app.core.agent_event_stream import build_agent_event_stream_handler
from app.core.deps import AgentDeps
from app.core.model_routing import ModelRouter, ModelUsageTracker, RoutingContext, RoutingModel

if TYPE_CHECKING:
    from app.core.config import Settings
    from app.core.context_manager import ContextManager
    from app.core.model_manager import ModelManager
    from app.core.model_pricing import ModelPricingService
    from app.core.prompt_builder import PromptBuilder
    from app.core.session_manager import SessionManager
    from app.core.tool_manager import ToolManager

logger = logging.getLogger(__name__)


class AgentManager:
    """Build and run Ferryman agents."""

    def __init__(
        self,
        *,
        settings: "Settings",
        model_manager: "ModelManager",
        tool_manager: "ToolManager",
        prompt_builder: "PromptBuilder",
        session_manager: "SessionManager",
        context_manager: "ContextManager",
        model_pricing_service: "ModelPricingService | None" = None,
    ) -> None:
        self._settings = settings
        self._model_manager = model_manager
        if model_pricing_service is None:
            from app.core.model_pricing import ModelPricingService
            model_pricing_service = ModelPricingService(enabled=False)
        self._model_pricing_service = model_pricing_service
        self._tool_manager = tool_manager
        self._prompt_builder = prompt_builder
        self._session_manager = session_manager
        self._context_manager = context_manager
        self._model_router = ModelRouter(model_manager)

    def build_agent(self, system_prompt: str, *, routing_context: RoutingContext | None = None) -> Agent:
        model = RoutingModel(
            model_manager=self._model_manager,
            router=self._model_router,
            routing_context=routing_context or RoutingContext(),
        )
        agent: Agent = Agent(
            model=model,
            system_prompt=system_prompt,
            deps_type=AgentDeps,
            capabilities=self._tool_manager.get_capabilities(),
        )
        return agent

    def build_skill_agent(
        self,
        skill_name: str,
        *,
        session_id: str | None = None,
        run_id: str | None = None,
        usage_tracker: ModelUsageTracker | None = None,
    ) -> Agent:
        """Create a skill-scoped agent with the skill instructions injected."""
        agent = self.build_agent(
            self._prompt_builder.build_skill_system_prompt(skill_name),
            routing_context=RoutingContext(
                session_id=session_id,
                run_id=run_id,
                scope="skill",
                skill_name=skill_name,
                usage_tracker=usage_tracker,
            ),
        )
        self._tool_manager.register_skill_toolkits(agent)
        return agent

    def build_master_agent(
        self,
        session_id: str,
        *,
        run_id: str | None = None,
        usage_tracker: ModelUsageTracker | None = None,
    ) -> Agent:
        agent = self.build_agent(
            self._prompt_builder.build_system_prompt(session_id),
            routing_context=RoutingContext(
                session_id=session_id,
                run_id=run_id,
                scope="master",
                usage_tracker=usage_tracker,
            ),
        )
        self._tool_manager.register_master_toolkits(agent)
        return agent

    def _get_request_limit(self) -> int:
        value = self._settings.get("system.llm.request_limit", self._settings.llm_request_limit)
        if isinstance(value, int):
            return value
        try:
            return int(str(value))
        except (TypeError, ValueError):
            return self._settings.llm_request_limit

    async def run_master_agent(
        self,
        instruction: str,
        session_id: str,
        *,
        run_id: str,
        deps: AgentDeps,
    ) -> dict[str, object]:
        """Run the master agent for one user instruction."""
        logger.info({
            "message": {
                "event": "agent_run_start",
                "session_id": session_id,
                "run_id": run_id,
                "instruction": instruction,
                "instruction_length": len(instruction),
            }
        })
        user_message_id: Optional[str] = None
        usage_tracker = ModelUsageTracker()
        deps.model_usage_tracker = usage_tracker

        try:
            self._session_manager.ensure_session(session_id)

            history = self._context_manager.get_session_messages(session_id)

            user_msg = self._session_manager.append_user_message(
                session_id=session_id,
                content=instruction,
                run_id=run_id,
                token_estimate=self._context_manager.estimate_text_tokens(instruction),
            )
            user_message_id = user_msg.id

            master_agent = self.build_master_agent(
                session_id,
                run_id=run_id,
                usage_tracker=usage_tracker,
            )
            request_limit = self._get_request_limit()
            augmented_instruction = self._prompt_builder.build_runtime_augmented_instruction(instruction, session_id)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug({
                    "message": {
                        "session_id": session_id,
                        "run_id": run_id,
                        "event": "llm_request",
                        "scope": "master",
                        "input": augmented_instruction,
                        "message_history": ModelMessagesTypeAdapter.dump_python(history, mode="json"),
                        "history_count": len(history),
                        "request_limit": request_limit,
                    }
                })

            result = await master_agent.run(
                augmented_instruction,
                deps=deps,
                message_history=history,
                usage_limits=UsageLimits(request_limit=request_limit),
                event_stream_handler=build_agent_event_stream_handler(deps),
            )
            result_data = result.output
            response_messages = [msg for msg in result.new_messages() if isinstance(msg, ModelResponse)]
            latest_response = response_messages[-1] if response_messages else None
            serialized_response = (
                ModelMessagesTypeAdapter.dump_python([latest_response], mode="json")[0]
                if latest_response is not None
                else None
            )

            usage = result.usage()
            usage_data = {
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "total_tokens": usage.total_tokens,
            }
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug({
                    "message": {
                        "session_id": session_id,
                        "run_id": run_id,
                        "event": "llm_response",
                        "scope": "master",
                        "output": str(result_data),
                        "new_messages": ModelMessagesTypeAdapter.dump_python(result.new_messages(), mode="json"),
                        "usage": usage_data,
                    }
                })

            model_usage = usage_tracker.snapshot() if usage_tracker.has_usage() else None
            model_cost = self._model_pricing_service.calculate_cost(model_usage)
            assistant_message = self._session_manager.record_agent_run_success(
                user_message_id=user_message_id,
                session_id=session_id,
                run_id=run_id,
                content=str(result_data),
                token_estimate=self._context_manager.estimate_text_tokens(str(result_data)),
                parts=serialized_response.get("parts", []) if serialized_response else [],
                usage=usage_data,
                model={
                    "name": serialized_response.get("model_name") if serialized_response else None,
                    "provider": serialized_response.get("provider_name") if serialized_response else None,
                },
                model_usage=model_usage,
                model_cost=model_cost,
            )
            if model_usage:
                self._log_model_usage(
                    session_id=session_id,
                    run_id=run_id,
                    message_id=assistant_message.id,
                    usage=model_usage,
                    cost=model_cost,
                )

            await self._context_manager.maybe_compact_session(session_id)

            return self._build_final_payload(
                run_id=run_id,
                session_id=session_id,
                content=str(result_data),
                usage=usage_data,
                status="success",
                model_usage=model_usage,
                model_cost=model_cost,
            )

        except Exception as e:
            logger.exception(f"Master Agent failed for session {session_id}")
            error_message = str(e)
            cause_message = str(e.__cause__ or "")
            if cause_message and cause_message not in error_message:
                error_message += f"\n\nCause: {cause_message}"

            self._session_manager.record_agent_run_failure(
                user_message_id=user_message_id,
                session_id=session_id,
                run_id=run_id,
                error_message=error_message,
            )

            return self._build_final_payload(
                run_id=run_id,
                session_id=session_id,
                content=f"Run failed: {error_message}",
                usage={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                status="failed",
                error=error_message,
            )

    @staticmethod
    def _build_final_payload(
        *,
        run_id: str,
        session_id: str,
        content: str,
        usage: dict[str, int],
        status: str,
        error: str | None = None,
        model_usage: dict[str, object] | None = None,
        model_cost: dict[str, object] | None = None,
    ) -> dict[str, object]:
        from app.models.events import ChatFinalPayload, EventNamespace, FerrymanEventEnvelope

        run_metadata = {
            "id": run_id,
            "status": status,
        }
        if error is not None:
            run_metadata["error"] = error

        message_metadata: dict[str, object] = {
            "run": run_metadata,
        }
        if model_usage:
            message_metadata["usage"] = model_usage
        if model_cost:
            message_metadata["cost"] = model_cost

        payload = ChatFinalPayload(
            run_id=run_id,
            messages=[
                {
                    "role": "assistant",
                    "content": content,
                    "metadata": message_metadata,
                }
            ],
            usage=usage,
        )
        final_res = FerrymanEventEnvelope(
            namespace=EventNamespace.AGENT,
            event="chat_final",
            session_id=session_id,
            payload=payload,
        )
        return final_res.model_dump(mode="json")

    @staticmethod
    def _log_model_usage(
        *,
        session_id: str,
        run_id: str,
        message_id: str,
        usage: dict[str, object],
        cost: dict[str, object] | None,
    ) -> None:
        logger.info({
            "message": {
                "event": "model_usage",
                "session_id": session_id,
                "run_id": run_id,
                "message_id": message_id,
                "usage": usage,
                "cost": cost,
            }
        })
