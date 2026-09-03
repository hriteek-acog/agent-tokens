"""Abstract base provider for reading agent token statistics."""

from abc import ABC, abstractmethod
from typing import Optional
from agent_tokens.models import AgentReport


class BaseProvider(ABC):
    """Abstract interface that every agent token provider must implement."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name of the agent (e.g. OpenCode, Claude Code)."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the agent data store exists on the current host."""
        pass

    @abstractmethod
    def get_report(self, today_only: bool = False) -> Optional[AgentReport]:
        """Collect and return the AgentReport for the requested timeframe."""
        pass
