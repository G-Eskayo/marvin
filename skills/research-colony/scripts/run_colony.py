#!/usr/bin/env python3
"""Orchestrate the research colony: fetch → correlate → digest."""
import sys
from datetime import date
from pathlib import Path

# Ensure the scripts dir is importable regardless of cwd
_SCRIPTS = Path(__file__).parent
sys.path.insert(0, str(_SCRIPTS))

# Add lib to path for brief_fallback import
sys.path.insert(0, str(Path.home() / ".agents" / "lib"))

import source_monitor
import correlate
import research_digest
import brief_fallback  # noqa: E402


def main() -> int:
    # Fallback gate: primary (mini) always builds; laptop only builds if primary is silent
    today = date.today().isoformat()
    local_path = research_digest.DIGEST_DIR / f"{today}.md"
    decision = brief_fallback.should_run(local_path=local_path, usual_hour=9, usual_minute=0)
    if not decision.should_build:
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
