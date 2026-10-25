#!/usr/bin/env python3
"""Orchestrate the research colony: fetch → correlate → digest."""
import sys
from datetime import date
from pathlib import Path

# Ensure the scripts dir is importable regardless of cwd
_SCRIPTS = Path(__file__).parent
sys.path.insert(0, str(_SCRIPTS))

sys.path.insert(0, str(Path.home() / ".agents" / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import brief_fallback  # noqa: E402

import source_monitor
import correlate
import research_digest


def main() -> int:
    # Gate: check if this machine should run the colony (fallback gate for Mini-only primary builder)
    today = date.today().isoformat()
    research_digest_path = research_digest.DIGEST_DIR / f"{today}.md"
    decision = brief_fallback.should_run(local_path=research_digest_path, usual_hour=9, usual_minute=0)
    if not decision.should_build:
        print(f"[colony] {decision.reason} — skipping", file=sys.stderr)
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
