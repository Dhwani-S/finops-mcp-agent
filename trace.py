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
    cached_tokens: int = 0
    total_tokens: int = 0


class TurnTrace(BaseModel):
    """One round of the agentic loop (LLM call + tool executions)."""

    round: int
    tokens: TokenUsage = Field(default_factory=TokenUsage)
    tool_calls: list[ToolCallTrace] = Field(default_factory=list)
    has_text_response: bool = False
    duration_ms: float = 0.0
    active_tools_count: int = 0
    routed_servers: list[str] = Field(default_factory=list)


class SessionTrace(BaseModel):
    """Cumulative trace for the entire conversation session."""

    turns: list[TurnTrace] = Field(default_factory=list)
    total_prompt_tokens: int = 0
    total_response_tokens: int = 0
    total_cached_tokens: int = 0
    total_tool_calls: int = 0

    def record_turn(self, turn: TurnTrace) -> None:
        """Add a completed turn and update cumulative totals."""
        self.turns.append(turn)
        self.total_prompt_tokens += turn.tokens.prompt_tokens
        self.total_response_tokens += turn.tokens.response_tokens
        self.total_cached_tokens += turn.tokens.cached_tokens
        self.total_tool_calls += len(turn.tool_calls)

    @property
    def total_tokens(self) -> int:
        return self.total_prompt_tokens + self.total_response_tokens

    @property
    def turn_count(self) -> int:
        return len(self.turns)

    def summary(self) -> dict:
        """Return a JSON-serializable summary."""
        total_duration = sum(t.duration_ms for t in self.turns)
        total_result_chars = sum(
            tc.result_chars for t in self.turns for tc in t.tool_calls
        )

        return {
            "tracking_enabled": True,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_response_tokens": self.total_response_tokens,
            "total_cached_tokens": self.total_cached_tokens,
            "total_tokens": self.total_tokens,
            "total_tool_calls": self.total_tool_calls,
            "total_duration_ms": round(total_duration, 1),
            "total_result_chars": total_result_chars,
            "turns": self.turn_count,
            "per_turn": [
                {
                    "round": t.round,
                    "prompt_tokens": t.tokens.prompt_tokens,
                    "response_tokens": t.tokens.response_tokens,
                    "cached_tokens": t.tokens.cached_tokens,
                    "total_tokens": t.tokens.total_tokens,
                    "tool_calls": len(t.tool_calls),
                    "tools_used": [tc.tool for tc in t.tool_calls],
                    "tool_details": [
                        {
                            "tool": tc.tool,
                            "server": tc.server,
                            "duration_ms": round(tc.duration_ms, 1),
                            "result_chars": tc.result_chars,
                            "result_tokens_est": tc.result_chars // 4,
                            "truncated": tc.truncated,
                            "error": tc.error,
                        }
                        for tc in t.tool_calls
                    ],
                    "duration_ms": round(t.duration_ms, 1),
                    "active_tools_count": t.active_tools_count,
                    "routed_servers": t.routed_servers,
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
        self.total_cached_tokens = 0
        self.total_tool_calls = 0
