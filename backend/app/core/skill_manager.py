from __future__ import annotations

from datetime import date
import logging
from pathlib import Path

import frontmatter

from app.core.config import Settings
from app.models.schemas import SkillModel

logger = logging.getLogger(__name__)


class SkillManager:
    """Manage installed file-based Skills."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._skills: dict[str, SkillModel] = {}

    @property
    def skills(self) -> dict[str, SkillModel]:
        return self._skills

    @staticmethod
    def _parse_skill_date(value: object) -> date | None:
        if not value:
            return None
        if isinstance(value, date):
            return value
        return date.fromisoformat(str(value).strip())

    def load_skill_from_directory(self, directory: Path) -> SkillModel | None:
        """Parse a skill directory's SKILL.md metadata."""
        skill_md_path = directory / "SKILL.md"
        if not skill_md_path.exists():
            return None

        try:
            post = frontmatter.load(str(skill_md_path))
            metadata = {str(key): value for key, value in post.metadata.items()}
            name = metadata.get("name")
            description = metadata.get("description")
            version = metadata.get("version")
            author = metadata.get("author")
            created = metadata.get("created")
            updated = metadata.get("updated")

            return SkillModel(
                name=str(name) if name is not None else directory.name,
                description=str(description) if description is not None else "",
                path=directory,
                version=str(version) if version is not None else "0.1.0",
                author=str(author) if author is not None else "Unknown",
                created=self._parse_skill_date(created),
                updated=self._parse_skill_date(updated),
            )
        except Exception as e:
            logger.error(f"Error loading skill from {directory}: {e}")
        return None

    def scan_skills(self) -> None:
        for base in self._settings.skills_dir:
            if not base.exists():
                continue
            for item in base.iterdir():
                if item.is_dir():
                    skill = self.load_skill_from_directory(item)
                    if skill:
                        self._skills[skill.name] = skill
        logger.info(f"Scanned {len(self._skills)} skill(s)")

    def get_skill_index_text(self) -> str:
        if not self._skills:
            return "- No skills installed."
        lines = []
        for skill in self._skills.values():
            description = " ".join((skill.description or "").split())
            lines.append(f"- {skill.name}: {description}")
        return "\n".join(lines)

    def read_skill_sop(self, name: str) -> str:
        if name not in self._skills:
            return f"Error: Skill '{name}' not found."
        skill_md_path = Path(self._skills[name].path) / "SKILL.md"
        return frontmatter.load(str(skill_md_path)).content
