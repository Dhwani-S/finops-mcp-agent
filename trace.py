"""
Pydantic models for structured agent tracing.

Captures tool calls, results, token usage, and timing per turn.
Enable/disable via TOKEN_TRACKING env var or agent.set_token_tracking().
"""

from __future__ import annotations

import time
from pydantic import BaseModel, Field


class ToolCallTrace(BaseModel):
    """A single tool invocation within a turn."""

    tool: str
    server: str
    args: dict = Field(default_factory=dict)
    result_chars: int = 0
    truncated: bool = False
    error: str | None = None
    duration_ms: float = 0.0


class TokenUsage(BaseModel):
    """Token counts from a single Gemini response."""

    prompt_tokens: int = 0
    response_tokens: int = 0
    total_tokens: int = 0


class TurnTrace(BaseModel):
    """One round of the agentic loop (LLM call + tool executions)."""

    round: int
    tokens: TokenUsage = Field(default_factory=TokenUsage)
    tool_calls: list[ToolCallTrace] = Field(default_factory=list)
    has_text_response: bool = False
    duration_ms: float = 0.0


class SessionTrace(BaseModel):
    """Cumulative trace for the entire conversation session."""

    turns: list[TurnTrace] = Field(default_factory=list)
    total_prompt_tokens: int = 0
    total_response_tokens: int = 0
    total_tool_calls: int = 0

    def record_turn(self, turn: TurnTrace) -> None:
        """Add a completed turn and update cumulative totals."""
        self.turns.append(turn)
        self.total_prompt_tokens += turn.tokens.prompt_tokens
        self.total_response_tokens += turn.tokens.response_tokens
        self.total_tool_calls += len(turn.tool_calls)

    @property
    def total_tokens(self) -> int:
        return self.total_prompt_tokens + self.total_response_tokens

    @property
    def turn_count(self) -> int:
        return len(self.turns)

    def summary(self) -> dict:
        """Return a JSON-serializable summary."""
        return {
            "tracking_enabled": True,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_response_tokens": self.total_response_tokens,
            "total_tokens": self.total_tokens,
            "total_tool_calls": self.total_tool_calls,
            "turns": self.turn_count,
            "per_turn": [
                {
                    "round": t.round,
                    "prompt_tokens": t.tokens.prompt_tokens,
                    "response_tokens": t.tokens.response_tokens,
                    "total_tokens": t.tokens.total_tokens,
                    "tool_calls": len(t.tool_calls),
                    "tools_used": [tc.tool for tc in t.tool_calls],
                    "duration_ms": round(t.duration_ms, 1),
                    "cumulative_prompt": sum(
                        tr.tokens.prompt_tokens for tr in self.turns[:i + 1]
                    ),
                    "cumulative_response": sum(
                        tr.tokens.response_tokens for tr in self.turns[:i + 1]
                    ),
                }
                for i, t in enumerate(self.turns)
            ],
        }

    def clear(self) -> None:
        """Reset all trace data."""
        self.turns.clear()
        self.total_prompt_tokens = 0
        self.total_response_tokens = 0
        self.total_tool_calls = 0
