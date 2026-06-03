"""Memory: a typed service for persistent user context.

Adapted from the Session 6 architecture. Stores facts and preferences
that survive across chat sessions. When a user says "I work on team
Platform Engineering" or accepts "org-wide" scope, that context persists
so the next conversation can start scoped without re-asking.

Three kinds of memory items:
    fact        — observed truth (e.g., "user's team is Platform Engineering")
    preference  — user-stated preference (e.g., "prefers GCP cost metric: cost_with_credits")
    scratchpad  — session-scoped working note (cleared on session reset)

Reads are pure keyword overlap — no LLM call, no embedding.
Writes for facts/preferences are deterministic (kind is known upfront).

Persistence: state/memory.json — survives process restarts.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

MemoryKind = Literal["fact", "preference", "scratchpad"]


class MemoryItem(BaseModel):
    """One record in memory."""

    id: str
    kind: MemoryKind
    keywords: list[str] = Field(default_factory=list)
    descriptor: str
    value: dict = Field(default_factory=dict)
    source: str = ""
    session_id: str = ""
    confidence: float = 1.0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

STATE_PATH = Path(__file__).resolve().parent / "state" / "memory.json"
STATE_PATH.parent.mkdir(parents=True, exist_ok=True)

_STOPWORDS = {
    "the", "is", "a", "an", "of", "to", "and", "or", "in", "on", "for", "at",
    "with", "by", "from", "what", "how", "when", "where", "why", "this", "that",
    "it", "be", "as", "are", "was", "were", "i", "you", "me", "my", "your",
    "show", "me", "give", "tell", "get", "find", "please", "can", "do",
}


def _tokens(text: str) -> set[str]:
    return {
        w for w in re.findall(r"\w+", text.lower())
        if w not in _STOPWORDS and len(w) > 2
    }


def _load() -> list[MemoryItem]:
    if not STATE_PATH.exists():
        return []
    try:
        raw = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return [MemoryItem.model_validate(r) for r in raw]
    except (json.JSONDecodeError, Exception):
        return []


def _save(items: list[MemoryItem]) -> None:
    STATE_PATH.write_text(
        json.dumps([i.model_dump(mode="json") for i in items], indent=2),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Reads — pure keyword search, zero LLM cost
# ---------------------------------------------------------------------------

def read(
    query: str,
    *,
    kinds: list[str] | None = None,
    top_k: int = 5,
) -> list[MemoryItem]:
    """Return memory items relevant to the query, ranked by keyword overlap."""
    items = _load()
    if kinds:
        items = [i for i in items if i.kind in kinds]
    if not items:
        return []

    qtoks = _tokens(query)
    scored: list[tuple[int, MemoryItem]] = []
    for item in items:
        itoks = {w.lower() for w in item.keywords} | _tokens(item.descriptor)
        score = len(qtoks & itoks)
        if score > 0:
            scored.append((score, item))

    scored.sort(key=lambda x: -x[0])
    return [i for _, i in scored[:top_k]]


def read_all(*, kinds: list[str] | None = None) -> list[MemoryItem]:
    """Return all items, optionally filtered by kind. Used for injecting
    preferences into the system prompt context."""
    items = _load()
    if kinds:
        items = [i for i in items if i.kind in kinds]
    return items


# ---------------------------------------------------------------------------
# Writes — deterministic, zero LLM cost
# ---------------------------------------------------------------------------

def remember(
    descriptor: str,
    *,
    kind: MemoryKind = "fact",
    value: dict | None = None,
    keywords: list[str] | None = None,
    source: str = "agent",
    session_id: str = "",
) -> MemoryItem:
    """Write a typed memory item. Deduplicates by descriptor similarity."""
    kw = [k.lower() for k in (keywords or list(_tokens(descriptor))[:10])]

    # Dedup: if a very similar item exists, update it instead of duplicating
    items = _load()
    for existing in items:
        if existing.kind == kind and existing.descriptor == descriptor:
            # Exact duplicate — skip
            return existing

    item = MemoryItem(
        id=f"mem:{uuid4().hex[:8]}",
        kind=kind,
        keywords=kw,
        descriptor=descriptor,
        value=value or {},
        source=source,
        session_id=session_id,
        confidence=1.0,
    )
    items.append(item)
    _save(items)
    return item


def remember_preference(
    key: str,
    value: str,
    *,
    source: str = "user",
    session_id: str = "",
) -> MemoryItem:
    """Store or update a user preference (e.g., team, default cloud, scope).
    If a preference with the same key exists, it is replaced."""
    items = _load()

    # Remove old preference with same key
    items = [i for i in items if not (
        i.kind == "preference" and i.value.get("key") == key
    )]

    item = MemoryItem(
        id=f"mem:{uuid4().hex[:8]}",
        kind="preference",
        keywords=[key.lower(), value.lower()] + list(_tokens(value)),
        descriptor=f"User preference: {key} = {value}",
        value={"key": key, "value": value},
        source=source,
        session_id=session_id,
        confidence=1.0,
    )
    items.append(item)
    _save(items)
    return item


def get_preference(key: str) -> str | None:
    """Look up a specific preference by key. Returns the value or None."""
    for item in _load():
        if item.kind == "preference" and item.value.get("key") == key:
            return item.value.get("value")
    return None


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

def clear_session(session_id: str) -> int:
    """Remove scratchpad items from a specific session. Returns count removed."""
    items = _load()
    before = len(items)
    items = [i for i in items if not (
        i.kind == "scratchpad" and i.session_id == session_id
    )]
    _save(items)
    return before - len(items)


def clear_all() -> None:
    """Wipe all persistent memory. Use between clean resets."""
    _save([])
