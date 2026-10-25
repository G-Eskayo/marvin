#!/usr/bin/env python3
"""Orchestrate the research colony: fetch → correlate → digest."""
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure the scripts dir is importable regardless of cwd
_SCRIPTS = Path(__file__).parent
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(Path.home() / ".agents" / "lib"))

import source_monitor
import correlate
import research_digest
import job_ownership  # noqa: E402


def main() -> int:
    now = datetime.now(timezone.utc)

    # Single gate at the top: if the digest already exists, we're done
    if research_digest.digest_path(now).exists():
        print("[colony] research digest already exists for today", file=sys.stderr)
        return 0

    # Early gate (ADR 0067): skip entire pipeline if not primary, before deadline, or if Mini already has real output
    is_primary = job_ownership.is_primary()
    past_deadline = job_ownership.past_deadline(9, 0, now)  # usual time 09:00

    if is_primary:
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
    elif not past_deadline:
        print("[colony] not primary machine and before deadline — skipping", file=sys.stderr)
        return 0
    else:
        # Fallback path: check if Mini has real output
        mini_out = job_ownership.mini_output("research-digest/" + datetime.now(timezone.utc).strftime("%Y-%m-%d") + ".md")
        if mini_out:
            print("[colony] primary machine has real output — skipping fallback build", file=sys.stderr)
            return 0

        print("[colony] === fallback build (primary past deadline or missing) ===", file=sys.stderr)
        source_monitor.main()
        correlated = correlate.correlate()
        out = research_digest.generate()

        if out:
            print(f"[colony] fallback done — digest at {out}", file=sys.stderr)
        else:
            print("[colony] fallback done — no digest written", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
