#!/usr/bin/env python3
"""PostToolUse hook: when a handoff doc is written, spawn a tool-restricted
background review that actually runs self-improve's process, instead of
relying on the main conversation thread remembering to do it inline.

Why this exists: self-improve's own SKILL.md says it "runs autonomously
after every non-trivial task — no user prompt needed," but
~/.agents/retrospective-log.md sat completely empty (header row only)
through an entire marathon session that clearly warranted several entries.
The prose reminder alone doesn't reliably fire. Modeled on NousResearch
hermes-agent's background_review.py: fork a review after each turn under a
hard tool whitelist so it's safe to run fully unattended (see the
hermes-fork-to-review memory for the full comparison).

Runs the review as a detached, non-blocking subprocess — a real LLM call
here would otherwise stall the hook chain for the interactive session.
Never blocks or errors the originating tool; any failure exits silently.
"""
from __future__ import annotations
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HANDOFF_DIR = Path.home() / ".claude" / "handoffs"
AGENTS_DIR = Path.home() / ".agents"
SELF_IMPROVE_DIR = AGENTS_DIR / "skills" / "self-improve"
LOCK_FILE = SELF_IMPROVE_DIR / ".background_review.lock"
LOG_FILE = SELF_IMPROVE_DIR / ".background_review.log"

# Handoffs can fire more than once in a very active session — without a
# cooldown, each would spawn its own concurrent `claude -p` review, racing
# to edit the same retrospective-log.md/CLAUDE.md and burning a full LLM
# call each time. 20 minutes is long enough that back-to-back handoffs in
# one work session collapse into a single review of the whole span.
COOLDOWN_SECONDS = 20 * 60


def _resolve_claude_bin() -> str:
    """See daily_digest.py's identical helper — launchd's environment
    doesn't source .zshrc/.zprofile, so a plain PATH lookup can miss an
    install that works fine interactively."""
    found = shutil.which("claude")
    if found:
        return found
    for candidate in (
        Path.home() / ".local" / "bin" / "claude",
        Path("/opt/homebrew/bin/claude"),
        Path("/usr/local/bin/claude"),
    ):
        if candidate.exists():
            return str(candidate)
    raise FileNotFoundError("claude CLI not found on PATH or in common install locations")


def _cooldown_active() -> bool:
    if not LOCK_FILE.exists():
        return False
    age = time.time() - LOCK_FILE.stat().st_mtime
    return age < COOLDOWN_SECONDS


REVIEW_PROMPT_TEMPLATE = """You are the background self-improvement reviewer for MARVIN, running unattended after a handoff was just written. You have Read, Write, and Edit only — no Bash, no web access, no other tools. This is deliberate: you physically cannot do anything beyond read files and write memory/skill content, so it's safe to run without anyone watching.

Read `~/.agents/skills/self-improve/SKILL.md` and `~/.agents/skills/self-improve/quality-filter.md` in full and follow that process exactly against the handoff below. Do not improvise a different framework.

Be ACTIVE, not passive: most sessions that produced a handoff worth writing also produced at least one pattern worth capturing. A pass that finds nothing is a missed opportunity more often than it's the honest outcome — but don't force it if genuinely nothing qualifies.

Do NOT capture: environment-dependent failures specific to one machine, negative claims about a tool being broken (these harden into unwarranted self-citations later), transient/one-off errors, or narratives that only make sense for this exact conversation.

Regardless of outcome, append exactly one line to ~/.agents/retrospective-log.md in its existing format:
YYYY-MM-DD | <skill-name-or-"none"> | I/S/F | <one-line summary>
Use today's real date. If nothing passed the quality filter, write skill-name as "none" and summarize why briefly (e.g. "reviewed, no pattern met the recurrence gate").

Handoff to review:
---
{handoff_content}
---
"""


def run_review(handoff_content: str) -> None:
    """Runs synchronously — only ever called from the already-detached
    relaunch below, so blocking here doesn't stall the interactive session.
    Writes clear start/end markers with real exit status so daily_digest.py
    can parse actual success/failure counts instead of guessing from raw
    output."""
    try:
        claude_bin = _resolve_claude_bin()
    except FileNotFoundError as exc:
        with LOG_FILE.open("a") as log:
            log.write(f"\n=== run {datetime.now(timezone.utc).isoformat()} ===\n")
            log.write(f"START_FAILED: {exc}\n")
        return

    prompt = REVIEW_PROMPT_TEMPLATE.format(handoff_content=handoff_content)

    with LOG_FILE.open("a") as log:
        log.write(f"\n=== run {datetime.now(timezone.utc).isoformat()} ===\n")
        log.flush()
        proc = subprocess.run(
            [
                claude_bin, "-p", prompt,
                "--tools", "Read,Write,Edit",
                # No TTY here to approve anything, and none of Read/Write/
                # Edit needs approving anyway — Bash/WebFetch/Agent are
                # simply not in the toolset above, which is the actual
                # safety boundary. Without this the run just stalls
                # waiting on a prompt no one can answer (confirmed live).
                "--permission-mode", "bypassPermissions",
                "--output-format", "text",
            ],
            stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        )
        log.write(f"=== end (exit {proc.returncode}) ===\n")


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--run-review":
        # Relaunched-and-detached mode (see below) — read the handoff
        # content back from the path passed as argv[2] and actually run.
        run_review(Path(sys.argv[2]).read_text(errors="ignore"))
        return

    try:
        payload = json.load(sys.stdin)
    except Exception:
        return

    if payload.get("tool_name") not in ("Write", "Edit", "MultiEdit"):
        return

    fp = (payload.get("tool_input") or {}).get("file_path", "")
    if not fp:
        return

    p = Path(fp)
    try:
        in_handoffs = HANDOFF_DIR.resolve() in [d.resolve() for d in p.parents]
    except Exception:
        return
    if not in_handoffs or p.suffix.lower() != ".md":
        return

    if _cooldown_active():
        return

    if not p.exists():
        return

    # Relaunch this same script, detached, with --run-review — that copy
    # runs run_review() synchronously (safe, since it's not blocking this
    # hook process) so it can write real start/end/exit-status markers to
    # the log. Spawning `claude` directly here (the original approach)
    # meant nothing after Popen() ever ran, so the log had no way to know
    # whether a launch actually succeeded.
    try:
        LOCK_FILE.write_text(str(time.time()))
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--run-review", str(p)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
            start_new_session=True,  # detach fully — outlives this hook process
        )
        print("[self-improve] background review launched", flush=True)
    except Exception:
        return


if __name__ == "__main__":
    main()
