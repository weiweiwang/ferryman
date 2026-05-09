from pathlib import Path

from app.core.deps import AgentDeps


def test_toolkits_do_not_call_kernel_through_deps_directly():
    toolkit_dir = Path("backend/app/core/toolkits")
    forbidden_deps_access = ("ctx.deps." + "runtime", "deps." + "runtime")
    offenders = []
    for path in toolkit_dir.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if any(pattern in text for pattern in forbidden_deps_access):
            offenders.append(str(path))

    assert offenders == []


def test_agent_deps_exposes_explicit_managers_not_runtime():
    field_names = set(AgentDeps.__dataclass_fields__)

    assert "settings" in field_names
    assert "workspace_dir" in field_names
    assert "agent_manager" in field_names
    assert "browser_manager" in field_names
    assert "prompt_builder" in field_names
    assert "skill_manager" in field_names
    assert "task_manager" in field_names
    assert "runtime" not in field_names
    assert "kernel" not in field_names


def test_agent_deps_does_not_define_runtime_protocols():
    text = Path("backend/app/core/deps.py").read_text(encoding="utf-8")

    assert "Protocol" not in text
    assert "get_runtime" not in text


def test_backend_has_no_kernel_compatibility_surface():
    assert not Path("backend/app/core/kernel.py").exists()

    forbidden_patterns = (
        "FerrymanKernel",
        "app.core.kernel",
        "ctx.deps.kernel",
        "deps.kernel",
        "app_state.kernel",
        "context.kernel",
        "fastapi_app.state.kernel",
    )
    offenders = []
    for path in Path("backend/app").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        matches = [pattern for pattern in forbidden_patterns if pattern in text]
        if matches:
            offenders.append((str(path), matches))

    assert offenders == []


def test_browser_manager_does_not_depend_on_runtime():
    text = Path("backend/app/core/browser_manager.py").read_text(encoding="utf-8")

    assert "self._" + "runtime" not in text
    assert "runtime" + ":" not in text


def test_context_manager_does_not_depend_on_runtime():
    text = Path("backend/app/core/context_manager.py").read_text(encoding="utf-8")

    assert "self._" + "runtime" not in text
    assert "runtime" + ":" not in text


def test_tool_manager_does_not_depend_on_runtime():
    text = Path("backend/app/core/tool_manager.py").read_text(encoding="utf-8")

    assert "self._" + "runtime" not in text
    assert "runtime" + ":" not in text
    assert "Protocol" not in text


def test_agent_manager_does_not_depend_on_runtime_or_protocol():
    text = Path("backend/app/core/agent_manager.py").read_text(encoding="utf-8")

    assert "self._" + "runtime" not in text
    assert "runtime" + ":" not in text
    assert "Protocol" not in text
    assert "def build_system_prompt" not in text
    assert "def build_runtime_augmented_instruction" not in text


def test_agent_runs_start_only_through_run_registry():
    offenders = []
    allowed_paths = {
        Path("backend/app/core/run_registry.py"),
        Path("backend/app/core/runtime.py"),
    }

    for path in Path("backend/app").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if ".run_master_agent(" not in text:
            continue
        if path not in allowed_paths:
            offenders.append(str(path))

    assert offenders == []
