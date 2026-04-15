import json
import logging
import shutil
from pathlib import Path

from pydantic_ai.tools import RunContext
from pydantic_ai.usage import UsageLimits

from app.core.deps import AgentDeps
from app.core.utils import load_skill_from_directory

logger = logging.getLogger(__name__)


class SkillToolkit:
    """Delegate work to installed skills and publish draft skills."""

    @staticmethod
    def get_tools():
        return [SkillToolkit.run_skill, SkillToolkit.publish_skill]

    @staticmethod
    async def run_skill(
        ctx: RunContext[AgentDeps],
        skill_name: str,
        instruction: str,
    ) -> str:
        """Run an installed skill with the given instruction.

        `skill_name` must exist in the registered skill list. Returns the
        skill's output text. Raises `RuntimeError` if the skill run fails.
        """
        kernel = ctx.deps.kernel
        session_id = ctx.deps.session_id
        
        if skill_name not in kernel.skills:
            raise ValueError(f"Skill '{skill_name}' not found.")

        workspace = kernel.get_session_workspace(session_id)

        logger.info(f"Executing skill '{skill_name}' in {workspace}")
        skill_agent = kernel.build_skill_agent(skill_name)

        try:
            # IMPORTANT: Pass ctx.usage to sub-agent so request/token accounting
            # and request budgeting are shared across the master agent and delegated skills.
            request_limit = kernel.get_setting("system.llm.request_limit", 100)
            augmented_instruction = kernel.build_runtime_augmented_instruction(instruction, session_id)
            skill_deps = AgentDeps(
                kernel=kernel,
                session_id=session_id,
                skill_name=skill_name,
                emit_event_cb=ctx.deps.emit_event_cb,
            )
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug({
                    "message": {
                        "session_id": session_id,
                        "event": "llm_request",
                        "scope": "skill",
                        "skill": skill_name,
                        "input": augmented_instruction,
                        "request_limit": request_limit,
                    }
                })

            result = await skill_agent.run(
                augmented_instruction,
                deps=skill_deps,
                usage=ctx.usage,
                usage_limits=UsageLimits(request_limit=request_limit),
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
                        "event": "llm_response",
                        "scope": "skill",
                        "skill": skill_name,
                        "output": str(result.output),
                        "usage": usage_data,
                    }
                })

            return str(result.output)
        except Exception as e:
            logger.exception({
                "message": {
                    "session_id": session_id,
                    "event": "agent_run",
                    "scope": "skill",
                    "status": "failed",
                    "skill": skill_name,
                    "input": instruction,
                    "error": str(e),
                }
            })
            raise RuntimeError(f"Skill '{skill_name}' failed: {e}") from e

    @staticmethod
    async def publish_skill(
        ctx: RunContext[AgentDeps],
        draft_path: str,
    ) -> str:
        """Publish a draft skill from the current session workspace.

        The draft directory must stay inside the workspace and contain a valid
        `SKILL.md`. Copies the directory into the user skills folder and returns
        a JSON result string.
        """
        kernel = ctx.deps.kernel
        workspace_dir = kernel.get_session_workspace(ctx.deps.session_id).resolve()
        normalized = draft_path.strip()
        if not normalized:
            raise RuntimeError("draft_path cannot be empty.")

        source_path = (workspace_dir / normalized).resolve() if not Path(normalized).is_absolute() else Path(normalized).resolve()
        try:
            source_path.relative_to(workspace_dir)
        except ValueError as exc:
            raise RuntimeError("draft_path must be inside the current session workspace.") from exc

        if not source_path.exists():
            raise RuntimeError(f"Draft skill directory not found: {draft_path}")
        if not source_path.is_dir():
            raise RuntimeError(f"Draft path is not a directory: {draft_path}")

        skill = load_skill_from_directory(source_path)
        if not skill:
            raise RuntimeError(f"Draft directory is not a valid skill: {draft_path}")

        destination_dir = kernel._settings.user_skills_dir.resolve()
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination_path = destination_dir / skill.name
        if destination_path.exists():
            raise RuntimeError(f"Skill '{skill.name}' already exists in user skills.")

        shutil.copytree(str(source_path), str(destination_path))
        kernel.scan_skills()

        return json.dumps(
            {
                "ok": True,
                "skill_name": skill.name,
                "source_path": str(source_path),
                "destination_path": str(destination_path),
                "registered": skill.name in kernel.skills,
            },
            ensure_ascii=False,
        )
