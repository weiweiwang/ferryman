import yaml
import asyncio
import platform
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime, timezone

from pydantic_ai import Agent, RunContext

from app.core.config import config, get_active_model_id, get_provider_llm_config
from app.core.db import get_session
from app.models.database import Session, Message, Task, Schedule
from app.models.schemas import SkillModel, TaskStatus, TaskModel, ScheduleModel
from app.core.prompts import OS_PROMPT
from app.core.utils import load_skill_from_directory

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# FerrymanKernel – the heart of the OS
# ---------------------------------------------------------------------------

class FerrymanKernel:
    def __init__(self) -> None:
        self.skills: Dict[str, SkillModel] = {}
        self.tasks: Dict[str, Task] = {}
        self.workspace_root: Path = config.root_dir / "workspaces"
        self._master_agent: Optional[Agent] = None
        self._browsers: Dict[str, Any] = {}
        self.mcp_client: Any = None # To be initialized later

    # ---- Skill management ------------------------------------------------

    def scan_skills(self) -> None:
        """Scan user & official skill directories."""
        for base in config.skills_dir:
            if not base.exists():
                continue
            for item in base.iterdir():
                if item.is_dir():
                    skill = load_skill_from_directory(item)
                    if skill:
                        self.skills[skill.name] = skill
        logger.info(f"Scanned {len(self.skills)} skill(s)")

    def get_skill_index_xml(self) -> str:
        """XML block injected into the OS Prompt."""
        if not self.skills:
            return "<available_skills>\n  <!-- No skills installed -->\n</available_skills>"
        lines = ["<available_skills>"]
        for s in self.skills.values():
            lines.append(
                f"  <skill>\n"
                f"    <name>{s.name}</name>\n"
                f"    <description>{s.description}</description>\n"
                f"  </skill>"
            )
        lines.append("</available_skills>")
        return "\n".join(lines)

    def read_skill_sop(self, name: str) -> str:
        """Return the full SKILL.md content for a given skill."""
        if name not in self.skills:
            return f"Error: Skill '{name}' not found."
        return (self.skills[name].path / "SKILL.md").read_text(encoding="utf-8")

    # ---- Workspace & task management -------------------------------------

    def ensure_session_workspace(self, session_id: str) -> Path:
        session_dir = self.workspace_root / session_id / "artifacts"
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir

    def _persist_task(
        self,
        session_id: str,
        title: str,
        parent_id: Optional[str] = None,
        args: Optional[Dict] = None,
    ) -> Task:
        logger.debug(f"Creating task: {title} (session_id: {session_id}, parent_id: {parent_id})")
        task = Task(
            session_id=session_id,
            parent_id=parent_id,
            title=title,
            args=args or {},
        )
        self.tasks[task.id] = task
        
        # Persist to DB
        with get_session() as session:
            session.add(task)
            session.commit()
            session.refresh(task)
            logger.debug(f"Task persisted to DB with ID: {task.id}")
            
        return task

    def _persist_task_update(
        self,
        task_id: str,
        status: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ) -> None:
        logger.debug(f"Updating task {task_id}: status={status}, metadata={metadata}")
        with get_session() as session:
            from sqlmodel import select
            statement = select(Task).where(Task.id == task_id)
            db_task = session.exec(statement).first()
            
            if db_task:
                if status:
                    db_task.status = status
                    if status in (TaskStatus.SUCCESS, TaskStatus.FAILED):
                        db_task.finished_at = datetime.now()
                if metadata:
                    # SQLModel Tip: Must re-assign to trigger dirty check for JSON
                    temp_meta = dict(db_task.metadata_)
                    temp_meta.update(metadata)
                    db_task.metadata_ = temp_meta
                db_task.updated_at = datetime.now()
                session.add(db_task)
                session.commit()
                
                # Update in-memory cache too
                self.tasks[task_id] = db_task

    # ---- Master Agent ----------------------------------------------------

    async def mcp_tool_bridge(self, ctx: RunContext[None], tool_name: str, arguments: dict) -> dict:
        """Call an external MCP tool."""
        if not self.mcp_client:
            return {"status": "error", "message": "MCP Client not initialized"}
        return await self.mcp_client.call_tool(tool_name, arguments)

    async def get_browser(self, session_id: str):
        """Lazy load a BrowserController for the session."""
        if not hasattr(self, "_browsers"):
            self._browsers = {}
        if session_id not in self._browsers:
            from app.core.browser import BrowserController
            browser = BrowserController(headless=True)
            await browser.__aenter__()
            self._browsers[session_id] = browser
        return self._browsers[session_id]

    async def close_browser(self, session_id: str):
        if hasattr(self, "_browsers") and session_id in self._browsers:
            await self._browsers[session_id].__aexit__(None, None, None)
            del self._browsers[session_id]

    def _build_system_prompt(self, session_id: str) -> str:
        """Render the OS Prompt with runtime context."""
        workspace = self.ensure_session_workspace(session_id)
        return OS_PROMPT.format(
            os_name=platform.system(),
            current_time=datetime.now().isoformat(),
            root_dir=str(config.root_dir),
            skill_list=self.get_skill_index_xml(),
        )

    def _build_agent(self, session_id: str, system_prompt: str) -> Agent:
        """
        Create a PydanticAI Agent with standard OS tools and a given system prompt.
        Dynamic model initialization using the Registry.
        """
        active_model_id = get_active_model_id()
        provider, model_name = active_model_id.split(":", 1) if ":" in active_model_id else ("gemini", active_model_id)
        
        # Get provider-specific keys/urls from Registry
        provider_config = get_provider_llm_config(provider)
        
        # Standardize Base URL and API Key (Strip spaces, convert empty to None)
        api_key = provider_config.get("api_key")
        base_url = provider_config.get("base_url")
        if base_url and isinstance(base_url, str):
            base_url = base_url.strip() or None
        if api_key and isinstance(api_key, str):
            api_key = api_key.strip()
            
        # Cleaned kwargs for Provider instantiation
        p_kwargs = {
            "api_key": api_key,
            "base_url": base_url
        }
        # Final cleanup of None values to let PydanticAI defaults work
        p_kwargs = {k: v for k, v in p_kwargs.items() if v is not None}

        # Explicit model initialization to support base_url and api_key overrides via Providers
        llm_model: Any = model_name
        try:
            if provider == "openai":
                from pydantic_ai.models.openai import OpenAIModel
                from pydantic_ai.providers.openai import OpenAIProvider
                p_instance = OpenAIProvider(**p_kwargs)
                llm_model = OpenAIModel(model_name, provider=p_instance)
            elif provider == "anthropic":
                from pydantic_ai.models.anthropic import AnthropicModel
                from pydantic_ai.providers.anthropic import AnthropicProvider
                p_instance = AnthropicProvider(**p_kwargs)
                llm_model = AnthropicModel(model_name, provider=p_instance)
            elif provider == "gemini":
                from pydantic_ai.models.google import GoogleModel
                from pydantic_ai.providers.google import GoogleProvider
                p_instance = GoogleProvider(**p_kwargs)
                llm_model = GoogleModel(model_name, provider=p_instance)
        except Exception as e:
            logger.warning(f"Failed to initialize explicit model for {provider}, falling back to string name: {e}")
            import traceback
            logger.debug(traceback.format_exc())

        agent: Agent["FerrymanKernel"] = Agent(
            model=llm_model,
            system_prompt=system_prompt,
            deps_type=FerrymanKernel,
        )

        # -- Tool: read_skill_sop ------------------------------------------
        @agent.tool
        async def read_skill_sop(
            ctx: RunContext["FerrymanKernel"], skill_name: str
        ) -> str:
            """Read the full SOP (SKILL.md) of a specific skill before executing it."""
            kernel = ctx.deps
            return kernel.read_skill_sop(skill_name)

        # -- Tool: run_skill -----------------------------------------------
        @agent.tool
        async def run_skill(
            ctx: RunContext["FerrymanKernel"],
            skill_name: str,
            instruction: str,
            session_id: str,
        ) -> str:
            """
            Execute a specialized Skill (App).
            Skills are independent; if you need to track this as a task, 
            create the task separately using `create_task`.
            """
            kernel = ctx.deps
            if skill_name not in kernel.skills:
                return f"Error: Skill '{skill_name}' not found."

            workspace = kernel.ensure_session_workspace(session_id)
            sop = kernel.read_skill_sop(skill_name)
            
            logger.info(f"Executing skill '{skill_name}' in {workspace}")
            
            skill_context = f"You are executing the specialized Skill '{skill_name}'.\n\nSOP (Standard Operating Procedure):\n{sop}\n"
            executor = kernel._build_agent(session_id, skill_context)
            
            try:
                result = await executor.run(instruction, deps=kernel)
                result_data = getattr(result, 'data', getattr(result, 'output', str(result)))
                return f"Skill '{skill_name}' execution completed. Result: {str(result_data)}"
            except Exception as e:
                return f"Error executing Skill '{skill_name}': {e}"

        def _normalize_workspace_path(file_path: str) -> str:
            """Strip leading 'artifacts/' from agent-supplied paths to avoid double nesting."""
            for prefix in ("artifacts/", "./artifacts/", "./"):
                if file_path.startswith(prefix):
                    file_path = file_path[len(prefix):]
            return file_path

        # -- Tool: read_file -----------------------------------------------
        @agent.tool
        async def read_file(
            ctx: RunContext["FerrymanKernel"], file_path: str
        ) -> str:
            """Read a file from the session workspace."""
            base_dir = ctx.deps.ensure_session_workspace(session_id)
            p = base_dir / _normalize_workspace_path(file_path)
            if not p.exists():
                return f"Error: File not found: {file_path}"
            return p.read_text(encoding="utf-8")

        # -- Tool: write_file ----------------------------------------------
        @agent.tool
        async def write_file(
            ctx: RunContext["FerrymanKernel"],
            file_path: str,
            content: str,
        ) -> str:
            """Write content to a file in the session workspace."""
            base_dir = ctx.deps.ensure_session_workspace(session_id)
            normalized = _normalize_workspace_path(file_path)
            full_path = base_dir / normalized
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding="utf-8")
            return f"Successfully wrote {len(content)} characters to {normalized}"

        # -- Tool: list_files ----------------------------------------------
        @agent.tool
        async def list_files(
            ctx: RunContext["FerrymanKernel"], directory: str = "."
        ) -> str:
            """List files and directories in the session workspace."""
            base_dir = ctx.deps.ensure_session_workspace(session_id)
            p = base_dir / _normalize_workspace_path(directory)
            if not p.exists():
                return f"Error: Directory not found: {directory}"
            entries = sorted(p.iterdir())
            return "\n".join(
                f"{'[DIR] ' if e.is_dir() else ''}{e.name}" for e in entries
            )

        # -- RISC Web Actions ----------------------------------------------
        
        @agent.tool
        async def browser_navigate(ctx: RunContext["FerrymanKernel"], url: str) -> str:
            """Navigate to a website url (e.g. 'https://bing.com') using the stealth browser."""
            browser = await ctx.deps.get_browser(session_id)
            return await browser.navigate(url)

        @agent.tool
        async def browser_get_distilled_dom(ctx: RunContext["FerrymanKernel"]) -> str:
            """Extract pure, hyper-clean text/markdown content from the current page. Best for reading articles."""
            browser = await ctx.deps.get_browser(session_id)
            return await browser.get_distilled_dom()

        @agent.tool
        async def browser_aria_snapshot(ctx: RunContext["FerrymanKernel"]) -> str:
            """
            Get a high-density 'Accessibility Tree' snapshot. 
            Lists UI elements by Role and Name. Use this to 'see' the UI 
            layout efficiently for automation.
            """
            browser = await ctx.deps.get_browser(session_id)
            return await browser.get_aria_snapshot()

        @agent.tool
        async def browser_click(ctx: RunContext["FerrymanKernel"], selector: str) -> str:
            """Click on an element on the parsed DOM using a CSS selector."""
            browser = await ctx.deps.get_browser(session_id)
            return await browser.click(selector)

        @agent.tool
        async def browser_click_id(ctx: RunContext["FerrymanKernel"], element_id: str) -> str:
            """Click on an element using its numeric ID (e.g. '12') from the aria_snapshot."""
            browser = await ctx.deps.get_browser(session_id)
            return await browser.click_id(element_id)

        @agent.tool
        async def browser_type_id(ctx: RunContext["FerrymanKernel"], element_id: str, text: str) -> str:
            """Type text into an input field using its numeric ID (e.g. '5') from the aria_snapshot."""
            browser = await ctx.deps.get_browser(session_id)
            return await browser.type_id(element_id, text)

        @agent.tool
        async def browser_hover(ctx: RunContext["FerrymanKernel"], selector: str) -> str:
            """Hover the mouse over an element on the current page."""
            browser = await ctx.deps.get_browser(session_id)
            return await browser.hover(selector)

        @agent.tool
        async def browser_scroll(ctx: RunContext["FerrymanKernel"], selector: str = None) -> str:
            """Scroll the page or a specific element into view."""
            browser = await ctx.deps.get_browser(session_id)
            return await browser.scroll(selector)

        @agent.tool
        async def browser_wait(ctx: RunContext["FerrymanKernel"], timeout_ms: int = 2000, selector: str = None) -> str:
            """Wait for a certain amount of time or for an element to appear."""
            browser = await ctx.deps.get_browser(session_id)
            return await browser.wait(timeout_ms, selector)

        @agent.tool
        async def browser_screenshot(ctx: RunContext["FerrymanKernel"], selector: str = None) -> str:
            """Take a screenshot of the page or a specific element."""
            browser = await ctx.deps.get_browser(session_id)
            return await browser.screenshot(selector)

        @agent.tool
        async def browser_type(ctx: RunContext["FerrymanKernel"], selector: str, text: str) -> str:
            """Type text into an input field on the current page."""
            browser = await ctx.deps.get_browser(session_id)
            return await browser.type(selector, text)

        # -- Task Management ----------------------------------------------
        @agent.tool
        async def create_task(
            ctx: RunContext["FerrymanKernel"], session_id: str, title: str, instruction: str
        ) -> str:
            """
            Register a persistent Task record to track the lifecycle of a work unit.
            Returns a task_id which can be used to update status or metadata.
            """
            kernel = ctx.deps
            task = kernel._persist_task(session_id=session_id, title=title, args={"instruction": instruction})
            return task.id

        @agent.tool
        async def update_task(
            ctx: RunContext["FerrymanKernel"], task_id: str, status: str, progress_note: Optional[str] = None
        ) -> str:
            """
            Update the state of an existing Task record.
            Status values: 'pending', 'running', 'success', 'failed', 'canceled'.
            """
            kernel = ctx.deps
            meta = {"progress_note": progress_note} if progress_note else None
            kernel._persist_task_update(task_id, status=status, metadata=meta)
            return f"Task {task_id} updated to {status}"

        @agent.tool
        async def list_tasks(ctx: RunContext["FerrymanKernel"], session_id: str) -> str:
            """List all orchestration tasks for a session to query status or find IDs."""
            kernel = ctx.deps
            relevant = [t for t in kernel.tasks.values() if t.session_id == session_id]
            if not relevant:
                return "No tasks found for this session."
            
            lines = ["Current Orchestration Tasks:"]
            for t in relevant:
                lines.append(f"- ID: {t.id} | Title: {t.title} | Status: {t.status}")
            return "\n".join(lines)

        # -- Scheduling Tools ---------------------------------------------
        @agent.tool
        async def create_schedule(
            ctx: RunContext["FerrymanKernel"], name: str, cron_expression: str, instruction: str
        ) -> str:
            """
            Register a persistent Schedule record for automated/recurring execution.
            - cron_expression: standard cron string (e.g., '0 9 * * *').
            - instruction: the goal Ferryman should achieve when triggered.
            """
            kernel = ctx.deps
            new_schedule = Schedule(
                name=name,
                cron_expression=cron_expression,
                args={"instruction": instruction}
            )
            with get_session() as session:
                session.add(new_schedule)
                session.commit()
                session.refresh(new_schedule)
            return f"Schedule '{name}' created with ID: {new_schedule.id}"

        @agent.tool
        async def list_schedules(ctx: RunContext["FerrymanKernel"]) -> str:
            """List all automated routines and their status."""
            with get_session() as session:
                from sqlmodel import select
                schedules = session.exec(select(Schedule)).all()
                if not schedules:
                    return "No schedules registered."
                lines = ["Registered Automated Routines:"]
                for s in schedules:
                    status = "Enabled" if s.enabled else "Disabled"
                    lines.append(f"- [{status}] ID: {s.id} | Name: {s.name} | Cron: {s.cron_expression}")
                return "\n".join(lines)

        @agent.tool
        async def update_schedule(
            ctx: RunContext["FerrymanKernel"], 
            schedule_id: str, 
            enabled: Optional[bool] = None, 
            cron_expression: Optional[str] = None
        ) -> str:
            """Toggle or modify an automated routine."""
            with get_session() as session:
                from sqlmodel import select
                statement = select(Schedule).where(Schedule.id == schedule_id)
                s = session.exec(statement).first()
                if not s:
                    return "Schedule not found."
                if enabled is not None:
                    s.enabled = enabled
                if cron_expression:
                    s.cron_expression = cron_expression
                s.updated_at = datetime.now()
                session.add(s)
                session.commit()
                return f"Schedule {schedule_id} updated."

        @agent.tool
        async def delete_schedule(ctx: RunContext["FerrymanKernel"], schedule_id: str) -> str:
            """Remove an automated routine entry."""
            with get_session() as session:
                from sqlmodel import select
                statement = select(Schedule).where(Schedule.id == schedule_id)
                s = session.exec(statement).first()
                if s:
                    session.delete(s)
                    session.commit()
                    return f"Schedule {schedule_id} deleted."
                return "Schedule not found."

        # -- MCP Tool Bridge ----------------------------------------------
        @agent.tool
        async def call_mcp_tool(
            ctx: RunContext["FerrymanKernel"], tool_name: str, arguments: dict
        ) -> dict:
            """Call an external MCP tool."""
            kernel = ctx.deps
            if not kernel.mcp_client:
                return {"status": "error", "message": "MCP Client not initialized"}
            return await kernel.mcp_client.call_tool(tool_name, arguments)

        return agent

    def _get_master_agent(self, session_id: str) -> Agent:
        return self._build_agent(session_id, self._build_system_prompt(session_id))

    async def run_master_agent(self, instruction: str, session_id: str) -> Dict:
        """
        The single entry-point called by the JSON-RPC `execute` method.
        """
        logger.info(f"Master Agent processing session {session_id}: {instruction}")

        try:
            # 1. Ensure Session exists in DB
            with get_session() as db_session:
                session_obj = db_session.get(Session, session_id)
                if not session_obj:
                    # Create new session if it doesn't exist
                    session_obj = Session(id=session_id, title="New Chat")
                    db_session.add(session_obj)
                    db_session.commit()
                    db_session.refresh(session_obj)
                
                # Save user message
                user_msg = Message(
                    session_id=session_id,
                    role="user",
                    content=instruction,
                    type="text"
                )
                db_session.add(user_msg)
                db_session.commit()
                
            # 2. Execute agent
            agent = self._get_master_agent(session_id)
            result = await agent.run(instruction, deps=self)
            result_data = getattr(result, 'data', getattr(result, 'output', str(result)))
            
            # 3. Extract usage stats
            input_tokens = 0
            output_tokens = 0
            usage_metadata = {}
            try:
                usage = result.usage()
                input_tokens = usage.input_tokens
                output_tokens = usage.output_tokens
                usage_metadata = {
                    "usage": {
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "total_tokens": usage.total_tokens,
                    }
                }
            except (AttributeError, Exception):
                logger.debug("Usage stats not available for this run.")

            # 4. Save response message and Update Session
            with get_session() as db_session:
                # Save assistant message
                assistant_msg = Message(
                    session_id=session_id,
                    role="assistant",
                    content=str(result_data),
                    type="text",
                    metadata_=usage_metadata
                )
                db_session.add(assistant_msg)
                
                # Update Session (Incremental token update)
                session_obj = db_session.get(Session, session_id)
                if session_obj:
                    session_obj.input_tokens += input_tokens
                    session_obj.output_tokens += output_tokens
                    session_obj.updated_at = datetime.now(timezone.utc)
                    
                    # 5. Auto-title generation for "New Chat" sessions
                    if session_obj.title == "New Chat":
                        try:
                            # Minimal agent to summarize the first message into a title
                            title_agent = Agent(
                                model=agent.model,
                                system_prompt="You are a session title generator. Generate a concise, clear title (max 5 words) for the conversation based on the user's message. Output ONLY the title, no quotes or meta-text. Use the same language as the user."
                            )
                            title_result = await title_agent.run(f"User message: {instruction}")
                            new_title = str(title_result.data).strip()
                            if new_title:
                                # Clean up potential quotes
                                new_title = new_title.strip('"').strip("'")
                                session_obj.title = new_title
                        except Exception as title_err:
                            logger.error(f"Failed to auto-generate session title: {title_err}")
                    
                    db_session.add(session_obj)
                
                db_session.commit()

            return {
                "status": "success",
                "response": result_data,
                "session_id": session_id,
                "usage": usage_metadata.get("usage", {})
            }

        except Exception as e:
            logger.error(f"Master Agent failed: {e}", exc_info=True)
            return {
                "status": "error",
                "message": str(e),
            }
        finally:
            # Clean up browser session
            await self.close_browser(session_id)
