#!/usr/bin/env python3
"""PostToolUse hook: when a handoff doc is written to ~/.claude/handoffs/, extract
its '## Resume prompt' section and print a paste-ready block. Deterministic — fires
even if the model forgets to surface it (the 'wire it as a hook, don't trust prose'
principle). Never errors the originating tool: any failure exits silently.

It also stamps the handoff's front matter when it has none (marvin#1221): `as_of` now (a live session writes its
handoff at its last activity), `machine`, `session`, `source: skill`. The resume check dates handoffs by it, not by
mtime. An existing stamp (a rebuilt handoff's transcript date) is never overwritten here.
"""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".agents" / "lib"))
try:
    import resume_check
    from machine_profile import machine_label
except Exception:  # noqa: BLE001  (never errors the originating tool)
    resume_check = None

    def machine_label():
        return None


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return

    if payload.get("tool_name", "") not in ("Write", "Edit", "MultiEdit"):
        return
    fp = (payload.get("tool_input") or {}).get("file_path", "")
    if not fp:
        return

    p = Path(fp)
    handoff_dir = Path.home() / ".claude" / "handoffs"
    try:
        in_handoffs = handoff_dir.resolve() in [d.resolve() for d in p.parents]
    except Exception:
        in_handoffs = False
    if not in_handoffs or p.suffix.lower() != ".md":
        return

    if resume_check is not None:
        try:
            resume_check.stamp(p, as_of=datetime.now(timezone.utc), machine=machine_label(),
                               session=payload.get("session_id"), source="skill")
        except Exception:  # noqa: BLE001
            pass

    try:
        text = p.read_text(errors="ignore")
    except Exception:
        return

    m = re.search(r"##\s*Resume prompt\s*\n(.*)$", text, re.DOTALL | re.IGNORECASE)
    body = (m.group(1) if m else "").strip().strip("-").strip()
    if not body:
        body = f"Continue from handoff: {fp}"

    bar = "=" * 64
    print(f"\n{bar}\n📋 RESUME PROMPT — paste into your next session to continue:\n{bar}")
    print(body)
    print(f"{bar}\n(source: {fp})")


if __name__ == "__main__":
    main()
