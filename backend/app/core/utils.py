import yaml
import logging
from pathlib import Path
from typing import Optional
from app.models.schemas import SkillModel

logger = logging.getLogger(__name__)

def load_skill_from_directory(directory: Path) -> Optional[SkillModel]:
    """Parse SKILL.md YAML frontmatter and return a SkillModel."""
    skill_md_path = directory / "SKILL.md"
    if not skill_md_path.exists():
        return None

    try:
        content = skill_md_path.read_text(encoding="utf-8")
        metadata = {}
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                metadata = yaml.safe_load(parts[1]) or {}
        
        return SkillModel(
            name=metadata.get("name", directory.name),
            description=metadata.get("description", ""),
            path=directory,
            version=metadata.get("version", "0.1.0"),
            author=metadata.get("author", "Unknown"),
            created=str(metadata.get("created")) if metadata.get("created") else None,
            updated=str(metadata.get("updated")) if metadata.get("updated") else None,
        )
    except Exception as e:
        logger.error(f"Error loading skill from {directory}: {e}")
    return None
