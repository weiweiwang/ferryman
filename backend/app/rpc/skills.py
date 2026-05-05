from __future__ import annotations

from jsonrpcserver import Success, method

from app.rpc.serializers import format_optional_date


@method
async def list_skills(context):
    if context and hasattr(context, "runtime"):
        skills = sorted(context.runtime.skill_manager.skills.values(), key=lambda skill: skill.name.lower())
        skills = sorted(
            skills,
            key=lambda skill: format_optional_date(getattr(skill, "updated", None)) or "",
            reverse=True,
        )
        return Success([
            {
                "name": skill.name,
                "description": skill.description,
                "version": skill.version,
                "author": skill.author,
                "created": format_optional_date(getattr(skill, "created", None)),
                "updated": format_optional_date(getattr(skill, "updated", None)),
            }
            for skill in skills
        ])

    return Success([])

