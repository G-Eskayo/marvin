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
import collections
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".agents" / "lib"))
from hook_errors import log_hook_error  # noqa: E402
from claude_bin import resolve_claude_bin as _resolve_claude_bin  # noqa: E402
import marvin_launcher  # noqa: E402
import instance  # noqa: E402

HANDOFF_DIR = Path.home() / ".claude" / "handoffs"
AGENTS_DIR = Path.home() / ".agents"
SELF_IMPROVE_DIR = AGENTS_DIR / "skills" / "self-improve"
LOCK_FILE = SELF_IMPROVE_DIR / ".background_review.lock"
LOG_FILE = SELF_IMPROVE_DIR / ".background_review.log"
RETRO_LOG = instance.path("retrospective-log.md")  # learned from the owner's sessions: private (ADR 0071)
SAFETY_MONITOR_SCRIPTS = AGENTS_DIR / "skills" / "safety-monitor" / "scripts"

sys.path.insert(0, str(SAFETY_MONITOR_SCRIPTS))
try:
    from verify import verify, quarantine  # noqa: E402
    from calibrate import get_tau  # noqa: E402
    _SAFETY_MONITOR_AVAILABLE = True
except ImportError:
    _SAFETY_MONITOR_AVAILABLE = False

# Handoffs can fire more than once in a very active session — without a
# cooldown, each would spawn its own concurrent `claude -p` review, racing
# to edit the same retrospective-log.md/CLAUDE.md and burning a full LLM
# call each time. 20 minutes is long enough that back-to-back handoffs in
# one work session collapse into a single review of the whole span.
COOLDOWN_SECONDS = 20 * 60


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


def _diff_lines(before: str, after: str) -> tuple[list[str], list[str]]:
    """Multiset line diff via Counter, returning added/removed lines in
    their original order with duplicates preserved correctly (lines that
    appear more in after than before are added, and vice versa)."""
    before_lines = before.splitlines()
    after_lines = after.splitlines()

    before_counter = collections.Counter(before_lines)
    after_counter = collections.Counter(after_lines)

    # added: lines that appear more in after than before, in after's order
    added = []
    after_counter_copy = after_counter.copy()
    for line in after_lines:
        if after_counter_copy[line] > before_counter[line]:
            added.append(line)
            after_counter_copy[line] -= 1

    # removed: lines that appear more in before than after, in before's order
    removed = []
    before_counter_copy = before_counter.copy()
    for line in before_lines:
        if before_counter_copy[line] > after_counter[line]:
            removed.append(line)
            before_counter_copy[line] -= 1

    return added, removed


def _remove_lines(text: str, lines_to_remove: list[str]) -> str:
    """Removes exactly one occurrence of each flagged line from text,
    leaving everything else (including lines that arrived after the
    added lines were computed) untouched. Removes from the end
    (last/most recent occurrence) to safely undo appends. Preserves
    the original file's line endings (\\n, \\r\\n, etc.)."""
    if not lines_to_remove:
        return text

    lines_with_ends = text.splitlines(keepends=True)
    removal_counter = collections.Counter(lines_to_remove)

    # Mark indices to skip (from the end, for each line to remove).
    # Iterate backwards so we remove the last occurrence of each line.
    skip_indices = set()
    for idx in range(len(lines_with_ends) - 1, -1, -1):
        line_with_end = lines_with_ends[idx]
        # Strip line endings using splitlines() without keepends.
        # This correctly handles all line separators that splitlines() recognizes.
        split_result = line_with_end.splitlines()
        content = split_result[0] if split_result else ''

        if removal_counter[content] > 0:
            removal_counter[content] -= 1
            skip_indices.add(idx)

    # Reconstruct, skipping marked indices
    result = ""
    for idx, line_with_end in enumerate(lines_with_ends):
        if idx not in skip_indices:
            result += line_with_end

    return result


def _atomic_write(path: Path, text: str) -> None:
    """Atomically write text to path using a temporary file + os.replace,
    preserving the original file's permissions if it exists."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.chmod(tmp, path.stat().st_mode & 0o777)
        except FileNotFoundError:
            os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def _verify_and_reconcile(before: str, log) -> None:
    """Post-hoc check on what the review actually appended to the append-only
    retrospective-log.md — the reviewer itself has Write/Edit and no
    verification gate, so this is the only check between it and a permanent,
    git-tracked line. Reverting an unflagged append here is safe: it happens
    before any git commit, and verify_retrospective_integrity.py only checks
    the working tree against the last *commit*, not against this script."""
    after = RETRO_LOG.read_text() if RETRO_LOG.exists() else ""

    added, removed = _diff_lines(before, after)

    if removed:
        log.write("VERIFY: retrospective-log.md changed non-additively — leaving "
                   "as-is for verify_retrospective_integrity.py to catch\n")

    if not added:
        log.write("VERIFY: no new retrospective-log.md entry — nothing to check\n")
        return

    if not _SAFETY_MONITOR_AVAILABLE:
        new_lines = "\n".join(added)
        log.write(f"VERIFY: safety-monitor unavailable, appended unchecked: {new_lines!r}\n")
        return

    new_lines = "\n".join(added)
    score = verify(new_lines, loop_name="self_improve")
    tau = get_tau("self_improve")
    if score >= tau:
        current = RETRO_LOG.read_text() if RETRO_LOG.exists() else ""
        updated = _remove_lines(current, added)
        _atomic_write(RETRO_LOG, updated)
        quarantine(new_lines, score, "self_improve", tau,
                   reason="flagged before landing in retrospective-log.md; append reverted")
        log.write(f"VERIFY: QUARANTINED (score {score:.2f} >= tau {tau:.2f}), "
                  f"reverted append, see ~/.claude/quarantine.md\n")
    else:
        log.write(f"VERIFY: passed (score {score:.2f} < tau {tau:.2f})\n")


def run_review(handoff_content: str) -> None:
    """Runs synchronously — only ever called from the already-detached
    relaunch below, so blocking here doesn't stall the interactive session.
    Writes clear start/end markers with real exit status so daily_digest.py
    can parse actual success/failure counts instead of guessing from raw
    output."""
    try:
        _resolve_claude_bin()  # fail early and log it when claude is missing
    except FileNotFoundError as exc:
        with LOG_FILE.open("a") as log:
            log.write(f"\n=== run {datetime.now(timezone.utc).isoformat()} ===\n")
            log.write(f"START_FAILED: {exc}\n")
        return

    prompt = REVIEW_PROMPT_TEMPLATE.format(handoff_content=handoff_content)
    before = RETRO_LOG.read_text() if RETRO_LOG.exists() else ""

    with LOG_FILE.open("a") as log:
        log.write(f"\n=== run {datetime.now(timezone.utc).isoformat()} ===\n")
        log.flush()
        # No TTY here to approve anything, and none of Read/Write/Edit needs approving anyway —
        # Bash/WebFetch/Agent are not in the toolset, which is the actual safety boundary.
        # Without bypassPermissions the run stalls on a prompt no one can answer (confirmed live).
        result = marvin_launcher.launch("background-analyst", prompt, tools="Read,Write,Edit",
                                        permission_mode="bypassPermissions")
        log.write(result.text + (f"\n{result.stderr}" if result.stderr else "") + "\n")
        log.write(f"=== end (exit {result.exit_code}) ===\n")
        if result.exit_code == 0:
            _verify_and_reconcile(before, log)


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--run-review":
        # Relaunched-and-detached mode (see below) — read the handoff
        # content back from the path passed as argv[2] and actually run.
        run_review(Path(sys.argv[2]).read_text(errors="ignore"))
        return

    try:
        payload = json.load(sys.stdin)
    except Exception as e:
        log_hook_error("background_review", "parsing stdin payload", e)
        return

    if payload.get("tool_name") not in ("Write", "Edit", "MultiEdit"):
        return

    fp = (payload.get("tool_input") or {}).get("file_path", "")
    if not fp:
        return

    p = Path(fp)
    try:
        in_handoffs = HANDOFF_DIR.resolve() in [d.resolve() for d in p.parents]
    except Exception as e:
        log_hook_error("background_review", f"resolving path {fp}", e)
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
    except Exception as e:
        log_hook_error("background_review", "spawning detached review subprocess", e)
        return


if __name__ == "__main__":
    main()
