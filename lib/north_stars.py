"""The north stars, read from their single source: docs/north-stars.md (marvin#274, ADR 0059).

Any prompt that states the north stars gets them from here, never from a copy, so a change to
the doc reaches every reader at once. A missing file raises: a prompt silently missing its
north stars is the drift this module exists to prevent.
"""
from __future__ import annotations

import re
from pathlib import Path

NORTH_STARS_DOC = Path(__file__).resolve().parents[1] / "docs" / "north-stars.md"


def load(path: Path = NORTH_STARS_DOC) -> str:
    """The doc from its first section on: the title and the note to editors are left out."""
    text = Path(path).read_text()
    start = text.find("\n## ")
    return text[start + 1:].strip() if start != -1 else text.strip()


def titles(path: Path = NORTH_STARS_DOC) -> list[str]:
    """Each north star's bold title, in order, without its closing full stop (for labels such as the job catalog's)."""
    return [m.group(1).rstrip(".") for m in re.finditer(r"^\d+\. \*\*(.+?)\*\*", Path(path).read_text(), re.M)]


def delegation_preamble(repo: str | None = None) -> str:
    """The standard opening of any design/fix work handed to another agent (marvin#556: #554 was built by a delegated
    agent that never read CONTEXT.md "Triggers over polling"). Short on purpose: it rides on every delegated prompt."""
    where = f"{repo}'s" if repo else "the target repo's"
    return (
        "Required reading before designing: ~/.agents/docs/north-stars.md, and "
        f"{where} CONTEXT.md decisions (and docs/adr/) for every area you touch. A design that contradicts a "
        "recorded decision is a defect: if you think the decision is wrong, say so rather than work around it. "
        "Search for an existing pattern to reuse before writing anything new. Your plan or report must state which "
        "existing pattern you reused (file and function), or why none fit."
    )


def main(argv: list[str] | None = None) -> int:
    """`north_stars.py preamble [owner/repo]` prints the delegation preamble (for shell callers like dispatch_ticket.sh)."""
    import sys
    args = sys.argv[1:] if argv is None else argv
    if not args or args[0] != "preamble":
        print("usage: north_stars.py preamble [owner/repo]", file=sys.stderr)
        return 2
    print(delegation_preamble(args[1] if len(args) > 1 else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
