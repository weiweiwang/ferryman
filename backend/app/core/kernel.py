import logging
import platform
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any, Dict
from uuid import uuid4

from asgi_correlation_id import correlation_id
from pydantic_ai.agent import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)
from pydantic_ai.usage import UsageLimits
from sqlmodel import select

from app.core.config import Settings
from app.core.db import get_session, init_db
# Refactored Imports
from app.core.deps import AgentDeps
from app.core.prompts import MASTER_SYSTEM_PROMPT, SKILL_SYSTEM_PROMPT
from app.core.toolkits.command import CommandToolkit
from app.core.toolkits.file import FileToolkit
from app.core.toolkits.skill import SkillToolkit
from app.core.toolkits.task import TaskToolkit
from app.core.toolkits.web import WebToolkit
from app.core.utils import load_skill_from_directory
from app.models.database import Session, Message, Task
from app.models.schemas import SkillModel, TaskStatus, AgentRunResult, Usage

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# FerrymanKernel – the heart of the OS
# ---------------------------------------------------------------------------

class FerrymanKernel:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self.skills: Dict[str, SkillModel] = {}
        self.tasks: Dict[str, Task] = {}
        self.workspace_root: Path = settings.root_dir / "workspaces"
        self._master_agent: Optional[Agent] = None
        self._browsers: Dict[str, Any] = {}
        self._session_headless: Dict[str, bool] = {}
        # self.mcp_client: Any = None  # To be initialized later
        self._init_directories(settings)
        init_db()

    def get_setting(self, key: str, default: Any = None) -> Any:
        """Public access to persisted runtime settings."""
        return self._settings.get(key, default)

    # ---- Skill management ------------------------------------------------

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
                logger.info(f"📁 Created directory: {sd}")

    def scan_skills(self) -> None:
        """Scan user & official skill directories."""
        for base in self._settings.skills_dir:
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

    def get_session_workspace(self, session_id: str) -> Path:
        session_dir = self.workspace_root / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir

    @staticmethod
    def _find_duplicate_task(title: str) -> Optional[Task]:
        """Search for an existing active task using order-agnostic word similarity."""
        import difflib

        def normalize(text: str) -> str:
            # Lowercase, alphanumeric only, split, sort, and re-join
            # This makes it order-insensitive: "A to B" == "B to A"
            cleaned = "".join(c if c.isalnum() else " " for c in (text or "").lower())
            return " ".join(sorted(cleaned.split()))

        norm_title = normalize(title)
        if not norm_title:
            return None

        with get_session() as session:
            from sqlmodel import select

            # 1. Fetch all candidate active tasks (pending or running)
            # noinspection PyUnresolvedReferences
            statement = select(Task).where(Task.status.in_(["pending", "running"]))
            candidates = session.exec(statement).all()

            # 2. Fuzzy Match on Normalized Titles (Sorted Words)
            for cand in candidates:
                norm_cand = normalize(cand.title)
                ratio = difflib.SequenceMatcher(None, norm_title, norm_cand).ratio()
                if ratio > 0.85:
                    logger.info(f"Task deduplication: '{title}' matched '{cand.title}' (normalized ratio {ratio:.2f})")
                    return cand

        return None

    def persist_task(
            self,
            session_id: str,
            title: str,
            parent_id: Optional[str] = None,
            args: Optional[Dict] = None,
    ) -> Task:
        """Global Task Persistence: Prevents duplicates using string similarity."""
        existing = self._find_duplicate_task(title)
        if existing:
            if existing.id not in self.tasks:
                self.tasks[existing.id] = existing
            return existing

        # Create new if no duplicate
        logger.debug(f"Creating task: {title} (session_id: {session_id}, parent_id: {parent_id})")
        task = Task(
            session_id=session_id,
            parent_id=parent_id,
            title=title,
            args=args or {},
        )
        self.tasks[task.id] = task

        with get_session() as session:
            session.add(task)
            session.commit()
            session.refresh(task)
            logger.debug(f"Task persisted to DB with ID: {task.id}")

        return task

    def persist_task_update(
            self,
            task_id: str,
            status: Optional[str] = None,
            metadata: Optional[Dict] = None,
    ) -> None:
        logger.debug(f"Updating task {task_id}: status={status}, metadata={metadata}")
        with get_session() as session:
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

    @staticmethod
    def update_session_usage(session_id: str, input_tokens: int, output_tokens: int) -> None:
        """Update the cumulative token usage for a session in the database."""
        with get_session() as session:
            session_obj = session.get(Session, session_id)
            if session_obj:
                session_obj.input_tokens += input_tokens
                session_obj.output_tokens += output_tokens
                session_obj.updated_at = datetime.now(timezone.utc)
                session.add(session_obj)
                session.commit()
                logger.debug(f"Updated usage for session {session_id}: +{input_tokens} in, +{output_tokens} out")

    # ---- Master Agent ----------------------------------------------------

    # async def mcp_tool_bridge(self, ctx: RunContext[None], tool_name: str, arguments: dict) -> dict:
    #     """Call an external MCP tool."""
    #     if not self.mcp_client:
    #         return {"status": "error", "message": "MCP Client not initialized"}
    #     return await self.mcp_client.call_tool(tool_name, arguments)

    async def get_browser(self, session_id: str, headless: Optional[bool] = None) -> Any:
        """Lazy load a BrowserController for the session. Re-initializes if mode changes."""
        await self.cleanup_stale_browsers()

        requested_headless = headless if headless is not None else True
        if headless is not None:
            self._session_headless[session_id] = headless

        # 1. Check if we need to switch mode
        if session_id in self._browsers:
            entry = self._browsers[session_id]
            existing_browser = entry["instance"]

            # Only trigger mode change if explicitly requested AND differing
            # noinspection PyProtectedMember
            if headless is not None and existing_browser._headless != headless:
                # noinspection PyProtectedMember
                logger.info(f"🔄Browser mode change detected ({existing_browser._headless} -> {headless}). "
                            f"Restarting...")
                await self.close_browser(session_id)
            else:
                # Update last active timestamp
                entry["last_active"] = time.time()
                return existing_browser

        # 1.5 Enforce Max Instances Limit (LRU Eviction)
        max_instances = self.get_setting("system.browser.max_instances", 3)
        if session_id not in self._browsers and len(self._browsers) >= max_instances:
            oldest_sid = min(self._browsers.keys(), key=lambda sid: self._browsers[sid]["last_active"])
            logger.info(f"🚀 Max browser instances ({max_instances}) reached. Evicting oldest: {oldest_sid}")
            await self.close_browser(oldest_sid)

        # 2. Create if missing (or just deleted above)
        if session_id not in self._browsers:
            from app.core.browser import BrowserController
            browser = BrowserController(
                headless=requested_headless,
                user_data_dir=str(self._settings.browser_dir)
            )
            await browser.__aenter__()
            self._browsers[session_id] = {
                "instance": browser,
                "last_active": time.time()
            }

        return self._browsers[session_id]["instance"]

    async def close_browser(self, session_id: str):
        """Safely close and remove a browser instance from cache."""
        # Pop from dict first to ensure it's removed from cache regardless of closing success
        entry = self._browsers.pop(session_id, None)
        if entry:
            browser = entry["instance"]
            try:
                await browser.__aexit__(None, None, None)
            except Exception as e:
                logger.exception(f"Failed to gracefully close browser for session {session_id}, "
                                 f"but removed from cache, exception: {e}")

    async def cleanup_stale_browsers(self):
        """Close browsers that have been inactive for longer than the configured TTL."""
        ttl = self.get_setting("system.browser.ttl", 1800)  # Default 30 minutes
        now = time.time()
        stale_sids = [
            sid for sid, entry in self._browsers.items()
            if now - entry["last_active"] > ttl
        ]

        for sid in stale_sids:
            logger.info(f"🧹 Cleaning up stale browser for session: {sid}")
            await self.close_browser(sid)

    async def shutdown(self) -> None:
        """Release runtime resources before process exit."""
        for sid in list(self._browsers.keys()):
            await self.close_browser(sid)

    def _build_system_prompt(self, session_id: str) -> str:
        """Render the stable master system prompt."""
        self.get_session_workspace(session_id)

        system_prompt = MASTER_SYSTEM_PROMPT.format(
            skill_list=self.get_skill_index_xml(),
            session_id=session_id
        )
        return system_prompt

    def build_runtime_augmented_instruction(self, instruction: str, session_id: str) -> str:
        """Attach per-run runtime context to the current request."""
        now = datetime.now().astimezone()
        timezone_name = now.tzname() or str(now.tzinfo) or "Unknown"
        current_date = now.date().isoformat()
        workspace_dir = self.get_session_workspace(session_id)
        return (
            "Runtime Context:\n"
            f"- Host OS: {platform.system()}\n"
            f"- Root Dir: {self._settings.root_dir}\n"
            f"- Session Workspace: {workspace_dir}\n"
            f"- Current Date: {current_date}\n"
            f"- Time Zone: {timezone_name}\n\n"
            "Current Request:\n"
            f"{instruction}"
        )

    def _init_llm_model(self) -> Any:
        """Initialize the LLM model based on current settings."""
        active_model_id = self._settings.get_active_model_id()
        provider, model_name = active_model_id.split(":", 1) if ":" in active_model_id else ("gemini", active_model_id)

        # Get provider-specific keys/urls from Registry
        provider_config = self._settings.get_provider_llm_config(provider)

        # Standardize Base URL and API Key
        api_key = provider_config.get("api_key")
        base_url = provider_config.get("base_url")
        if base_url and isinstance(base_url, str):
            base_url = base_url.strip() or None
        if api_key and isinstance(api_key, str):
            api_key = api_key.strip()

        p_kwargs = {k: v for k, v in {"api_key": api_key, "base_url": base_url}.items() if v is not None}

        try:
            if provider == "openai":
                from pydantic_ai.models.openai import OpenAIChatModel
                from pydantic_ai.providers.openai import OpenAIProvider
                return OpenAIChatModel(model_name, provider=OpenAIProvider(**p_kwargs))
            elif provider == "anthropic":
                from pydantic_ai.models.anthropic import AnthropicModel
                from pydantic_ai.providers.anthropic import AnthropicProvider
                return AnthropicModel(model_name, provider=AnthropicProvider(**p_kwargs))
            elif provider == "gemini":
                from pydantic_ai.models.google import GoogleModel
                from pydantic_ai.providers.google import GoogleProvider
                return GoogleModel(model_name, provider=GoogleProvider(**p_kwargs))
        except Exception as e:
            logger.exception(f"Failed to initialize explicit model for {provider}, "
                             f"falling back to string name, exception: {e}")

        return model_name

    def build_agent(self, system_prompt: str) -> Agent:
        """
        Create a PydanticAI Agent with modular toolkits and a given system prompt.
        """
        llm_model = self._init_llm_model()

        agent: Agent = Agent(
            model=llm_model,
            system_prompt=system_prompt,
            deps_type=AgentDeps,
        )

        # Register Toolkits
        self._register_toolkit(agent, SkillToolkit)
        self._register_toolkit(agent, FileToolkit)
        self._register_toolkit(agent, WebToolkit)
        self._register_toolkit(agent, TaskToolkit)
        self._register_toolkit(agent, CommandToolkit)
        return agent

    def build_skill_agent(self, skill_name: str) -> Agent:
        """Create a skill-scoped agent with the skill instructions injected into its system prompt."""
        skill_context = SKILL_SYSTEM_PROMPT.format(
            skill_name=skill_name,
            sop=self.read_skill_sop(skill_name),
            skill_list=self.get_skill_index_xml(),
        )
        return self.build_agent(skill_context)

    @staticmethod
    def _register_toolkit(agent: Agent, toolkit_class: Any) -> None:
        """Register all tools from a toolkit class using its get_tools() method."""
        if hasattr(toolkit_class, "get_tools"):
            from functools import wraps
            from pydantic_ai import RunContext
            from asgi_correlation_id import correlation_id
            import time
            import json

            for tool_func in toolkit_class.get_tools():

                def make_wrapped_tool(bound_tool_func):
                    @wraps(bound_tool_func)
                    async def wrapped_tool(ctx: RunContext[AgentDeps], *args, **kwargs):
                        start_time = time.time()
                        tool_name = bound_tool_func.__name__
                        run_id = correlation_id.get() or "unknown-run"

                        input_summary = {}
                        try:
                            for k, v in kwargs.items():
                                if hasattr(v, "model_dump"):
                                    input_summary[k] = v.model_dump()
                                else:
                                    input_summary[k] = v
                            raw_input = json.dumps(input_summary, default=str)
                            if len(raw_input) > 2000:
                                input_summary = {"_truncated": True, "size": len(raw_input)}
                        except Exception:
                            input_summary = {"_serialization_error": True}

                        await ctx.deps.emit_tool_event(
                            run_id=run_id,
                            tool_name=tool_name,
                            phase="start",
                            input=input_summary
                        )

                        try:
                            result = await bound_tool_func(ctx, *args, **kwargs)
                            duration = int((time.time() - start_time) * 1000)
                            await ctx.deps.emit_tool_event(
                                run_id=run_id,
                                tool_name=tool_name,
                                phase="complete",
                                duration_ms=duration
                            )
                            return result
                        except Exception as e:
                            duration = int((time.time() - start_time) * 1000)
                            await ctx.deps.emit_tool_event(
                                run_id=run_id,
                                tool_name=tool_name,
                                phase="error",
                                duration_ms=duration
                            )
                            raise e

                    return wrapped_tool

                agent.tool(make_wrapped_tool(tool_func))

    def _get_master_agent(self, session_id: str) -> Agent:
        return self.build_agent(self._build_system_prompt(session_id))

    def _get_session_messages(self, session_id: str) -> list[ModelMessage]:
        """Load and convert history from database into PydanticAI messages."""
        # Get configurable limit, default to 30 messages (~15 rounds)
        limit = self.get_setting("system.llm.history_limit", 30)

        with get_session() as db_session:
            from sqlalchemy import desc
            # Query the LATEST messages first
            statement = (
                select(Message)
                .where(Message.session_id == session_id)
                .order_by(desc(Message.created_at))  # type:ignore
                .limit(limit)
            )
            db_messages = list(db_session.exec(statement).all())

            # Reverse back so the chronological order is [Old -> New]
            db_messages.reverse()

            history: list[ModelMessage] = []
            for msg in db_messages:
                if msg.role == "user":
                    history.append(ModelRequest(parts=[UserPromptPart(content=msg.content)]))
                elif msg.role == "assistant":
                    history.append(ModelResponse(parts=[TextPart(content=msg.content)]))
            return history

    async def run_master_agent(self, instruction: str, session_id: str, emit_event_cb: Optional[Any] = None) -> dict:
        """
        The single entry-point called by the JSON-RPC `execute` method.
        """
        logger.info(f"Master Agent processing session {session_id}: {instruction}")

        request_id = correlation_id.get() or uuid4().hex
        user_message_id: Optional[str] = None

        try:
            # 1. Ensure Session exists in DB
            with get_session() as db_session:
                session_obj = db_session.get(Session, session_id)
                if not session_obj:
                    # Create new session if it doesn't exist
                    session_obj = Session(id=session_id, title=None)
                    db_session.add(session_obj)
                    db_session.commit()
                    db_session.refresh(session_obj)

            # Load existing thread history before persisting the current turn,
            # so the new user message does not get duplicated into message_history.
            history = self._get_session_messages(session_id)

            # Persist the incoming user turn immediately for auditability.
            with get_session() as db_session:
                # Persist the incoming user turn immediately for auditability.
                user_msg = Message(
                    session_id=session_id,
                    role="user",
                    content=instruction,
                    type="text",
                    metadata_={
                        "run": {
                            "id": request_id,
                            "status": "pending",
                            "scope": "master",
                        }
                    }
                )
                db_session.add(user_msg)
                db_session.commit()
                db_session.refresh(user_msg)
                user_message_id = user_msg.id

            # 2. Execute agent
            master_agent = self._get_master_agent(session_id)
            deps = AgentDeps(
                kernel=self,
                session_id=session_id,
                emit_event_cb=emit_event_cb
            )
            # Use configurable shared request limit, defaults to 100
            request_limit = self.get_setting("system.llm.request_limit", 100)
            augmented_instruction = self.build_runtime_augmented_instruction(instruction, session_id)

            result = await master_agent.run(
                augmented_instruction,
                deps=deps,
                message_history=history,
                usage_limits=UsageLimits(request_limit=request_limit)
            )
            result_data = result.output
            response_messages = [msg for msg in result.new_messages() if isinstance(msg, ModelResponse)]
            latest_response = response_messages[-1] if response_messages else None
            serialized_response = (
                ModelMessagesTypeAdapter.dump_python([latest_response], mode="json")[0]
                if latest_response is not None
                else None
            )

            # 3. Handle Usage and Persistence
            usage = result.usage()
            usage_data = {
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "total_tokens": usage.total_tokens,
            }
            logger.info({
                "message": {
                    "session_id": session_id,
                    "request_id": request_id,
                    "event": "agent_run",
                    "scope": "master",
                    "status": "success",
                    "input": instruction,
                    "output": str(result_data),
                    "usage": usage_data,
                }
            })

            with get_session() as db_session:
                # Mark the persisted user turn as completed for this run.
                if user_message_id:
                    user_msg = db_session.get(Message, user_message_id)
                    if user_msg:
                        user_meta = dict(user_msg.metadata_ or {})
                        user_meta["run"] = {
                            "id": request_id,
                            "status": "success",
                            "scope": "master",
                        }
                        user_msg.metadata_ = user_meta
                        db_session.add(user_msg)

                # Save assistant message
                assistant_msg = Message(
                    session_id=session_id,
                    role="assistant",
                    content=str(result_data),
                    type="text",
                    parts=serialized_response.get("parts", []) if serialized_response else [],
                    metadata_={
                        "usage": usage_data,
                        "model": {
                            "name": serialized_response.get("model_name") if serialized_response else None,
                            "provider": serialized_response.get("provider_name") if serialized_response else None,
                        },
                        "run": {
                            "id": request_id,
                            "status": "success",
                            "scope": "master",
                        }
                    }
                )
                db_session.add(assistant_msg)

                # Update Session (Atomic incremental update)
                session_obj = db_session.get(Session, session_id)
                if session_obj:
                    session_obj.input_tokens += usage.input_tokens
                    session_obj.output_tokens += usage.output_tokens
                    session_obj.updated_at = datetime.now(timezone.utc)

                    # Auto-title generation removed as requested

                    db_session.add(session_obj)

                db_session.commit()

            # Return ChatFinalPayload dict representing the unified event structure
            from app.models.events import FerrymanEventEnvelope, EventNamespace, ChatFinalPayload
            payload = ChatFinalPayload(
                run_id=request_id,
                messages=[{"role": "assistant", "content": str(result_data)}],
                usage=usage_data
            )
            final_res = FerrymanEventEnvelope(
                namespace=EventNamespace.AGENT,
                event="chat_final",
                session_id=session_id,
                payload=payload
            )
            return final_res.model_dump(mode="json")

        except Exception as e:
            logger.exception(f"Master Agent failed for session {session_id}")
            error_message = str(e)

            with get_session() as db_session:
                if user_message_id:
                    user_msg = db_session.get(Message, user_message_id)
                    if user_msg:
                        user_meta = dict(user_msg.metadata_ or {})
                        user_meta["run"] = {
                            "id": request_id,
                            "status": "failed",
                            "scope": "master",
                            "error": error_message,
                        }
                        user_msg.metadata_ = user_meta
                        db_session.add(user_msg)

                failure_msg = Message(
                    session_id=session_id,
                    role="assistant",
                    content=f"Run failed: {error_message}",
                    type="text",
                    metadata_={
                        "run": {
                            "id": request_id,
                            "status": "failed",
                            "scope": "master",
                            "error": error_message,
                        }
                    }
                )
                db_session.add(failure_msg)

                session_obj = db_session.get(Session, session_id)
                if session_obj:
                    session_obj.updated_at = datetime.now(timezone.utc)
                    db_session.add(session_obj)

                db_session.commit()

            return AgentRunResult(
                status="error",
                message=error_message,
                session_id=session_id,
            )
        # FINALLY block browser closing removed to support persistent session states
