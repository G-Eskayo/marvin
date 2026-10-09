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

Found the hard way again, 2026-07-14/15: a WIP-restore conflict (pull()'s
stash-pop failure path, logged as "restoring local WIP conflicted") leaves
the stash sitting there un-popped and says so in the log — but nothing
actually stopped the *next* run from trying anyway. Every subsequent
push()/pull() on that machine kept failing silently into sync-log.md for a
day and a half, only surfacing the next morning via cron_health.py's daily
snapshot. Both push() and pull() now call _stuck_from_previous_run() first
and refuse to proceed (no new stash on top of an old one, no commit while
mid-merge) until a live session resolves it by hand — the same class of fix
as the conflict-marker check above, just for the state a run leaves behind
instead of the content it's about to commit.

Found again, 2026-10-08: a specific stash-pop collision happens when machine
A has untracked bench/metrics run-logs, and machine B pushes the same paths
as newly-tracked files (from recording metrics in that session). The merge
succeeds, but stash pop fails with "untracked files would be overwritten"
because git can't restore a stash-tracked file on top of an untracked one
with the same name. For this one specific case (all colliding files are
bench/metrics/*.json or *.md, excluding index.md), pull() now intelligently
merges them by timestamp and commits the union, rather than leaving a stash
behind. The merge logic mirrors metrics_registry.record()'s own format:
JSON files union-by-timestamp (deduplicate exact matches), markdown files
union on header-timestamp boundaries. Any other collision shape (non-metrics
files, mixed collisions) falls through to today's "stash preserved" behavior
unchanged — the autonomous resolver only acts when safe to do so.

Two more things tuned the same day, both about pull()'s own logging:
pull() no longer logs (or stashes) a pure no-op — nothing merged, no local
WIP involved — since logging one just to have said something produced its
own failure mode (two machines pulling close together each generate a
"nothing happened" entry, hand it to the other, which logs *that* as its own
no-op, forever). And pull()'s entry for a *real* merge is deliberately left
to trail rather than self-committed immediately — an earlier attempt to
self-flush it caused a worse problem: committing+pushing immediately hands
the other machine a new commit to merge, which logs and flushes its own
entry about *that* merge, which this machine then merges and flushes again —
two machines pulling from each other never reach a quiet fixed point. Left
to trail instead; the next real push() (on either machine, from actual work)
sweeps it up naturally, same as any other pending local change.
"""
from __future__ import annotations
import json
import re
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from machine_profile import machine_label  # noqa: E402
from notify import notify  # noqa: E402

DEFAULT_REPO = Path.home() / ".agents"
LOG_PATH = Path.home() / ".claude" / "sync-log.md"
CONFLICT_MARKER_RE = re.compile(r"^(<{7}|={7}|>{7})(?: |$)", re.MULTILINE)
UNTRACKED_OVERWRITE_RE = re.compile(
    r"(untracked working tree files.*would be overwritten|"
    r"already exists, no checkout|"
    r"could not restore untracked files from stash)",
    re.IGNORECASE | re.DOTALL,
)


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


def _git_ok(repo: Path, args: list[str], env: dict | None = None) -> tuple[bool, str]:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True,
                            env={**os.environ, **env} if env else None)
    return result.returncode == 0, (result.stdout + result.stderr)


CONFLICT_STATUS_CODES = {"UU", "AA", "DD", "AU", "UA", "UD", "DU"}


def _stuck_from_previous_run(repo: Path) -> str | None:
    """Is this repo already broken from a run that never finished — a live
    merge conflict, or a stash left behind by a failed WIP-restore? If so,
    every git operation below (stash, commit, merge) either compounds the
    mess or silently no-ops, so callers must bail before touching anything.
    Same detection logic as session_start_report.py's check_git_conflicts(),
    duplicated rather than imported so code_sync.py has no dependency on the
    hook script — this needs to run standalone from cron/hooks too."""
    status = _git(repo, ["status", "--porcelain=v1"])
    has_conflict = (repo / ".git" / "MERGE_HEAD").exists() or any(
        line[:2] in CONFLICT_STATUS_CODES for line in status.splitlines()
    )
    if has_conflict:
        return "an unresolved merge conflict is already sitting in the working tree"

    stash = _git(repo, ["stash", "list"])
    n_stash = len([line for line in stash.splitlines() if line.strip()])
    if n_stash:
        files = _stash_file_names(repo)
        if files:
            files_str = ", ".join(files[:5])  # limit to first 5 for readability
            if len(files) > 5:
                files_str += f" + {len(files) - 5} more"
            return f"{n_stash} stash(es) left over from a previous failed WIP-restore (`git stash list`) — stash@{{0}} touches: {files_str}"
        return f"{n_stash} stash(es) left over from a previous failed WIP-restore (`git stash list`)"

    return None


def _stash_untracked_paths(repo: Path) -> list[str]:
    """Extract untracked file paths from stash@{0}'s untracked parent.
    Returns [] if there's no untracked parent in the stash."""
    output = _git(repo, ["ls-tree", "-r", "--name-only", "stash@{0}^3"])
    if not output.strip():
        return []
    return [line.strip() for line in output.splitlines() if line.strip()]


def _stash_file_names(repo: Path) -> list[str]:
    """Get all tracked and untracked file names from stash@{0}.
    Combines tracked files (stash@{0}) + untracked files (stash@{0}^3).
    Returns [] if stash doesn't exist or can't be read."""
    tracked = []
    untracked = _stash_untracked_paths(repo)

    # Get tracked files from the main stash
    output = _git(repo, ["diff-tree", "--no-commit-id", "--name-only", "-r", "stash@{0}^..stash@{0}"])
    if output.strip():
        tracked = [line.strip() for line in output.splitlines() if line.strip()]

    # Deduplicate and return
    return sorted(set(tracked + untracked))


def _is_bench_metrics_runlog(path: str) -> bool:
    """True for bench/metrics/*.json or bench/metrics/*.md, excluding index.md."""
    if not path.startswith("bench/metrics/"):
        return False
    name = path.split("/")[-1]
    if name == "index.md":
        return False
    return name.endswith(".json") or name.endswith(".md")


def _merge_metrics_json(stash_text: str, upstream_text: str) -> str:
    """Merge two JSON metrics files by timestamp (union-by-timestamp).
    Parses both as JSON lists, deduplicates by timestamp, sorts ascending."""
    try:
        stash_data = json.loads(stash_text)
        upstream_data = json.loads(upstream_text)
    except (json.JSONDecodeError, ValueError):
        return upstream_text

    by_timestamp = {}
    for entry in stash_data:
        if isinstance(entry, dict) and "timestamp" in entry:
            by_timestamp[entry["timestamp"]] = entry
    for entry in upstream_data:
        if isinstance(entry, dict) and "timestamp" in entry:
            by_timestamp[entry["timestamp"]] = entry

    merged = sorted(by_timestamp.values(), key=lambda e: e.get("timestamp", ""))
    return json.dumps(merged, indent=2)


def _merge_metrics_md(stash_text: str, upstream_text: str) -> str:
    """Merge two markdown metrics files by timestamp.
    Splits on ^## boundaries, deduplicates by header line's timestamp, sorts."""
    def split_blocks(text: str) -> list[tuple[str, str]]:
        parts = re.split(r"^## ", text, flags=re.MULTILINE)
        blocks = []
        for part in parts[1:]:
            lines = part.split("\n", 1)
            header = lines[0] if lines else ""
            content = ("\n" + lines[1]) if len(lines) > 1 else ""
            blocks.append((header, content))
        return blocks

    stash_blocks = split_blocks(stash_text)
    upstream_blocks = split_blocks(upstream_text)

    by_header = {}
    for header, content in stash_blocks:
        by_header[header] = content
    for header, content in upstream_blocks:
        by_header[header] = content

    sorted_headers = sorted(by_header.keys())
    merged_lines = []
    for header in sorted_headers:
        merged_lines.append(f"## {header}{by_header[header]}")

    return "".join(merged_lines)


def _resolve_metrics_stash_collision(repo: Path, candidates: list[str]) -> bool:
    """Resolve stash pop collision for bench/metrics run-log files.
    Returns True if resolved, False if unrelated conflict found (falls through
    to existing behavior, leaving stash intact)."""
    saved_upstream = {}
    for path in candidates:
        full_path = repo / path
        if full_path.exists():
            try:
                saved_upstream[path] = full_path.read_text()
            except Exception:
                return False
            full_path.unlink()

    pop_ok, pop_out = _git_ok(repo, ["stash", "pop"])
    if not pop_ok:
        for path, content in saved_upstream.items():
            (repo / path).write_text(content)
        return False

    merged_files = []
    for path in candidates:
        full_path = repo / path
        if not full_path.exists():
            continue

        upstream_content = saved_upstream[path]
        current_content = full_path.read_text()

        if current_content == upstream_content:
            continue

        if path.endswith(".json"):
            merged = _merge_metrics_json(current_content, upstream_content)
        else:
            merged = _merge_metrics_md(current_content, upstream_content)

        full_path.write_text(merged)
        merged_files.append(path)

    if merged_files:
        _git(repo, ["add"] + merged_files)
        label = machine_label()
        msg = f"keep both machines' runs ({label}): {', '.join(merged_files)}"
        _git_ok(repo, ["commit", "-m", msg], env={"MARVIN_COMMIT_KIND": "auto-sync"})
        _log(repo, "pull", f"resolved untracked metrics collision by merging timestamps", merged_files)

    return True


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

    stuck = _stuck_from_previous_run(repo)
    if stuck:
        _log(repo, "push", f"REFUSING to run — {stuck}, needs manual resolution before push can proceed")
        notify("MARVIN code-sync CONFLICT", f"Stuck from a previous run [{repo.name}] — check sync-log.md", open_target=str(LOG_PATH))
        return

    status = _git(repo, ["status", "--porcelain"])
    all_changed = [line[3:].strip() for line in status.splitlines() if line.strip()]
    # sync-log.md itself doesn't count — otherwise its own last entry (written
    # after a prior push, per the pre-log write below, still lands one line
    # after the commit it describes) would make every push think there's
    # real work to do, and would make "nothing to commit" impossible to ever
    # detect once the log has grown at all.
    real_changes = [f for f in all_changed if f != LOG_PATH.name]
    if not real_changes:
        # Working tree can be clean while HEAD still holds commits that were
        # never pushed — e.g. a manual conflict-resolution `git commit` made
        # outside this script. A pure "nothing dirty" check missed this and
        # silently no-op'd real work.
        subprocess.run(["git", "fetch", "origin"], cwd=repo, capture_output=True)
        ahead = _git(repo, ["rev-list", "--count", "origin/main..HEAD"]).strip()
        if ahead in ("", "0"):
            return
        push_ok, push_out = _git_ok(repo, ["push", "origin", "main"])
        if push_ok:
            _log(repo, "push", f"pushed {ahead} already-committed change(s) found on a clean working tree")
            notify("MARVIN code-sync", f"Pushed {ahead} pending commit(s) from {label} [{repo.name}]")
            return
        clean, merge_output = _merge_remote(repo)
        if not clean:
            _log(repo, "push", f"CONFLICT merging remote while pushing pre-existing commits — needs manual resolution:\n{merge_output}")
            notify("MARVIN code-sync CONFLICT", f"Push rejected and merge conflicted [{repo.name}] — check sync-log.md", open_target=str(LOG_PATH))
            return
        retry_ok, retry_out = _git_ok(repo, ["push", "origin", "main"])
        if retry_ok:
            _log(repo, "push", f"pushed {ahead} already-committed change(s) (merged remote changes first)")
            notify("MARVIN code-sync", f"Pushed pending commit(s) from {label} [{repo.name}] (merged first)")
        else:
            _log(repo, "push", f"push failed even after merge retry:\n{retry_out}")
            notify("MARVIN code-sync FAILED", f"Push failed after retry [{repo.name}] — check sync-log.md", open_target=str(LOG_PATH))
        return

    broken = _files_with_conflict_markers(repo, all_changed)
    if broken:
        _log(repo, "push", f"REFUSING to commit — conflict markers found in {len(broken)} file(s), needs manual resolution before this push can proceed:", broken)
        notify("MARVIN code-sync CONFLICT", f"Refusing to commit broken content [{repo.name}] — check sync-log.md", open_target=str(LOG_PATH))
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
    # marks its commit for the direct-commit check (#337): never blocked, but code swept up without tests is logged
    commit_ok, commit_out = _git_ok(repo, ["commit", "-m", msg], env={"MARVIN_COMMIT_KIND": "auto-sync"})
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
        notify("MARVIN code-sync CONFLICT", f"Push rejected and merge conflicted [{repo.name}] — check sync-log.md", open_target=str(LOG_PATH))
        return

    retry_ok, retry_out = _git_ok(repo, ["push", "origin", "main"])
    if retry_ok:
        _log(repo, "push", f"committed + pushed {len(changed_files)} file(s) (merged remote changes first)", changed_files)
        notify("MARVIN code-sync", f"Pushed {len(changed_files)} file(s) from {label} [{repo.name}] (merged first)")
    else:
        _log(repo, "push", f"push failed even after merge retry:\n{retry_out}", changed_files)
        notify("MARVIN code-sync FAILED", f"Push failed after retry [{repo.name}] — check sync-log.md", open_target=str(LOG_PATH))


def pull(repo: Path) -> None:
    stuck = _stuck_from_previous_run(repo)
    if stuck:
        _log(repo, "pull", f"REFUSING to run — {stuck}, needs manual resolution before pull can proceed")
        notify("MARVIN code-sync CONFLICT", f"Stuck from a previous run [{repo.name}] — check sync-log.md", open_target=str(LOG_PATH))
        return

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
        notify("MARVIN code-sync CONFLICT", f"Pull conflicted [{repo.name}] — check sync-log.md", open_target=str(LOG_PATH))
        return

    after = _git(repo, ["rev-parse", "HEAD"]).strip()

    if stashed:
        pop_ok, pop_out = _git_ok(repo, ["stash", "pop"])
        if not pop_ok:
            if UNTRACKED_OVERWRITE_RE.search(pop_out):
                candidates = [p for p in _stash_untracked_paths(repo) if (repo / p).exists()]
                if candidates and all(_is_bench_metrics_runlog(p) for p in candidates):
                    if _resolve_metrics_stash_collision(repo, candidates):
                        return
            _log(repo, "pull", f"pulled cleanly, but restoring local WIP conflicted — stash preserved, resolve by hand (`git stash list` / `git stash pop`):\n{pop_out}")
            notify("MARVIN code-sync CONFLICT", f"WIP restore conflicted after pull [{repo.name}] — check sync-log.md", open_target=str(LOG_PATH))
            return

    if before == after and not stashed:
        # Genuinely nothing happened — no merge, no WIP involved. Not worth
        # a log entry: logging (and self-flushing) a pure no-op just to have
        # something to say produced a real, avoidable failure mode — two
        # machines pulling close together would each generate their own
        # "nothing happened" commit, hand it to the other, which pulls it,
        # logs *that* as its own no-op, and so on indefinitely.
        return

    suffix = " (local WIP restored)" if stashed else ""
    if before == after:
        _log(repo, "pull", f"already up to date{suffix}")
    else:
        _log(repo, "pull", f"merged {before[:8]}..{after[:8]}{suffix}")
    # Deliberately NOT self-flushed (tried it, reverted — see git history):
    # committing+pushing this entry immediately creates a new commit for the
    # *other* machine to merge, which logs and flushes *its own* entry about
    # that merge, which this machine then merges and flushes again — two
    # machines pulling from each other never reach a quiet fixed point. Left
    # to trail instead; the next real push() (on either machine) sweeps it
    # up naturally, same as any other pending local change.


sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
import job_events  # noqa: E402  (run log shown in the dashboard's Health tab)


@job_events.reported("code-sync-push", "Code sync (git pull/push)")
def main() -> None:
    if len(sys.argv) not in (2, 3) or sys.argv[1] not in ("push", "pull"):
        print("usage: code_sync.py {push|pull} [repo-path]", file=sys.stderr)
        sys.exit(1)
    repo = Path(sys.argv[2]).expanduser() if len(sys.argv) == 3 else DEFAULT_REPO
    job_events.step(f"{sys.argv[1]} {repo}")
    (push if sys.argv[1] == "push" else pull)(repo)


if __name__ == "__main__":
    main()
