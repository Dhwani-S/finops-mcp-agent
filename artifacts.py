"""Content-addressable artifact store for large tool results.

When a tool returns a result larger than the context threshold, the full
text is stored here and a short descriptor + handle goes into the LLM
context.  This saves tokens while preserving the full data for downstream
tools (e.g. summarize_data with artifact_id).

Storage layout:
    state/artifacts/<sha256-prefix>.txt   — raw text content
    state/artifacts/<sha256-prefix>.json  — metadata (source, size, created_at)

Handles are strings of the form ``art:<16-char-hex>``.  Identical content
deduplicates automatically (content-addressed).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

STORE_DIR = Path(__file__).resolve().parent / "state" / "artifacts"
STORE_DIR.mkdir(parents=True, exist_ok=True)

# Preview length embedded in the descriptor that goes into LLM context.
_PREVIEW_CHARS = 500


def put(text: str, *, source: str, descriptor: str) -> str:
    """Store text content (deduped by SHA-256).  Returns artifact handle."""
    content_bytes = text.encode("utf-8")
    digest = hashlib.sha256(content_bytes).hexdigest()[:16]
    art_id = f"art:{digest}"

    txt_path = STORE_DIR / f"{digest}.txt"
    meta_path = STORE_DIR / f"{digest}.json"

    if not txt_path.exists():
        txt_path.write_text(text, encoding="utf-8")
        meta = {
            "id": art_id,
            "size_bytes": len(content_bytes),
            "source": source,
            "descriptor": descriptor,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    return art_id


def get_text(artifact_id: str) -> str:
    """Retrieve stored text by artifact handle."""
    digest = artifact_id.removeprefix("art:")
    path = STORE_DIR / f"{digest}.txt"
    if not path.exists():
        raise FileNotFoundError(f"Artifact {artifact_id} not found")
    return path.read_text(encoding="utf-8")


def exists(artifact_id: str) -> bool:
    digest = artifact_id.removeprefix("art:")
    return (STORE_DIR / f"{digest}.txt").exists()


def clear() -> None:
    """Remove all stored artifacts."""
    for f in STORE_DIR.glob("*"):
        f.unlink()
