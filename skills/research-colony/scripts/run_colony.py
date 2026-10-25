#!/usr/bin/env python3
"""Orchestrate the research colony: fetch → correlate → digest."""
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure the scripts dir is importable regardless of cwd
_SCRIPTS = Path(__file__).parent
sys.path.insert(0, str(_SCRIPTS))

sys.path.insert(0, str(Path.home() / ".agents" / "lib"))
import brief_fallback  # noqa: E402
import machine_profile  # noqa: E402

import source_monitor
import correlate
import research_digest

DIGEST_DIR = Path.home() / ".claude" / "research-digest"


def main() -> int:
    # Fallback builder check
    today = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    out_path = DIGEST_DIR / f"{today}.md"
    decision = brief_fallback.should_run(local_path=out_path, usual_hour=9, usual_minute=0)
    if not decision.should_build:
        print(f"[colony] {decision.reason} — skipping", file=sys.stderr)
        return 0

    # Short-circuit if today's digest already exists with valid content
    if out_path.exists() and brief_fallback.produced(out_path):
        print(f"[colony] Digest already produced — skipping fetch/correlate", file=sys.stderr)
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
