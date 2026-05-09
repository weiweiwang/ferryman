from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable, Optional

from app.core.config import Settings
from app.core.db import init_db

if TYPE_CHECKING:
    from app.core.deps import AgentDeps
    from app.models.events import FerrymanEventEnvelope

logger = logging.getLogger(__name__)


class FerrymanRuntime:
    """Composition root for the Ferryman local sidecar runtime."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._workspace_root: Path = settings.root_dir / "workspaces"
        self._init_directories(settings)
        init_db()
        settings.seed_runtime_defaults()
        self._init_managers(settings)

    def _init_managers(self, settings: Settings) -> None:
        from app.core.agent_manager import AgentManager
        from app.core.browser_manager import BrowserManager
        from app.core.context_manager import ContextManager
        from app.core.model_manager import ModelManager
        from app.core.prompt_builder import PromptBuilder
        from app.core.run_registry import RunRegistry
        from app.core.schedule_manager import ScheduleManager
        from app.core.session_manager import SessionManager
        from app.core.skill_manager import SkillManager
        from app.core.task_manager import TaskManager
        from app.core.tool_manager import ToolManager

        self.model_manager = ModelManager(settings=settings)
        self.skill_manager = SkillManager(settings=settings)
        self.task_manager = TaskManager()
        self.session_manager = SessionManager()
        self.tool_manager = ToolManager()
        self.schedule_manager = ScheduleManager(self, settings)
        self.browser_manager = BrowserManager(settings=settings, get_session_workspace=self.get_session_workspace)
        self.prompt_builder = PromptBuilder(
            settings=settings,
            skill_manager=self.skill_manager,
            get_session_workspace=self.get_session_workspace,
        )
        self.context_manager = ContextManager(
            settings=settings,
            model_manager=self.model_manager,
            session_manager=self.session_manager,
            build_system_prompt=self.prompt_builder.build_system_prompt,
        )
        self.agent_manager = AgentManager(
            settings=settings,
            model_manager=self.model_manager,
            tool_manager=self.tool_manager,
            prompt_builder=self.prompt_builder,
            session_manager=self.session_manager,
            context_manager=self.context_manager,
        )
        self.run_registry = RunRegistry(self)

    @staticmethod
    def _init_directories(settings: Settings) -> None:
        sub_dirs = [
            settings.user_dir / "reports",
            settings.user_dir / "tasks",
            settings.user_dir / "logs",
            settings.user_dir / "workspaces",
            settings.browser_dir,
            settings.user_skills_dir,
        ]

        for sd in sub_dirs:
            if not sd.exists():
                sd.mkdir(parents=True, exist_ok=True)
                logger.info(f"Created directory: {sd}")

    def get_session_workspace(self, session_id: str) -> Path:
        session_dir = self._workspace_root / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir

    def create_agent_deps(
        self,
        session_id: str,
        *,
        skill_name: Optional[str] = None,
        emit_event_cb: Optional[Callable[["FerrymanEventEnvelope"], Awaitable[None]]] = None,
    ) -> "AgentDeps":
        from app.core.deps import AgentDeps

        return AgentDeps(
            session_id=session_id,
            settings=self.settings,
            workspace_dir=self.get_session_workspace(session_id),
            agent_manager=self.agent_manager,
            browser_manager=self.browser_manager,
            prompt_builder=self.prompt_builder,
            skill_manager=self.skill_manager,
            task_manager=self.task_manager,
            skill_name=skill_name,
            emit_event_cb=emit_event_cb,
            schedule_manager=self.schedule_manager,
        )

    async def run_master_agent(
        self,
        instruction: str,
        session_id: str,
        *,
        run_id: str,
        emit_event_cb: Optional[Callable[["FerrymanEventEnvelope"], Awaitable[None]]] = None,
    ) -> dict[str, object]:
        deps = self.create_agent_deps(session_id=session_id, emit_event_cb=emit_event_cb)
        return await self.agent_manager.run_master_agent(
            instruction=instruction,
            session_id=session_id,
            run_id=run_id,
            deps=deps,
        )
