from app.core.config import Settings
from app.core.skill_manager import SkillManager


def test_skill_manager_scans_and_reads_skills(tmp_path, monkeypatch):
    bundled = tmp_path / "bundled" / "skills"
    user_skills = tmp_path / "user" / "skills"
    skill_dir = user_skills / "seo_matrix"
    skill_dir.mkdir(parents=True)
    (bundled).mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: seo_matrix
description: Build SEO content clusters
---
# SOP
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("FERRYMAN_BUNDLED_SKILLS_DIR", str(bundled))

    manager = SkillManager(Settings(root_dir=tmp_path))
    manager.scan_skills()

    assert "seo_matrix" in manager.skills
    assert "- seo_matrix: Build SEO content clusters" in manager.get_skill_index_text()
    sop = manager.read_skill_sop("seo_matrix")
    assert sop == "# SOP"
    assert "name: seo_matrix" not in sop
    assert "description:" not in sop
    assert manager.read_skill_sop("missing") == "Error: Skill 'missing' not found."
