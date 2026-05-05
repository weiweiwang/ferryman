from datetime import datetime

from pydantic_ai.tools import RunContext

from app.core.deps import AgentDeps
from app.core.toolkits.base import Toolkit


class TimeToolkit(Toolkit):
    """Return the current time in ISO 8601 format."""

    @staticmethod
    def get_tools():
        return [TimeToolkit.get_current_time]

    @staticmethod
    async def get_current_time(ctx: RunContext[AgentDeps]) -> str:
        """Return the current local datetime as an ISO 8601 string."""
        del ctx
        return datetime.now().astimezone().isoformat()
