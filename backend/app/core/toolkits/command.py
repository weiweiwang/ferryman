import asyncio
import json
import sys
from pathlib import Path
from typing import Annotated

from pydantic import BeforeValidator
from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.tools import RunContext

from app.core.deps import AgentDeps, get_skill_manager, get_workspace
from app.core.toolkits.base import Toolkit


def _coerce_args(v: object) -> list[str] | None:
    """Coerce a JSON-encoded argument list into `list[str]`."""
    if v is None or isinstance(v, list):
        return v
    if isinstance(v, str):
        try:
            return json.loads(v)
        except (json.JSONDecodeError, ValueError):
            return v
    return v


class CommandToolkit(Toolkit):
    """Run scripts from the current skill's scripts directory."""

    @staticmethod
    def get_tools():
        return [CommandToolkit.run_skill_script]

    @staticmethod
    def _resolve_script_path(ctx: RunContext[AgentDeps], script_name: str) -> Path:
        """Resolve a script path under the current skill's `scripts/` directory."""
        skill_name = ctx.deps.skill_name
        if not skill_name:
            raise ModelRetry("run_skill_script is only available inside a skill execution context.")

        skill = get_skill_manager(ctx.deps).skills.get(skill_name)
        if not skill:
            raise ModelRetry(f"Current skill '{skill_name}' is not registered.")

        scripts_dir = skill.path / "scripts"
        candidate = (scripts_dir / script_name).resolve()
        try:
            candidate.relative_to(scripts_dir.resolve())
        except ValueError as exc:
            raise ModelRetry(f"Script path escapes skill scripts directory: {script_name}") from exc

        if not candidate.exists():
            raise ModelRetry(f"Script not found: {script_name}")
        if not candidate.is_file():
            raise ModelRetry(f"Script is not a file: {script_name}")
        return candidate

    @staticmethod
    def _build_command(script_path: Path, args: list[str]) -> list[str]:
        """Build the subprocess command for a script based on its file type."""
        if script_path.suffix == ".py":
            if getattr(sys, "frozen", False):
                return [sys.executable, "--run-python-script", str(script_path), *args]
            return [sys.executable, str(script_path), *args]
        if script_path.suffix == ".sh":
            return ["/bin/bash", str(script_path), *args]
        return [str(script_path), *args]

    @staticmethod
    async def run_skill_script(
        ctx: RunContext[AgentDeps],
        script_name: str,
        args: Annotated[list[str] | None, BeforeValidator(_coerce_args)] = None,
        timeout_ms: int = 10000,
    ) -> dict:
        """Run a script from the current skill's `scripts/` directory.

        The script runs with the current session workspace as its working
        directory. Returns a structured result with command, exit code,
        timeout status, stdout, and stderr.
        """
        resolved_args = args or []
        script_path = CommandToolkit._resolve_script_path(ctx, script_name)
        workspace_dir = get_workspace(ctx.deps)
        command = CommandToolkit._build_command(script_path, resolved_args)

        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(workspace_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        timed_out = False
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=max(timeout_ms, 1) / 1000,
            )
        except asyncio.TimeoutError:
            timed_out = True
            process.kill()
            stdout, stderr = await process.communicate()

        result = {
            "ok": process.returncode == 0 and not timed_out,
            "script_name": script_name,
            "command": command,
            "cwd": str(workspace_dir),
            "exit_code": process.returncode,
            "timed_out": timed_out,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
        }
        return result
