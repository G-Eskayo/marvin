#!/usr/bin/env python3
"""Orchestrate the research colony: fetch → correlate → digest."""
import sys
from datetime import date, datetime
from pathlib import Path

# Ensure the scripts dir is importable regardless of cwd
_SCRIPTS = Path(__file__).parent
sys.path.insert(0, str(_SCRIPTS))

import source_monitor
import correlate
import research_digest

sys.path.insert(0, str(Path.home() / ".agents" / "lib"))
import brief_fallback  # noqa: E402


def main(now: datetime | None = None) -> int:
    # Gate on should_run before fetching — no point fetching if digest already exists
    today = date.today().isoformat()
    digest_path = research_digest.DIGEST_DIR / f"{today}.md"
    should_fetch, reason = brief_fallback.should_run(digest_path, usual_hour=9, usual_minute=0, now=now)

    if not should_fetch:
        print(f"[colony] {reason}", file=sys.stderr)
        return 0

    print("[colony] === source monitor ===", file=sys.stderr)
    source_monitor.main()

    print("[colony] === correlation engine ===", file=sys.stderr)
    correlated = correlate.correlate()

    print("[colony] === digest generator ===", file=sys.stderr)
    out = research_digest.generate(now=now)

    if out:
        print(f"[colony] done — digest at {out}", file=sys.stderr)
    else:
        print("[colony] done — no digest written (no items or already exists)", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
