#!/usr/bin/env python3
"""Orchestrate the research colony: fetch → correlate → digest."""
import sys
from datetime import date
from pathlib import Path

# Ensure the scripts dir is importable regardless of cwd
_SCRIPTS = Path(__file__).parent
sys.path.insert(0, str(_SCRIPTS))

sys.path.insert(0, str(Path.home() / ".agents" / "lib"))
import brief_fallback  # noqa: E402

import source_monitor
import correlate
import research_digest


def main() -> int:
    # Gate on the fallback builder's decision (primary on mini at 09:00, grace +60min)
    today = date.today().isoformat()
    digest_path = Path.home() / ".claude" / "research-digest" / f"{today}.md"

    # Check if already produced locally
    if brief_fallback.produced(digest_path):
        print(f"[colony] Today's digest already exists: {digest_path}", file=sys.stderr)
        return 0

    should_run, reason = brief_fallback.should_run(digest_path, usual_hour=9, usual_minute=0)
    if not should_run:
        print(f"[colony] Fallback gated: {reason}", file=sys.stderr)
        return 0

    print("[colony] === source monitor ===", file=sys.stderr)
    source_monitor.main()

    print("[colony] === correlation engine ===", file=sys.stderr)
    correlated = correlate.correlate()

    print("[colony] === digest generator ===", file=sys.stderr)
    out = research_digest.generate()

    if out:
        print(f"[colony] done — digest at {out}", file=sys.stderr)
    else:
        print("[colony] done — no digest written (no items or already exists)", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
