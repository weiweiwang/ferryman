from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable, Optional
from uuid import uuid4

if TYPE_CHECKING:
    from app.core.agent_manager import AgentManager
    from app.core.browser_manager import BrowserManager
    from app.core.config import Settings
    from app.core.prompt_builder import PromptBuilder
    from app.core.schedule_manager import ScheduleManager
    from app.core.skill_manager import SkillManager
    from app.core.task_manager import TaskManager
    from app.models.events import FerrymanEventEnvelope

logger = logging.getLogger(__name__)


@dataclass
class AgentDeps:
    session_id: str
    settings: "Settings"
    workspace_dir: Path
    agent_manager: "AgentManager"
    browser_manager: "BrowserManager"
    prompt_builder: "PromptBuilder"
    skill_manager: "SkillManager"
    task_manager: "TaskManager"
    skill_name: Optional[str] = None
    emit_event_cb: Optional[Callable[["FerrymanEventEnvelope"], Awaitable[None]]] = None
    schedule_manager: "ScheduleManager | None" = None
    _tool_event_seq: int = field(default=0, init=False, repr=False)

    async def emit_tool_event(self, run_id: str, tool_name: str, phase: str, **kwargs: object) -> None:
        if self.emit_event_cb:
            from app.models.events import FerrymanEventEnvelope, EventNamespace, ToolActivityPayload, ToolPhase
            self._tool_event_seq += 1
            event_id = uuid4().hex
            payload = ToolActivityPayload(
                run_id=run_id,
                event_id=event_id,
                seq=self._tool_event_seq,
                tool_name=tool_name,
                phase=ToolPhase(phase),
                **kwargs
            )
            event = FerrymanEventEnvelope(
                namespace=EventNamespace.AGENT,
                event="tool_activity",
                session_id=self.session_id,
                payload=payload
            )
            logger.debug({
                "message": {
                    "event": "tool_activity_emit",
                    "session_id": self.session_id,
                    "run_id": run_id,
                    "skill_name": self.skill_name,
                    "tool_name": tool_name,
                    "phase": phase,
                    "event_id": event_id,
                    "seq": self._tool_event_seq,
                }
            })
            await self.emit_event_cb(event)


def get_agent_manager(deps: AgentDeps) -> "AgentManager":
    return deps.agent_manager


def get_browser_manager(deps: AgentDeps) -> "BrowserManager":
    return deps.browser_manager


def get_prompt_builder(deps: AgentDeps) -> "PromptBuilder":
    return deps.prompt_builder


def get_skill_manager(deps: AgentDeps) -> "SkillManager":
    return deps.skill_manager


def get_task_manager(deps: AgentDeps) -> "TaskManager":
    return deps.task_manager


def get_schedule_manager(deps: AgentDeps) -> "ScheduleManager | None":
    return deps.schedule_manager


def get_workspace(deps: AgentDeps) -> Path:
    return deps.workspace_dir


def get_setting_value(deps: AgentDeps, key: str, default: object = None) -> object:
    return deps.settings.get(key, default)


def get_resend_default_from(deps: AgentDeps) -> str:
    return deps.settings.resend_default_from


def get_user_skills_dir(deps: AgentDeps) -> Path:
    return deps.settings.user_skills_dir
