"""The north stars, read from their single source: docs/north-stars.md (marvin#274, ADR 0059).

Any prompt that states the north stars gets them from here, never from a copy, so a change to
the doc reaches every reader at once. A missing file raises: a prompt silently missing its
north stars is the drift this module exists to prevent.
"""
from __future__ import annotations

from pathlib import Path

NORTH_STARS_DOC = Path(__file__).resolve().parents[1] / "docs" / "north-stars.md"


def load(path: Path = NORTH_STARS_DOC) -> str:
    """The doc from its first section on: the title and the note to editors are left out."""
    text = Path(path).read_text()
    start = text.find("\n## ")
    return text[start + 1:].strip() if start != -1 else text.strip()
