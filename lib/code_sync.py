#!/usr/bin/env python3
"""Bidirectional git sync across MARVIN's known machines, for any repo passed
to it. Two repos use this today:

    ~/.agents  — skills/lib/docs, remote is github.com/G-Eskayo/marvin
    ~/.claude  — a curated subset (CLAUDE.md, memory/, commands/, handoffs/,
                 shared backlogs — see ~/.claude/.gitignore's allow-list),
                 remote is a bare repo self-hosted on Mac Mini
                 (~/.claude-sync.git), reached over Tailscale/SSH — no
                 third-party service, since this content is more sensitive
                 than ~/.agents' skill code.

Full design rationale: docs/adr/0021-bidirectional-code-sync-scoped-commit-exception.md

    code_sync.py push [repo]   — commit + push local changes
    code_sync.py pull [repo]   — stash-if-dirty, pull, pop

`repo` defaults to ~/.agents. `push` is triggered by handoff's existing
PostToolUse hook (session/topic-switch moments) plus a daily launchd cron
backstop for sessions that never trigger a handoff — both wired for each
repo. `pull` is triggered by a SessionStart hook — wired as a real hook, not
a CLAUDE.md checklist line, per the "wire it as a hook, don't trust prose"
principle already established by emit-resume-prompt.py.

This is a scoped exception to CLAUDE.md's standing "never commit without being
asked" rule, limited to these two repos, made in exchange for real
transparency: every push/pull writes to ~/.claude/sync-log.md (checked at
session start, mirroring auto-fix-log.md's existing "autonomous but never
silent" pattern) — including runs against ~/.claude itself, which logs to a
file inside the very repo it's syncing. That self-reference caused a real
recurring friction the first time both machines pushed regularly: a log
entry written *after* a commit is, by construction, uncommitted content by
the time the next pull stashes it — meaning nearly every cycle produced an
avoidable stash-pop conflict on sync-log.md alone. push() now writes its log
entry *before* committing (optimistically, describing the commit about to
happen) so it's swept into the same commit instead of trailing.

Non-overlapping changes auto-merge (git's own merge machinery). Genuine
conflicts fail loud — merge aborted, tree left clean, logged clearly — and get
resolved by whichever live session next notices the log entry, the same way
manual resolution already works today. No automated conflict resolver exists
(deliberately not built ahead of a single real case — see ADR 0021).

Found the hard way, 2026-07-12: a stash-pop conflict leaves literal
`<<<<<<<`/`=======`/`>>>>>>>` markers sitting in working-tree files. Without a
check, the *next* automated push() doesn't know or care — it just `git add
-A`s and commits whatever's on disk, markers included, and pushes that
broken content as if it were legitimate. The other machine then pulls the
corruption, and if it also auto-pushes, can commit its own broken
"resolution" on top — compounding across autonomous cycles with nobody
watching, exactly what happened overnight while this file's own conflict
sat unresolved through several 22:00 cron backstop runs. push() now refuses
to commit if any changed file still contains conflict markers.
"""
from __future__ import annotations
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".agents" / "lib"))
from machine_profile import machine_label  # noqa: E402
from notify import notify  # noqa: E402

DEFAULT_REPO = Path.home() / ".agents"
LOG_PATH = Path.home() / ".claude" / "sync-log.md"
CONFLICT_MARKER_RE = re.compile(r"^(<{7}|={7}|>{7})(?: |$)", re.MULTILINE)


def _files_with_conflict_markers(repo: Path, files: list[str]) -> list[str]:
    """Which of these files still contain literal git conflict markers —
    catches a prior stash-pop/merge conflict that never got resolved before
    something (a live session or an autonomous cron) tried to commit anyway."""
    broken = []
    for f in files:
        path = repo / f
        if not path.is_file():
            continue
        try:
            text = path.read_text(errors="ignore")
        except Exception:
            continue
        if CONFLICT_MARKER_RE.search(text):
            broken.append(f)
    return broken


def _git(repo: Path, args: list[str]) -> str:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    return result.stdout


def _git_ok(repo: Path, args: list[str]) -> tuple[bool, str]:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    return result.returncode == 0, (result.stdout + result.stderr)


def _log(repo: Path, action: str, summary: str, files: list[str] | None = None) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()
    lines = [f"\n## {ts} — {action} ({machine_label()}) [{repo}]", summary]
    if files:
        lines += [f"- {f}" for f in files[:20]]
        if len(files) > 20:
            lines.append(f"- ...and {len(files) - 20} more")
    with LOG_PATH.open("a") as f:
        f.write("\n".join(lines) + "\n")


def _merge_remote(repo: Path) -> tuple[bool, str]:
    """Fetch + merge origin/main. On conflict, aborts the merge (tree left
    clean, nothing partially applied) rather than attempting resolution."""
    subprocess.run(["git", "fetch", "origin"], cwd=repo, capture_output=True)
    ok, output = _git_ok(repo, ["merge", "origin/main", "--no-edit"])
    if not ok:
        subprocess.run(["git", "merge", "--abort"], cwd=repo, capture_output=True)
        return False, output
    return True, output


def push(repo: Path) -> None:
    label = machine_label()
    status = _git(repo, ["status", "--porcelain"])
    all_changed = [line[3:].strip() for line in status.splitlines() if line.strip()]
    # sync-log.md itself doesn't count — otherwise its own last entry (written
    # after a prior push, per the pre-log write below, still lands one line
    # after the commit it describes) would make every push think there's
    # real work to do, and would make "nothing to commit" impossible to ever
    # detect once the log has grown at all.
    real_changes = [f for f in all_changed if f != LOG_PATH.name]
    if not real_changes:
        return

    broken = _files_with_conflict_markers(repo, all_changed)
    if broken:
        _log(repo, "push", f"REFUSING to commit — conflict markers found in {len(broken)} file(s), needs manual resolution before this push can proceed:", broken)
        notify("MARVIN code-sync CONFLICT", f"Refusing to commit broken content [{repo.name}] — check sync-log.md")
        return

    # Write the log entry BEFORE committing, not after — so it's swept into
    # the same commit by the git add -A below instead of trailing as fresh
    # dirty content that the next pull has to stash-and-repop (this was
    # generating a real, avoidable stash-pop conflict on almost every cycle
    # once both machines were pushing regularly — see ADR 0021's addendum).
    # Optimistic: written before we know push will actually succeed, so a
    # genuine failure still trails (rare; acceptable).
    _log(repo, "push", f"committed + pushed {len(real_changes)} file(s)", real_changes)

    changed_files = [line[3:].strip() for line in _git(repo, ["status", "--porcelain"]).splitlines() if line.strip()]
    _git(repo, ["add", "-A"])
    msg = f"auto-sync ({label}): {len(changed_files)} file(s) changed\n\n" + "\n".join(f"- {f}" for f in changed_files[:20])
    commit_ok, commit_out = _git_ok(repo, ["commit", "-m", msg])
    if not commit_ok:
        _log(repo, "push", f"commit failed:\n{commit_out}", changed_files)
        return

    push_ok, push_out = _git_ok(repo, ["push", "origin", "main"])
    if push_ok:
        notify("MARVIN code-sync", f"Pushed {len(real_changes)} file(s) from {label} [{repo.name}]")
        return

    # Rejected, most likely non-fast-forward — merge the remote's new commits
    # into our newly-made local commit, then retry once.
    clean, merge_output = _merge_remote(repo)
    if not clean:
        _log(repo, "push", f"CONFLICT merging remote after push rejection — local commit preserved, needs manual resolution:\n{merge_output}", changed_files)
        notify("MARVIN code-sync CONFLICT", f"Push rejected and merge conflicted [{repo.name}] — check sync-log.md")
        return

    retry_ok, retry_out = _git_ok(repo, ["push", "origin", "main"])
    if retry_ok:
        _log(repo, "push", f"committed + pushed {len(changed_files)} file(s) (merged remote changes first)", changed_files)
        notify("MARVIN code-sync", f"Pushed {len(changed_files)} file(s) from {label} [{repo.name}] (merged first)")
    else:
        _log(repo, "push", f"push failed even after merge retry:\n{retry_out}", changed_files)
        notify("MARVIN code-sync FAILED", f"Push failed after retry [{repo.name}] — check sync-log.md")


def pull(repo: Path) -> None:
    status = _git(repo, ["status", "--porcelain"])
    stashed = False
    if status.strip():
        stash_ok, stash_out = _git_ok(repo, ["stash", "push", "-u", "-m", "code_sync auto-stash"])
        stashed = stash_ok and "No local changes to save" not in stash_out

    before = _git(repo, ["rev-parse", "HEAD"]).strip()
    clean, merge_output = _merge_remote(repo)

    if not clean:
        if stashed:
            subprocess.run(["git", "stash", "pop"], cwd=repo, capture_output=True)
        _log(repo, "pull", f"CONFLICT merging origin/main — merge aborted, tree left clean:\n{merge_output}")
        notify("MARVIN code-sync CONFLICT", f"Pull conflicted [{repo.name}] — check sync-log.md")
        return

    after = _git(repo, ["rev-parse", "HEAD"]).strip()

    if stashed:
        pop_ok, pop_out = _git_ok(repo, ["stash", "pop"])
        if not pop_ok:
            _log(repo, "pull", f"pulled cleanly, but restoring local WIP conflicted — stash preserved, resolve by hand (`git stash list` / `git stash pop`):\n{pop_out}")
            notify("MARVIN code-sync CONFLICT", f"WIP restore conflicted after pull [{repo.name}] — check sync-log.md")
            return

    suffix = " (local WIP restored)" if stashed else ""
    if before == after:
        _log(repo, "pull", f"already up to date{suffix}")
    else:
        _log(repo, "pull", f"merged {before[:8]}..{after[:8]}{suffix}")


def main() -> None:
    if len(sys.argv) not in (2, 3) or sys.argv[1] not in ("push", "pull"):
        print("usage: code_sync.py {push|pull} [repo-path]", file=sys.stderr)
        sys.exit(1)
    repo = Path(sys.argv[2]).expanduser() if len(sys.argv) == 3 else DEFAULT_REPO
    (push if sys.argv[1] == "push" else pull)(repo)


if __name__ == "__main__":
    main()
