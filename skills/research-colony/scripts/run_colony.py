#!/usr/bin/env python3
"""Orchestrate the research colony: fetch → correlate → digest."""
import sys
from datetime import date
from pathlib import Path

# Ensure the scripts dir is importable regardless of cwd
_SCRIPTS = Path(__file__).parent
sys.path.insert(0, str(_SCRIPTS))

import source_monitor
import correlate
import research_digest

sys.path.insert(0, str(Path.home() / ".agents" / "lib"))
import brief_fallback  # noqa: E402


def main() -> int:
    # Fallback builder check (ADR 0067): check if primary builder already produced
    # today's digest, and don't run the colony if it did. This avoids duplicate
    # work and race conditions from two builders competing.
    today = date.today().isoformat()
    out_path = research_digest.today_path()

    if brief_fallback.produced(today, str(out_path)):
        print("[colony] primary builder already produced today's digest — skipping", file=sys.stderr)
        return 0

    # Check if we should build (are we the fallback, and should we act?)
    should_build_it, reason = brief_fallback.should_build(today, str(out_path))
    if not should_build_it:
        print(f"[colony] skipping (not our job: {reason})", file=sys.stderr)
        return 0

    print("[colony] === source monitor ===", file=sys.stderr)
    source_monitor.main()

    print("[colony] === correlation engine ===", file=sys.stderr)
    correlated = correlate.correlate()

    print("[colony] === digest generator ===", file=sys.stderr)
    out = research_digest.generate()

    if out:
        brief_fallback.mark_built(str(research_digest.DIGEST_DIR), today, reason)
        print(f"[colony] done — digest at {out}", file=sys.stderr)
    else:
        print("[colony] done — no digest written (no items or already exists)", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
