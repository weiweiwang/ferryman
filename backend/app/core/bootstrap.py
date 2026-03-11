import logging
from app.core.config import SystemConfig
from app.core.db import init_db

logger = logging.getLogger(__name__)

def init_env(settings: SystemConfig):
    """
    Ensures the core directory structure and basic files exist.
    This should be called during application startup.
    """
    sub_dirs = [
        *settings.skills_dir,
        settings.user_dir / "reports",
        settings.user_dir / "tasks",
        settings.user_dir / "logs",
        settings.user_dir / "workspaces"
    ]
    
    for sd in sub_dirs:
        if not sd.exists():
            sd.mkdir(parents=True, exist_ok=True)
            logger.info(f"📁 Created directory: {sd}")
    
    # Initialize DB tables
    init_db()
