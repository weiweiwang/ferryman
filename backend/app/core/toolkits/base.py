from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Sequence


class Toolkit(ABC):
    """Base contract for tool groups registered with the agent runtime."""

    @staticmethod
    @abstractmethod
    def get_tools() -> Sequence[Callable[..., Awaitable[object]]]:
        """Return tool functions to register on an agent."""
