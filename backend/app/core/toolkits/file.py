from pathlib import Path
import logging

from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.tools import RunContext

from app.core.deps import AgentDeps
from app.core.toolkits.base import Toolkit

logger = logging.getLogger(__name__)


class FileToolkit(Toolkit):
    """Read and write files for the current session.

    Writes stay inside the session workspace. Reads may also access the current
    skill's bundled resources.
    """

    SCRIPT_SUFFIXES = {
        ".bash",
        ".bat",
        ".cjs",
        ".cmd",
        ".fish",
        ".js",
        ".jsx",
        ".lua",
        ".mjs",
        ".php",
        ".pl",
        ".ps1",
        ".py",
        ".pyw",
        ".r",
        ".rb",
        ".sh",
        ".ts",
        ".tsx",
        ".zsh",
    }

    @staticmethod
    def get_tools():
        return [
            FileToolkit.read_file,
            FileToolkit.write_file,
            FileToolkit.list_files,
        ]

    @staticmethod
    def _normalize_relative_path(file_path: str) -> str:
        """Normalize an agent-supplied relative path."""
        file_path = file_path.strip()
        for prefix in ("./",):
            file_path = file_path.removeprefix(prefix)
        return file_path or "."

    @staticmethod
    def _validate_skill_resource_path(file_path: str) -> str:
        """Return a normalized path that must stay relative to the current skill."""
        normalized = FileToolkit._normalize_relative_path(file_path)
        candidate = Path(normalized)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError(f"Invalid current skill resource path: {file_path}")
        return normalized

    @staticmethod
    def resolve_session_path(tool_context: AgentDeps, raw_path: str) -> Path:
        """Resolve a path inside the current session workspace.

        Raises ValueError if the path escapes the workspace.
        """
        workspace_dir = Path(tool_context.workspace_dir).resolve()
        normalized = FileToolkit._normalize_relative_path(raw_path)
        candidate = (workspace_dir / normalized).resolve()

        try:
            candidate.relative_to(workspace_dir)
        except ValueError as exc:
            raise ValueError(f"Path escapes session workspace: {raw_path}") from exc

        return candidate

    @staticmethod
    def _is_script_write(path: Path, content: str) -> bool:
        """Return whether a write target looks like a runnable script."""
        if path.suffix.lower() in FileToolkit.SCRIPT_SUFFIXES:
            return True
        return content.startswith("#!")

    @staticmethod
    def _resolve_current_skill_resource_path(
        tool_context: AgentDeps,
        skill_name: str,
        raw_path: str,
    ) -> Path:
        """Resolve a read-only path inside the current skill directory."""
        skill = tool_context.skill_manager.skills.get(skill_name)
        if not skill:
            raise ValueError(f"Current skill '{skill_name}' is not registered.")

        skill_dir = skill.path.resolve()
        normalized = FileToolkit._normalize_relative_path(raw_path)
        raw_candidate = Path(normalized)
        candidate = raw_candidate.resolve() if raw_candidate.is_absolute() else (skill_dir / normalized).resolve()

        try:
            candidate.relative_to(skill_dir)
        except ValueError as exc:
            raise ValueError(f"Path escapes current skill directory: {raw_path}") from exc

        return candidate

    @staticmethod
    def resolve_current_skill_resource_path(
        tool_context: AgentDeps,
        raw_path: str,
        skill_name: str | None,
    ) -> Path:
        """Resolve a read-only relative path inside the current skill directory."""
        if not skill_name:
            raise ValueError("read_skill_file is only available during skill execution.")
        normalized = FileToolkit._validate_skill_resource_path(raw_path)
        return FileToolkit._resolve_current_skill_resource_path(tool_context, skill_name, normalized)

    @staticmethod
    def _list_current_skill_readable_files(
        tool_context: AgentDeps,
        skill_name: str,
    ) -> dict[str, list[str]]:
        skill = tool_context.skill_manager.skills.get(skill_name)
        if not skill:
            return {}
        skill_dir = skill.path.resolve()
        available: dict[str, list[str]] = {
            "assets": [],
            "references": [],
            "scripts": [],
            "other": [],
        }
        for item in skill_dir.rglob("*"):
            if not item.is_file() or item.name == "SKILL.md":
                continue
            rel = str(item.relative_to(skill_dir))
            if rel.startswith("assets/"):
                available["assets"].append(rel)
            elif rel.startswith("references/"):
                available["references"].append(rel)
            elif rel.startswith("scripts/"):
                available["scripts"].append(rel)
            else:
                available["other"].append(rel)
        return {key: sorted(value) for key, value in available.items() if value}

    @staticmethod
    def resolve_read_path(
        tool_context: AgentDeps,
        session_id: str,
        raw_path: str,
        skill_name: str | None = None,
    ) -> Path:
        """Resolve a readable path for agent tools.

        Prefers the session workspace. During skill execution, falls back to the
        current skill's bundled resources for read-only access.
        """
        try:
            workspace_path = FileToolkit.resolve_session_path(tool_context, raw_path)
        except ValueError:
            logger.debug({
                "message": {
                    "event": "file_read_workspace_rejected",
                    "session_id": session_id,
                    "skill_name": skill_name,
                    "raw_path": raw_path,
                }
            })
            if skill_name:
                skill_path = FileToolkit._resolve_current_skill_resource_path(tool_context, skill_name, raw_path)
                logger.debug({
                    "message": {
                        "event": "file_read_skill_fallback",
                        "session_id": session_id,
                        "skill_name": skill_name,
                        "raw_path": raw_path,
                        "resolved_path": str(skill_path),
                    }
                })
                return skill_path
            raise

        if not skill_name or workspace_path.exists():
            return workspace_path

        try:
            skill_path = FileToolkit._resolve_current_skill_resource_path(tool_context, skill_name, raw_path)
        except ValueError:
            logger.debug({
                "message": {
                    "event": "file_read_skill_fallback_rejected",
                    "session_id": session_id,
                    "skill_name": skill_name,
                    "raw_path": raw_path,
                    "workspace_path": str(workspace_path),
                }
            })
            return workspace_path

        logger.debug({
            "message": {
                "event": "file_read_skill_fallback_exists_check",
                "session_id": session_id,
                "skill_name": skill_name,
                "raw_path": raw_path,
                "workspace_path": str(workspace_path),
                "skill_path": str(skill_path),
                "workspace_exists": workspace_path.exists(),
                "skill_exists": skill_path.exists(),
            }
        })
        return skill_path if skill_path.exists() else workspace_path

    @staticmethod
    async def read_file(ctx: RunContext[AgentDeps], file_path: str) -> str:
        """Read a file from the session workspace or current skill resources.

        Raises `ModelRetry` if the file does not exist.
        """
        try:
            path = FileToolkit.resolve_read_path(
                ctx.deps,
                ctx.deps.session_id,
                file_path,
                ctx.deps.skill_name,
            )
        except ValueError as exc:
            raise ModelRetry(
                "Invalid path: use a relative path. "
                "Reads may only use the session workspace or current skill resources; "
                "writes may only use the session workspace. "
                f"Got: {file_path}"
            ) from exc
        else:
            if not path.exists():
                raise ModelRetry(f"File not found: {file_path}")
            return path.read_text(encoding="utf-8")

    @staticmethod
    async def read_skill_file(ctx: RunContext[AgentDeps], file_path: str) -> str:
        """Read a file from the current skill's read-only resources.

        `file_path` must be relative to the current skill directory, such as
        `assets/report-template.md` or `references/case-rubric.md`.
        """
        try:
            path = FileToolkit.resolve_current_skill_resource_path(
                ctx.deps,
                file_path,
                ctx.deps.skill_name,
            )
        except ValueError as exc:
            raise ModelRetry(
                "Invalid skill resource path: use a relative path inside the current "
                "skill directory. "
                f"Got: {file_path}"
            ) from exc
        else:
            if not path.exists():
                available = {}
                if ctx.deps.skill_name:
                    available = FileToolkit._list_current_skill_readable_files(
                        ctx.deps,
                        ctx.deps.skill_name,
                    )
                hint = f" Available files: {available}" if available else ""
                raise ModelRetry(f"Skill file not found: {file_path}.{hint}")
            return path.read_text(encoding="utf-8")

    @staticmethod
    async def write_file(ctx: RunContext[AgentDeps], file_path: str, content: str) -> str:
        """Write a UTF-8 file inside the session workspace.

        Creates parent directories as needed. Raises `ModelRetry` if the path
        escapes the workspace.
        """
        normalized = FileToolkit._normalize_relative_path(file_path)
        try:
            path = FileToolkit.resolve_session_path(ctx.deps, file_path)
        except ValueError as exc:
            raise ModelRetry(
                "Invalid path: use a relative path. "
                "Reads may only use the session workspace or current skill resources; "
                "writes may only use the session workspace. "
                f"Got: {file_path}"
            ) from exc
        else:
            if ctx.deps.skill_name and FileToolkit._is_script_write(path, content):
                raise ModelRetry(
                    "Script file creation is not allowed while executing a skill. "
                    "Use the skill's bundled scripts via run_skill_script, or write "
                    "only final deliverables such as .md, .csv, .json, or .txt files."
                )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return f"Successfully wrote {len(content)} characters to {normalized}"

    @staticmethod
    async def list_files(ctx: RunContext[AgentDeps], directory: str = ".") -> str:
        """List entries in the session workspace or current skill resources.

        Raises `ModelRetry` if the directory does not exist.
        """
        try:
            path = FileToolkit.resolve_read_path(
                ctx.deps,
                ctx.deps.session_id,
                directory,
                ctx.deps.skill_name,
            )
        except ValueError as exc:
            raise ModelRetry(
                "Invalid path: use a relative path. "
                "Reads may only use the session workspace or current skill resources; "
                "writes may only use the session workspace. "
                f"Got: {directory}"
            ) from exc
        else:
            if not path.exists():
                raise ModelRetry(f"Directory not found: {directory}")
            entries = sorted(path.iterdir())
            return "\n".join(
                f"{'[DIR] ' if e.is_dir() else ''}{e.name}" for e in entries
            )
