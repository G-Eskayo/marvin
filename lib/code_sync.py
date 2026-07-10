#!/usr/bin/env python3
"""Bidirectional git sync for ~/.agents across MARVIN's known machines.
Full design rationale: docs/adr/0021-bidirectional-code-sync-scoped-commit-exception.md

    code_sync.py push   — commit + push local changes
    code_sync.py pull   — stash-if-dirty, pull, pop

`push` is triggered by handoff's existing PostToolUse hook (session/topic-switch
moments) plus a daily launchd cron backstop for sessions that never trigger a
handoff. `pull` is triggered by a SessionStart hook — wired as a real hook, not
a CLAUDE.md checklist line, per the "wire it as a hook, don't trust prose"
principle already established by emit-resume-prompt.py.

This is a scoped exception to CLAUDE.md's standing "never commit without being
asked" rule, limited to this one repo, made in exchange for real transparency:
every push/pull writes to ~/.claude/sync-log.md (checked at session start,
mirroring auto-fix-log.md's existing "autonomous but never silent" pattern).

Non-overlapping changes auto-merge (git's own merge machinery). Genuine
conflicts fail loud — merge aborted, tree left clean, logged clearly — and get
resolved by whichever live session next notices the log entry, the same way
manual resolution already works today. No automated conflict resolver exists
(deliberately not built ahead of a single real case — see ADR 0021).
"""
from __future__ import annotations
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".agents" / "lib"))
from machine_profile import machine_label  # noqa: E402
from notify import notify  # noqa: E402

AGENTS_DIR = Path.home() / ".agents"
LOG_PATH = Path.home() / ".claude" / "sync-log.md"


def _git(args: list[str]) -> str:
    result = subprocess.run(["git", *args], cwd=AGENTS_DIR, capture_output=True, text=True)
    return result.stdout


def _git_ok(args: list[str]) -> tuple[bool, str]:
    result = subprocess.run(["git", *args], cwd=AGENTS_DIR, capture_output=True, text=True)
    return result.returncode == 0, (result.stdout + result.stderr)


def _log(action: str, summary: str, files: list[str] | None = None) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()
    lines = [f"\n## {ts} — {action} ({machine_label()})", summary]
    if files:
        lines += [f"- {f}" for f in files[:20]]
        if len(files) > 20:
            lines.append(f"- ...and {len(files) - 20} more")
    with LOG_PATH.open("a") as f:
        f.write("\n".join(lines) + "\n")


def _merge_remote() -> tuple[bool, str]:
    """Fetch + merge origin/main. On conflict, aborts the merge (tree left
    clean, nothing partially applied) rather than attempting resolution."""
    subprocess.run(["git", "fetch", "origin"], cwd=AGENTS_DIR, capture_output=True)
    ok, output = _git_ok(["merge", "origin/main", "--no-edit"])
    if not ok:
        subprocess.run(["git", "merge", "--abort"], cwd=AGENTS_DIR, capture_output=True)
        return False, output
    return True, output


def push() -> None:
    label = machine_label()
    status = _git(["status", "--porcelain"])
    if not status.strip():
        _log("push", "nothing to commit")
        return

    changed_files = [line[3:].strip() for line in status.splitlines() if line.strip()]
    _git(["add", "-A"])
    msg = f"auto-sync ({label}): {len(changed_files)} file(s) changed\n\n" + "\n".join(f"- {f}" for f in changed_files[:20])
    commit_ok, commit_out = _git_ok(["commit", "-m", msg])
    if not commit_ok:
        _log("push", f"commit failed:\n{commit_out}", changed_files)
        return

    push_ok, push_out = _git_ok(["push", "origin", "main"])
    if push_ok:
        _log("push", f"committed + pushed {len(changed_files)} file(s)", changed_files)
        notify("MARVIN code-sync", f"Pushed {len(changed_files)} file(s) from {label}")
        return

    # Rejected, most likely non-fast-forward — merge the remote's new commits
    # into our newly-made local commit, then retry once.
    clean, merge_output = _merge_remote()
    if not clean:
        _log("push", f"CONFLICT merging remote after push rejection — local commit preserved, needs manual resolution:\n{merge_output}", changed_files)
        notify("MARVIN code-sync CONFLICT", "Push rejected and merge conflicted — check sync-log.md")
        return

    retry_ok, retry_out = _git_ok(["push", "origin", "main"])
    if retry_ok:
        _log("push", f"committed + pushed {len(changed_files)} file(s) (merged remote changes first)", changed_files)
        notify("MARVIN code-sync", f"Pushed {len(changed_files)} file(s) from {label} (merged first)")
    else:
        _log("push", f"push failed even after merge retry:\n{retry_out}", changed_files)
        notify("MARVIN code-sync FAILED", "Push failed after retry — check sync-log.md")


def pull() -> None:
    label = machine_label()
    status = _git(["status", "--porcelain"])
    stashed = False
    if status.strip():
        stash_ok, stash_out = _git_ok(["stash", "push", "-u", "-m", "code_sync auto-stash"])
        stashed = stash_ok and "No local changes to save" not in stash_out

    before = _git(["rev-parse", "HEAD"]).strip()
    clean, merge_output = _merge_remote()

    if not clean:
        if stashed:
            subprocess.run(["git", "stash", "pop"], cwd=AGENTS_DIR, capture_output=True)
        _log("pull", f"CONFLICT merging origin/main — merge aborted, tree left clean:\n{merge_output}")
        notify("MARVIN code-sync CONFLICT", "Pull conflicted — check sync-log.md")
        return

    after = _git(["rev-parse", "HEAD"]).strip()

    if stashed:
        pop_ok, pop_out = _git_ok(["stash", "pop"])
        if not pop_ok:
            _log("pull", f"pulled cleanly, but restoring local WIP conflicted — stash preserved, resolve by hand (`git stash list` / `git stash pop`):\n{pop_out}")
            notify("MARVIN code-sync CONFLICT", "WIP restore conflicted after pull — check sync-log.md")
            return

    suffix = " (local WIP restored)" if stashed else ""
    if before == after:
        _log("pull", f"already up to date{suffix}")
    else:
        _log("pull", f"merged {before[:8]}..{after[:8]}{suffix}")


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in ("push", "pull"):
        print("usage: code_sync.py {push|pull}", file=sys.stderr)
        sys.exit(1)
    (push if sys.argv[1] == "push" else pull)()


if __name__ == "__main__":
    main()
