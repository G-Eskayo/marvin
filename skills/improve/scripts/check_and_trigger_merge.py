#!/usr/bin/env python3
"""Runs after any of MARVIN's daily per-machine agents finish on this
machine (daily-digest, research-colony — chained into each one's own
dispatch command, not a separate trigger). Checks whether the OTHER
machine has also gone idle; if so, triggers the cross-machine merge right
then — "last one out closes the door," event-driven, no fixed wait. If the
other machine is still busy, does nothing — its own copy of this same
check will catch the both-done condition when it finishes.

Originally built for research-colony alone (see
~/.agents/docs/adr/0014-research-colony-event-driven-merge-trigger.md);
moved here from research-colony/scripts/ 2026-07-09 when daily-digest
adopted the same pattern, since the logic was already fully generic — it
just checks dispatch-state and fires the shared cross_machine_merge.py,
nothing colony-specific about it. Design/rationale also in
~/.agents/CONTEXT.md's "Fan-out + merge (mode 2)" section.

cross_machine_merge.py's own merge step is already idempotent (skips if
today's merged file already exists) and already gracefully skips if either
side's output isn't ready — this script leans on that rather than
duplicating it. The only genuinely new logic here is *when* to call it.
"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".agents" / "lib"))
from machine_profile import load_or_build, remote_devices  # noqa: E402
from task_dispatch import _read_remote_dispatch_state, dispatch  # noqa: E402

MERGE_SCRIPT = Path.home() / ".agents" / "skills" / "improve" / "scripts" / "cross_machine_merge.py"
VENV_PYTHON = Path.home() / ".agents" / "venv" / "bin" / "python"
LOG_PREFIX = "[check-and-trigger-merge]"


def main() -> None:
    own_profile = load_or_build(max_age_hours=0)
    remotes = remote_devices()
    we_are_authority = own_profile.get("mobility_class") == "stationary"

    if not remotes:
        print(f"{LOG_PREFIX} no remotes registered — nothing to coordinate with", file=sys.stderr)
        return

    for remote_id, info in remotes.items():
        host = info.get("tailscale_hostname")
        if not host:
            continue
        state = _read_remote_dispatch_state(host)
        if state.get("busy"):
            print(f"{LOG_PREFIX} {remote_id} still running ({state.get('task', '?')}) — not triggering merge yet", file=sys.stderr)
            return

    print(f"{LOG_PREFIX} all known machines idle — triggering merge", file=sys.stderr)

    if we_are_authority:
        subprocess.run([str(VENV_PYTHON), str(MERGE_SCRIPT)])
        return

    # Not the authority ourselves — dispatch the merge run to whichever
    # remote is (mobility_class is only in each machine's own local
    # profile, not the shared registry, so ask: any remote not explicitly
    # known as non-stationary is assumed the authority target here since
    # today's topology is exactly two machines, one stationary).
    for remote_id in remotes:
        result = dispatch(
            f"cd {MERGE_SCRIPT.parent} && {VENV_PYTHON} {MERGE_SCRIPT}",
            target=remote_id, mode="async", task_label="cross-machine-merge (triggered)",
        )
        if result.ok:
            print(f"{LOG_PREFIX} dispatched merge run to {remote_id}", file=sys.stderr)
        else:
            print(f"{LOG_PREFIX} failed to dispatch merge run to {remote_id}: {result.error}", file=sys.stderr)


if __name__ == "__main__":
    main()
