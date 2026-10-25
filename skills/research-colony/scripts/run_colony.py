#!/usr/bin/env python3
"""Orchestrate the research colony: fetch → correlate → digest."""
import sys
from pathlib import Path
from datetime import datetime, timezone

# Ensure the scripts dir is importable regardless of cwd
_SCRIPTS = Path(__file__).parent
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(Path.home() / ".agents" / "lib"))

import source_monitor
import correlate
import research_digest
import brief_fallback  # noqa: E402


def main() -> int:
    from datetime import date

    # Fallback gate: check if the research digest should be built
    today = date.today().isoformat()
    out_path = Path.home() / ".claude" / "research-digest" / f"{today}.md"
    now = datetime.now(timezone.utc)

    decision = brief_fallback.should_run(out_path, usual_hour=9, usual_minute=0, now=now)
    if not decision.should_run:
        print(f"[colony] Skipping: {decision.reason}", file=sys.stderr)
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
