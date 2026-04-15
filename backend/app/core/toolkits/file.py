from pathlib import Path

from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.tools import RunContext

from app.core.deps import AgentDeps

class FileToolkit:
    """Read and write files for the current session.

    Writes stay inside the session workspace. Reads may also access the current
    skill's bundled resources.
    """

    @staticmethod
    def get_tools():
        return [FileToolkit.read_file, FileToolkit.write_file, FileToolkit.list_files]

    @staticmethod
    def _normalize_workspace_path(file_path: str) -> str:
        """Normalize an agent-supplied relative path for workspace use."""
        file_path = file_path.strip()
        for prefix in ("./",):
            file_path = file_path.removeprefix(prefix)
        return file_path or "."

    @staticmethod
    def resolve_session_path(kernel, session_id: str, raw_path: str) -> Path:
        """Resolve a path inside the current session workspace.

        Raises ValueError if the path escapes the workspace.
        """
        workspace_dir = kernel.get_session_workspace(session_id).resolve()
        normalized = FileToolkit._normalize_workspace_path(raw_path)
        candidate = (workspace_dir / normalized).resolve()

        try:
            candidate.relative_to(workspace_dir)
        except ValueError as exc:
            raise ValueError(f"Path escapes session workspace: {raw_path}") from exc

        return candidate

    @staticmethod
    def _resolve_current_skill_resource_path(kernel, skill_name: str, raw_path: str) -> Path:
        """Resolve a read-only path inside the current skill directory."""
        skill = kernel.skills.get(skill_name)
        if not skill:
            raise ValueError(f"Current skill '{skill_name}' is not registered.")

        skill_dir = skill.path.resolve()
        normalized = FileToolkit._normalize_workspace_path(raw_path)
        raw_candidate = Path(normalized)
        candidate = raw_candidate.resolve() if raw_candidate.is_absolute() else (skill_dir / normalized).resolve()

        try:
            candidate.relative_to(skill_dir)
        except ValueError as exc:
            raise ValueError(f"Path escapes current skill directory: {raw_path}") from exc

        return candidate

    @staticmethod
    def resolve_read_path(kernel, session_id: str, raw_path: str, skill_name: str | None = None) -> Path:
        """Resolve a readable path for agent tools.

        Prefers the session workspace. During skill execution, falls back to the
        current skill's bundled resources for read-only access.
        """
        try:
            workspace_path = FileToolkit.resolve_session_path(kernel, session_id, raw_path)
        except ValueError:
            if skill_name:
                return FileToolkit._resolve_current_skill_resource_path(kernel, skill_name, raw_path)
            raise

        if not skill_name or workspace_path.exists():
            return workspace_path

        try:
            skill_path = FileToolkit._resolve_current_skill_resource_path(kernel, skill_name, raw_path)
        except ValueError:
            return workspace_path

        return skill_path if skill_path.exists() else workspace_path

    @staticmethod
    async def read_file(ctx: RunContext[AgentDeps], file_path: str) -> str:
        """Read a file from the session workspace or current skill resources.

        Raises `ModelRetry` if the file does not exist.
        """
        p = FileToolkit.resolve_read_path(
            ctx.deps.kernel,
            ctx.deps.session_id,
            file_path,
            ctx.deps.skill_name,
        )
        if not p.exists():
            raise ModelRetry(f"File not found: {file_path}")
        return p.read_text(encoding="utf-8")

    @staticmethod
    async def write_file(ctx: RunContext[AgentDeps], file_path: str, content: str) -> str:
        """Write a UTF-8 file inside the session workspace.

        Creates parent directories as needed. Raises ValueError if the path
        escapes the workspace.
        """
        normalized = FileToolkit._normalize_workspace_path(file_path)
        full_path = FileToolkit.resolve_session_path(ctx.deps.kernel, ctx.deps.session_id, file_path)
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
        return f"Successfully wrote {len(content)} characters to {normalized}"

    @staticmethod
    async def list_files(ctx: RunContext[AgentDeps], directory: str = ".") -> str:
        """List entries in the session workspace or current skill resources.

        Raises `ModelRetry` if the directory does not exist.
        """
        p = FileToolkit.resolve_read_path(
            ctx.deps.kernel,
            ctx.deps.session_id,
            directory,
            ctx.deps.skill_name,
        )
        if not p.exists():
            raise ModelRetry(f"Directory not found: {directory}")
        entries = sorted(p.iterdir())
        return "\n".join(
            f"{'[DIR] ' if e.is_dir() else ''}{e.name}" for e in entries
        )
