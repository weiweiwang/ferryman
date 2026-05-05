from app.core.agent_manager import AgentManager
from app.core.browser_manager import BrowserManager
from app.core.context_manager import ContextManager
from app.core.model_manager import ModelManager
from app.core.prompt_builder import PromptBuilder
from app.core.runtime import FerrymanRuntime
from app.core.schedule_manager import ScheduleManager
from app.core.config import Settings
from app.core.session_manager import SessionManager
from app.core.skill_manager import SkillManager
from app.core.task_manager import TaskManager
from app.core.tool_manager import ToolManager


def test_runtime_composes_core_managers(tmp_path):
    runtime = FerrymanRuntime(Settings(root_dir=tmp_path))

    assert isinstance(runtime, FerrymanRuntime)
    assert runtime.settings.root_dir == tmp_path
    assert not hasattr(runtime, "skills")
    assert not hasattr(runtime, "tasks")
    assert not hasattr(runtime, "workspace_root")
    assert not hasattr(runtime, "_master_agent")
    assert isinstance(runtime.model_manager, ModelManager)
    assert isinstance(runtime.session_manager, SessionManager)
    assert isinstance(runtime.skill_manager, SkillManager)
    assert isinstance(runtime.task_manager, TaskManager)
    assert isinstance(runtime.context_manager, ContextManager)
    assert isinstance(runtime.prompt_builder, PromptBuilder)
    assert isinstance(runtime.tool_manager, ToolManager)
    assert isinstance(runtime.schedule_manager, ScheduleManager)
    assert isinstance(runtime.browser_manager, BrowserManager)
    assert isinstance(runtime.agent_manager, AgentManager)


def test_runtime_does_not_expose_manager_forwarding_methods(tmp_path):
    runtime = FerrymanRuntime(Settings(root_dir=tmp_path))

    forbidden_methods = (
        "scan_skills",
        "get_skill_index_text",
        "read_skill_sop",
        "persist_task",
        "persist_task_update",
        "update_session_usage",
        "_init_llm_model",
        "_estimate_text_tokens",
        "_normalize_session_memory",
        "_parse_utc_timestamp",
        "_ensure_utc_datetime",
        "_format_utc_timestamp",
        "_ensure_message_token_estimates",
        "_get_session_messages",
        "_get_compaction_state",
        "_update_compaction_metadata",
        "_build_compaction_reference",
        "_serialize_messages_for_compaction",
        "_get_compaction_agent",
        "_load_compactable_messages",
        "_maybe_compact_session",
        "build_agent",
        "build_skill_agent",
        "_register_toolkit",
        "_get_master_agent",
        "get_browser",
        "close_browser",
        "cleanup_stale_browsers",
        "shutdown",
    )

    assert [method for method in forbidden_methods if hasattr(runtime, method)] == []
