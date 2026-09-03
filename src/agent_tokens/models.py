"""Data models for token usage across coding agents."""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any


@dataclass
class TokenStats:
    """Model-level token usage aggregation.

    ``total_tokens`` counts every token category the trackers record:
    input + output + reasoning + cache reads + cache writes. Reasoning
    tokens are counted separately because several providers report them
    outside of output tokens; including them keeps grand totals honest.
    """

    model_id: str
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    session_count: int = 0
    turn_count: int = 0
    last_active: Optional[str] = None

    def __post_init__(self) -> None:
        # Coerce ``None``/float artefacts from DB/JSON rows to clean ints.
        for f in (
            "input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "cache_read_tokens",
            "cache_write_tokens",
            "session_count",
            "turn_count",
        ):
            v = getattr(self, f)
            if v is None:
                setattr(self, f, 0)
            elif isinstance(v, float):
                setattr(self, f, int(v))

    @property
    def total_tokens(self) -> int:
        """Total tokens moved (input + output + reasoning + cache reads + cache writes)."""
        return (
            self.input_tokens
            + self.output_tokens
            + self.reasoning_tokens
            + self.cache_read_tokens
            + self.cache_write_tokens
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "total_tokens": self.total_tokens,
            "session_count": self.session_count,
            "turn_count": self.turn_count,
            "last_active": self.last_active,
        }


@dataclass
class SessionInfo:
    """Individual session metadata and token consumption."""

    session_id: str
    title: str
    model_id: str
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    turn_count: int = 0
    updated_at: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.title:
            self.title = self.session_id[:18] if self.session_id else "untitled"
        if not self.model_id:
            self.model_id = "unknown"
        for f in (
            "input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "cache_read_tokens",
            "cache_write_tokens",
            "turn_count",
        ):
            v = getattr(self, f)
            if v is None:
                setattr(self, f, 0)
            elif isinstance(v, float):
                setattr(self, f, int(v))

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.reasoning_tokens
            + self.cache_read_tokens
            + self.cache_write_tokens
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "title": self.title,
            "model_id": self.model_id,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "turn_count": self.turn_count,
            "total_tokens": self.total_tokens,
            "updated_at": self.updated_at,
        }


@dataclass
class AgentReport:
    """Agent-level token usage aggregation report."""
    agent_name: str
    models: List[TokenStats] = field(default_factory=list)
    recent_sessions: List[SessionInfo] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return sum(m.total_tokens for m in self.models)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "total_tokens": self.total_tokens,
            "models": [m.to_dict() for m in self.models],
            "recent_sessions": [s.to_dict() for s in self.recent_sessions],
        }
