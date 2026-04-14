import json
import subprocess
import sys
import shutil
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.core.deps import AgentDeps
from app.core.kernel import FerrymanKernel
from app.core.toolkits.command import CommandToolkit
from app.core.toolkits.file import FileToolkit
from app.core.toolkits.skill import SkillToolkit

# Setup paths for tests
TEST_ROOT = Path("/tmp/ferryman_skill_test")
TEST_USER_SKILLS = TEST_ROOT / "user" / "skills"
TEST_BUNDLED_SKILLS = TEST_ROOT / "bundled" / "skills"
TEST_WORKSPACES = TEST_ROOT / "workspaces"

REPO_ROOT = Path(__file__).resolve().parents[2]
INIT_SCRIPT = REPO_ROOT / "skills" / "skill-creator" / "scripts" / "init_skill.py"
VALIDATE_SCRIPT = REPO_ROOT / "skills" / "skill-creator" / "scripts" / "quick_validate.py"

@pytest.fixture(autouse=True)
def setup_test_environment(monkeypatch):
    if TEST_ROOT.exists():
        shutil.rmtree(TEST_ROOT)

    TEST_ROOT.mkdir(parents=True, exist_ok=True)
    TEST_USER_SKILLS.mkdir(parents=True, exist_ok=True)
    TEST_BUNDLED_SKILLS.mkdir(parents=True, exist_ok=True)
    TEST_WORKSPACES.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("FERRYMAN_BUNDLED_SKILLS_DIR", str(TEST_BUNDLED_SKILLS))

    yield

    if TEST_ROOT.exists():
        shutil.rmtree(TEST_ROOT)


def create_test_settings() -> Settings:
    return Settings(root_dir=TEST_ROOT)


def create_mock_skill(name: str, desc: str, directory: Path):
    """Utility to create a mock skill directory."""
    skill_dir = directory / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_md = skill_dir / "SKILL.md"
    content = f"""---
name: {name}
description: {desc}
version: 1.0.0
---
# Mock SOP
"""
    skill_md.write_text(content, encoding="utf-8")


def create_mock_skill_with_script(name: str, desc: str, directory: Path):
    create_mock_skill(name, desc, directory)
    scripts_dir = directory / name / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    (scripts_dir / "fetch.py").write_text("print('ok')\n", encoding="utf-8")


def create_draft_skill(skill_dir: Path, name: str = "draft-skill"):
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"""---
name: {name}
description: Draft skill for publishing
version: 1.0.0
---
# Draft SOP
""",
        encoding="utf-8",
    )


# --- Skill scanning & fetching tests (migrated from test_kernel.py) ---
def test_scan_skills_and_xml_index():
    create_mock_skill("user_skill", "User skill desc", TEST_USER_SKILLS)
    create_mock_skill("internal_skill", "Internal skill desc", TEST_BUNDLED_SKILLS)

    kernel = FerrymanKernel(create_test_settings())
    kernel.scan_skills()
    assert "user_skill" in kernel.skills
    assert "internal_skill" in kernel.skills
    
    # Test XML generation (OS Prompt formatting)
    xml = kernel.get_skill_index_xml()
    assert "<available_skills>" in xml
    assert "<name>user_skill</name>" in xml
    assert "<description>Internal skill desc</description>" in xml


def test_read_skill_sop():
    create_mock_skill("target_skill", "Test", TEST_USER_SKILLS)
    kernel = FerrymanKernel(create_test_settings())
    kernel.scan_skills()
    
    sop = kernel.read_skill_sop("target_skill")
    assert "Mock SOP" in sop
    
    error_sop = kernel.read_skill_sop("non_existent")
    assert "Error: Skill 'non_existent' not found" in error_sop


@pytest.mark.asyncio
async def test_skill_context_can_list_its_own_bundled_scripts():
    create_mock_skill_with_script("bundled_skill", "Bundled skill desc", TEST_BUNDLED_SKILLS)
    kernel = FerrymanKernel(create_test_settings())
    kernel.scan_skills()
    skill = kernel.skills["bundled_skill"]

    ctx = SimpleNamespace(deps=AgentDeps(kernel=kernel, session_id="skill-session", skill_name="bundled_skill"))

    result = await FileToolkit.list_files(ctx, str(skill.path / "scripts"))

    assert "fetch.py" in result


@pytest.mark.asyncio
async def test_skill_context_keeps_writes_inside_session_workspace():
    create_mock_skill_with_script("bundled_skill", "Bundled skill desc", TEST_BUNDLED_SKILLS)
    kernel = FerrymanKernel(create_test_settings())
    kernel.scan_skills()
    skill = kernel.skills["bundled_skill"]

    ctx = SimpleNamespace(deps=AgentDeps(kernel=kernel, session_id="skill-session", skill_name="bundled_skill"))

    with pytest.raises(ValueError, match="Path escapes session workspace"):
        await FileToolkit.write_file(ctx, str(skill.path / "scripts" / "generated.txt"), "nope")


# --- Publish Skill Tests ---
@pytest.mark.asyncio
async def test_publish_skill_moves_draft_and_registers_it():
    kernel = FerrymanKernel(create_test_settings())
    session_id = "publish-session"
    workspace = kernel.get_session_workspace(session_id)
    draft_dir = workspace / "draft-skill"
    create_draft_skill(draft_dir)

    ctx = SimpleNamespace(deps=AgentDeps(kernel=kernel, session_id=session_id))

    result = await SkillToolkit.publish_skill(ctx, "draft-skill")
    payload = json.loads(result)

    published_dir = TEST_USER_SKILLS / "draft-skill"
    assert payload["ok"] is True
    assert payload["skill_name"] == "draft-skill"
    assert payload["registered"] is True
    assert published_dir.exists()
    assert not draft_dir.exists()
    assert "draft-skill" in kernel.skills


@pytest.mark.asyncio
async def test_publish_skill_rejects_paths_outside_workspace():
    kernel = FerrymanKernel(create_test_settings())
    session_id = "publish-session"
    outside_dir = TEST_ROOT / "outside-skill"
    create_draft_skill(outside_dir, name="outside-skill")

    ctx = SimpleNamespace(deps=AgentDeps(kernel=kernel, session_id=session_id))

    with pytest.raises(RuntimeError, match="inside the current session workspace"):
        await SkillToolkit.publish_skill(ctx, str(outside_dir))


@pytest.mark.asyncio
async def test_skill_creator_draft_publish_lifecycle_stays_in_allowed_paths():
    shutil.copytree(REPO_ROOT / "skills" / "skill-creator", TEST_BUNDLED_SKILLS / "skill-creator")
    kernel = FerrymanKernel(create_test_settings())
    kernel.scan_skills()

    session_id = "creator-session"
    workspace = kernel.get_session_workspace(session_id)
    creator_ctx = SimpleNamespace(deps=AgentDeps(kernel=kernel, session_id=session_id, skill_name="skill-creator"))

    init_result = json.loads(
        await CommandToolkit.run_skill_script(
            creator_ctx,
            "init_skill.py",
            ["demo-skill", "--description", "Demo skill", "--with-scripts"],
        )
    )
    draft_dir = workspace / "demo-skill"

    assert init_result["ok"] is True
    assert draft_dir.exists()
    assert "SKILL.md" in await FileToolkit.list_files(creator_ctx, "demo-skill")

    validate_result = json.loads(
        await CommandToolkit.run_skill_script(creator_ctx, "quick_validate.py", ["./demo-skill"])
    )
    assert validate_result["ok"] is True

    publish_result = json.loads(await SkillToolkit.publish_skill(creator_ctx, "demo-skill"))
    published_dir = TEST_USER_SKILLS / "demo-skill"

    assert publish_result["ok"] is True
    assert not draft_dir.exists()
    assert published_dir.exists()
    assert kernel.skills["demo-skill"].path == published_dir

    published_ctx = SimpleNamespace(deps=AgentDeps(kernel=kernel, session_id=session_id, skill_name="demo-skill"))
    assert "SKILL.md" in await FileToolkit.list_files(published_ctx, str(published_dir))


# --- Script Level Tests (Creator Scripts) ---
def test_init_skill_creates_draft_structure(tmp_path):
    output_dir = tmp_path / "workspace"
    result = subprocess.run(
        [
            sys.executable,
            str(INIT_SCRIPT),
            "demo-skill",
            "--description",
            "Demo trigger description",
            "--output-dir",
            str(output_dir),
            "--with-scripts",
            "--with-references",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    draft_dir = output_dir / "demo-skill"
    assert result.stdout.strip() == str(draft_dir)
    skill_md = draft_dir / "SKILL.md"
    assert skill_md.exists()
    skill_content = skill_md.read_text(encoding="utf-8")
    assert "version: 0.1.0" in skill_content
    assert "author: Ferryman" in skill_content
    assert f"created: {date.today().isoformat()}" in skill_content
    assert f"updated: {date.today().isoformat()}" in skill_content
    assert (draft_dir / "scripts").is_dir()
    assert (draft_dir / "references").is_dir()


def test_quick_validate_accepts_valid_skill(tmp_path):
    draft_dir = tmp_path / "demo-skill"
    draft_dir.mkdir()
    (draft_dir / "SKILL.md").write_text(
        """---
name: demo-skill
description: Demo trigger description
version: 0.1.0
author: Ferryman
created: 2026-04-14
updated: 2026-04-14
---
# Demo Skill
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(VALIDATE_SCRIPT), str(draft_dir)],
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["metadata"]["name"] == "demo-skill"
    assert payload["metadata"]["version"] == "0.1.0"
    assert payload["metadata"]["created"] == "2026-04-14"
    assert payload["metadata"]["updated"] == "2026-04-14"


def test_quick_validate_rejects_name_mismatch(tmp_path):
    draft_dir = tmp_path / "wrong-folder"
    draft_dir.mkdir()
    (draft_dir / "SKILL.md").write_text(
        """---
name: demo-skill
description: Demo trigger description
version: 0.1.0
author: Ferryman
created: 2026-04-14
updated: 2026-04-14
---
# Demo Skill
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(VALIDATE_SCRIPT), str(draft_dir)],
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["ok"] is False
    assert any("Directory name" in item for item in payload["errors"])


# --- Skill Loading Utils Tests ---
from app.core.utils import load_skill_from_directory
from app.models.schemas import SkillModel

def test_load_skill_from_directory_success(tmp_path):
    """Test loading a valid skill with YAML frontmatter."""
    skill_dir = tmp_path / "test_skill"
    skill_dir.mkdir()
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text("""---
name: Test Skill
description: A mock skill for testing
version: 1.0.0
author: Antigravity
---
# SOP
Perform some test actions.
""", encoding="utf-8")

    skill = load_skill_from_directory(skill_dir)
    assert skill is not None
    assert isinstance(skill, SkillModel)
    assert skill.name == "Test Skill"
    assert skill.version == "1.0.0"
    assert skill.path == skill_dir

def test_load_skill_from_directory_no_md(tmp_path):
    """Verify it returns None if SKILL.md is missing."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    assert load_skill_from_directory(empty_dir) is None

def test_load_skill_from_directory_invalid_yaml(tmp_path):
    """Verify it handles invalid YAML gracefully."""
    bad_dir = tmp_path / "bad_skill"
    bad_dir.mkdir()
    (bad_dir / "SKILL.md").write_text("---\nname: [unclosed bracket\n---", encoding="utf-8")
    
    assert load_skill_from_directory(bad_dir) is None
