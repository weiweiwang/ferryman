import pytest
from pathlib import Path
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
