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
    code_sync.py pull [repo]   — the Claude dir: commit, then merge; others: stash-if-dirty, pull, pop

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
happen) so it's swept into the same commit instead of trailing. That made the
log lie when the push then failed (marvin#427, 2026-10-14), and sync-log.md
has since been made merge=union, so push() now logs only once it knows the
outcome and lets the entry trail. Since 2026-10-26 (ADR 0076) every file both
machines append to in that dir is union-merged the same way, through a rule
code_sync writes into the clone's .git/info/attributes itself (ensure_union_rule).

Non-overlapping changes auto-merge (git's own merge machinery). Genuine
conflicts fail loud — merge aborted, tree left clean, logged clearly — and get
resolved by whichever live session next notices the log entry, the same way
manual resolution already works today.

Since 2026-10-26 (ADR 0077; the laptop's Claude dir went four days without a
push) four more rules keep both machines building on each other:
  - partial push: every changed file is pushed except those a live session is
    editing (a live-edit lease) or that hold conflict markers; they wait a cycle;
  - the synced Claude dir commits local work before it merges (a real merge, no
    stash or pop); the engine and the instance keep stash -> merge -> pop;
  - in that dir, a conflict confined to suggestions.md and memory notes is
    resolved by keeping both sides and shown on Health's union-review card;
  - a repo failing for 30 min tells the owner once (notify), and once when it
    clears; a leftover stash HEAD already contains is dropped and logged.

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
import hashlib
import json
import re
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from machine_profile import machine_label  # noqa: E402
from notify import notify  # noqa: E402
import error_log  # noqa: E402  (marvin#422: sync failures are never silent)
import session_work  # noqa: E402

DEFAULT_REPO = Path.home() / ".agents"
LOG_PATH = Path.home() / ".claude" / "sync-log.md"
# mirror() (pull-only node, ADR 0069) logs outside the synced files and backs up whatever it discards.
MIRROR_LOG_PATH = Path.home() / ".claude" / "logs" / "code-sync-mirror.log"
MIRROR_BACKUP_DIR = Path.home() / ".claude" / "backups" / "mirror"
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
    Same detection logic as session_start_report.py's check_sync_block(),
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
    if SYNC_FAILURE_RE.match(summary or ""):
        _RUN["failed"] = _RUN.get("failed") or (summary or "").splitlines()[0]
        error_log.record(f"sync:{action}", (summary or "").splitlines()[0][:200], raw=summary)


# Summaries that mean a sync run failed (marvin#422): before, these lived only in sync-log.md, and a stale git lock
# failed every pull for 26 hours without Health turning red.
SYNC_FAILURE_RE = re.compile(r"^(REFUSING|CONFLICT|commit failed|push failed|pulled cleanly, but restoring)")
STALE_LOCK_SECONDS = 10 * 60


def _lock_held(lock: Path) -> bool:
    """True if any process has the file open (lsof exits 0 when it lists one)."""
    # Found on PATH: /usr/sbin on macOS, /usr/bin on Linux (ADR 0069). Not found raises, which callers treat as doubt.
    lsof = shutil.which("lsof") or "/usr/sbin/lsof"
    return subprocess.run([lsof, "-t", "--", str(lock)], capture_output=True).returncode == 0


def heal_stale_index_lock(repo: Path, now: float | None = None) -> bool:
    """Remove .git/index.lock only when it is older than STALE_LOCK_SECONDS and no process holds it (a git command
    that crashed or was killed). Logged as a fix. Any doubt (holder check fails) leaves the lock alone."""
    lock = Path(repo) / ".git" / "index.lock"
    try:
        age = (now or time.time()) - lock.stat().st_mtime
    except OSError:
        return False
    if age < STALE_LOCK_SECONDS:
        return False
    try:
        if _lock_held(lock):
            return False
        lock.unlink()
    except Exception:  # noqa: BLE001 -- when in doubt, leave it: a wrong removal could corrupt the index
        return False
    error_log.record_fix("sync:pull", f"removed a stale git lock in {Path(repo).name} (left {int(age // 60)} min ago by a crashed git command)",
                         raw=str(lock))
    return True


def _leased_files(repo: Path, changed_files: list[str], now: float | None = None) -> dict[str, str]:
    """{file: reason} for each of `changed_files` a live session edited in the last LIVE_S: it might still be
    mid-write, so it waits for the next cycle while the rest syncs. A lease goes away on its own once the session goes
    quiet (crash, finished, or moved on); session_work's own LIVE_S window is the timeout. Any doubt reads as no
    lease (fails open, as before)."""
    if not changed_files:
        return {}
    now = now if now is not None else time.time()
    try:
        repo_id, _ = session_work.file_key(str(repo / changed_files[0]))
        if repo_id is None:
            return {}
        edits = session_work.live_edits_for(repo_id, changed_files, now)
    except Exception:
        return {}
    out: dict[str, str] = {}
    for e in sorted(edits, key=lambda e: -e["edited_at"]):
        if e["path"] not in out:
            minutes_ago = max(0, int((now - e["edited_at"]) / 60))
            request = f', working on: "{e["request"]}"' if e["request"] else ""
            out[e["path"]] = f'{e["path"]} was edited {minutes_ago} min ago by a live session{request}'
    return out


def _live_edit_lease(repo: Path, changed_files: list[str], now: float | None = None) -> str | None:
    """The first lease reason among `changed_files`, or None (kept for callers that ask about a whole set)."""
    leased = _leased_files(repo, changed_files, now)
    return next(iter(leased.values())) if leased else None


def _last_own_entry(repo: Path, action: str | None = None) -> str | None:
    """First line of this Mac's most recent entry for `repo` (of `action`, if given). Reads only the log's tail; any
    doubt is None."""
    try:
        with LOG_PATH.open("rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 512 * 1024))
            text = f.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    header = re.compile(r"^## \S+ — " + (re.escape(action) if action else r"\S+") + r" \(" + re.escape(machine_label())
                        + r"\) \[" + re.escape(str(repo)) + r"\]\n(.*)$", re.MULTILINE)
    last = None
    for last in header.finditer(text):
        pass
    return last.group(1) if last else None


def _last_own_push_failed(repo: Path) -> bool:
    return bool(SYNC_FAILURE_RE.match(_last_own_entry(repo, "push") or ""))


def _not_on_main(repo: Path) -> str | None:
    """Why this run must leave the tree alone, if anything other than `main` is checked out (marvin#440): a commit
    there sweeps other sessions' WIP into that branch (PR #439, 2026-10-14) and `git push origin main` never ships it.
    Whoever checked the branch out owns its commits. None for main, and for a path that isn't a git repo at all."""
    ok, out = _git_ok(repo, ["symbolic-ref", "--short", "-q", "HEAD"])
    if ok:
        branch = out.strip()
        return None if branch == "main" else f"skipping — {branch} checked out, not main; whoever checked it out owns its commits"
    if not _git_ok(repo, ["rev-parse", "--git-dir"])[0]:
        return None
    return "skipping — detached HEAD (rebase or bisect in progress?), not main; nothing committed, stashed or merged"


def _skip_off_main(repo: Path, action: str) -> bool:
    """True if the run must stop here. Logged once per branch, not every cycle."""
    reason = _not_on_main(repo)
    if not reason:
        return False
    if _last_own_entry(repo) != reason:
        _log(repo, action, reason)
    return True


# ── union merge for files both machines only add to (ADR 0076) ─────────────────────────────────────────────────────
# Both Macs append to these in the synced Claude dir; each such stash pop used to conflict and stop sync until a person
# kept both sides (three times, 2026-10-22..26). git's built-in `union` driver keeps both sides' lines instead. The rule
# lives in the clone's own .git/info/attributes, written here before every stash or merge: it is in force on a fresh
# machine before its first pull (a tracked .gitattributes only applies once it has been pulled), it can never conflict
# between machines itself, and it changes when the engine does. Patterns are anchored to the repo root.
UNION_REPO_NAME = ".claude"
UNION_MERGE_PATHS = (
    "/sync-log.md",
    "/auto-fix-log.md",
    "/quarantine.md",
    "/improvement-queue.md",
    "/projects/*/memory/MEMORY.md",   # the memory index; notes are edited in place and auto-resolved instead
)
_UNION_BEGIN = "# >>> code_sync: union merge for files every machine appends to (ADR 0076; managed, edits are replaced)"
_UNION_END = "# <<< code_sync"
_UNION_BLOCK_RE = re.compile(re.escape(_UNION_BEGIN) + r".*?" + re.escape(_UNION_END) + r"\n?", re.DOTALL)
INDEX_LINE_RE = re.compile(r"^\s*[-*] \[[^\]]*\]\(([^)\s]+)\)")
HEADING_RE = re.compile(r"^#{1,6} \S")
REVIEW_KINDS = ("kept-changed-line", "heading-twice", "linked-twice", "auto-resolved")


def ensure_union_rule(repo: Path) -> bool:
    """Make sure this clone's info/attributes carries the union rule. Only the synced Claude dir gets it, never the
    engine repo, whose code must conflict when two machines change it. Idempotent; a person's own lines in the file
    are kept. True if the file was written."""
    repo = Path(repo)
    if repo.name != UNION_REPO_NAME:
        return False
    ok, out = _git_ok(repo, ["rev-parse", "--git-path", "info/attributes"])
    if not ok or not out.strip():
        return False
    path = Path(out.strip().splitlines()[-1])
    path = path if path.is_absolute() else repo / path
    try:
        old = path.read_text() if path.exists() else ""
    except OSError:
        return False
    block = "\n".join([_UNION_BEGIN, *(f"{p} merge=union" for p in UNION_MERGE_PATHS), _UNION_END]) + "\n"
    rest = _UNION_BLOCK_RE.sub("", old)
    new = (rest if not rest or rest.endswith("\n") else rest + "\n") + block
    if new == old:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new)
    return True


def _union_files(repo: Path, files: list[str]) -> list[str]:
    """Which of `files` git itself merges with union -- asked of git, so the answer is exactly what the merge used."""
    if not files:
        return []
    out = _git(repo, ["check-attr", "merge", "--", *files])
    return [line.rsplit(": merge: ", 1)[0] for line in out.splitlines() if line.endswith(": merge: union")]


def _changed(repo: Path, a: str, b: str) -> set[str]:
    return {f for f in _git(repo, ["diff", "--name-only", "--no-renames", a, b]).splitlines() if f}


def _show(repo: Path, rev: str, path: str) -> str:
    ok, out = _git_ok(repo, ["show", f"{rev}:{path}"])
    return out if ok else ""


def _counts(text: str) -> dict[str, int]:
    """Lines that carry content (blank and pure-punctuation lines such as `---` repeat legitimately)."""
    counts: dict[str, int] = {}
    for line in text.splitlines():
        if re.search(r"\w", line):
            counts[line] = counts.get(line, 0) + 1
    return counts


def _review_union_merge(repo: Path, base: str, ours: str, theirs: str, result: str | None) -> list[dict]:
    """What union could not settle on its own, for the files both sides changed since `base`. `result` is a revision,
    or None for the working tree (a stash pop). One pass over each such file: O(lines of the files both sides touched).
      kept-changed-line  a line one side changed or removed is still there (union keeps both hunks whole when an
                         edit touches the other side's addition, so the old line comes back beside the new one)
      heading-twice      a markdown heading the merge doubled (two quarantine entries may share one: never removed)
    Exact duplicate memory-index lines are not reported: _tidy_union_merge removes them."""
    both = _changed(repo, base, ours) & _changed(repo, base, theirs)
    items = []
    for f in _union_files(repo, sorted(both)):
        if result is None:
            try:
                result_text = (repo / f).read_text()
            except OSError:
                continue
        else:
            result_text = _show(repo, result, f)
        b, o, t, r = (_counts(x) for x in (_show(repo, base, f), _show(repo, ours, f), _show(repo, theirs, f), result_text))
        for line, n in r.items():
            no, nt, nb = o.get(line, 0), t.get(line, 0), b.get(line, 0)
            if nb > min(no, nt) and n > min(no, nt):
                items.append({"kind": "kept-changed-line", "file": f, "line": line})
            elif n > max(no, nt) and HEADING_RE.match(line):
                items.append({"kind": "heading-twice", "file": f, "line": line, "count": n})
    return items


def _dedupe_index_lines(path: Path) -> list[str]:
    """Remove exact repeats of memory-index lines (`- [title](file.md) ...`), keeping the first. Nothing else is ever
    removed: not a near-duplicate, not prose, not a heading, not a blank line. A file still holding conflict markers is
    left exactly as it is. Returns the removed lines; the file is untouched when there are none."""
    try:
        text = path.read_text()
    except OSError:
        return []
    if CONFLICT_MARKER_RE.search(text):
        return []
    seen, kept, removed = set(), [], []
    for line in text.splitlines(keepends=True):
        bare = line.rstrip("\r\n")
        if INDEX_LINE_RE.match(bare):
            if bare in seen:
                removed.append(bare)
                continue
            seen.add(bare)
        kept.append(line)
    if removed:
        path.write_text("".join(kept))
    return removed


def _links_twice(text: str) -> list[str]:
    seen, twice = set(), []
    for line in text.splitlines():
        m = INDEX_LINE_RE.match(line)
        if m:
            if m.group(1) in seen and m.group(1) not in twice:
                twice.append(m.group(1))
            seen.add(m.group(1))
    return twice


def _review_path() -> Path:
    """Machine-local (under logs/, which the synced dir never commits): what this machine's merges left for a person."""
    return LOG_PATH.parent / "logs" / "union-merge-review.json"


def _item_holds(item: dict) -> bool:
    """A live reading: an item stays open only while the file still shows it, so a person fixing the file clears it."""
    if not isinstance(item, dict) or item.get("kind") not in REVIEW_KINDS or not item.get("repo") or not item.get("file"):
        return False
    try:
        text = (Path(item["repo"]) / item["file"]).read_text()
    except OSError:
        return False
    lines = text.splitlines()
    if item["kind"] == "kept-changed-line":
        return item.get("line") in lines
    if item["kind"] == "heading-twice":
        return lines.count(item.get("line")) >= int(item.get("count") or 2)
    if item["kind"] == "auto-resolved":   # open while its marked section is there, or (no section) the file is untouched
        return item.get("line") in lines if item.get("line") else _digest(text) == item.get("digest")
    return item.get("target") in _links_twice(text)


def _review_items_raw() -> list:
    """Raises on an unreadable file (Health says it couldn't measure); a missing file is no items."""
    path = _review_path()
    if not path.exists():
        return []
    items = json.loads(path.read_text()).get("items", [])
    return items if isinstance(items, list) else []


def union_review_open() -> list[dict]:
    """The items still open on this machine. An unreadable review file reads as none here; Health reports it."""
    try:
        return [i for i in _review_items_raw() if _item_holds(i)]
    except (OSError, ValueError, AttributeError):
        return []


def _item_key(item: dict) -> tuple:
    return (item.get("repo"), item.get("file"), item.get("kind"), item.get("line"), item.get("target"))


def _item_text(item: dict) -> str:
    if item["kind"] == "auto-resolved":
        where = f"; tidy the \"{item['line'].lstrip('# ')}\" section" if item.get("line") else "; check it reads right"
        return f"{item['file']}: both machines edited it, kept both sides{where}"
    if item["kind"] == "linked-twice":
        return f"{item['file']}: the memory {item['target']} is listed twice with different text — keep one"
    if item["kind"] == "heading-twice":
        return f"{item['file']}: heading now appears {item['count']} times — check for a doubled entry: {item['line'][:120]}"
    return f"{item['file']}: kept a line the other side changed or removed: {item['line'][:120]}"


def _tidy_union_merge(repo: Path, items: list[dict], touched: set[str]) -> None:
    """After a merge and any stash pop are done: remove exact duplicate index lines from the memory indexes union
    touched, then record (and log once) everything else for a person. Never runs between a merge and its stash pop:
    editing the tree there would make the pop conflict on the edit."""
    removed = []
    for f in sorted(touched):
        if Path(f).name == "MEMORY.md":
            removed += [f"{f}: {line}" for line in _dedupe_index_lines(repo / f)]
            try:
                text = (repo / f).read_text()
            except OSError:
                continue
            items += [{"kind": "linked-twice", "file": f, "target": t} for t in _links_twice(text)]
    if removed:
        _log(repo, "union", f"removed {len(removed)} exact duplicate memory index line(s) a union merge left behind", removed)

    items = [{**i, "repo": str(repo)} for i in items]
    raw = _safe_review_items()
    current = [i for i in raw if _item_holds(i)]
    known = {_item_key(i) for i in current}
    new = []
    for i in items:
        if _item_key(i) not in known and _item_holds(i):
            known.add(_item_key(i))
            new.append(i)
    if new:
        _log(repo, "union", f"needs a look — {len(new)} thing(s) a union merge could not settle on its own "
                            f"(Health shows them until the file is fixed):", [_item_text(i) for i in new])
    if new or len(current) != len(raw):   # bounded: items a person has since fixed are dropped on every write
        path = _review_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"items": current + new}, indent=1, ensure_ascii=False))
        tmp.replace(path)


def _safe_review_items() -> list:
    try:
        return _review_items_raw()
    except (OSError, ValueError, AttributeError):
        return []


def _review_merge_commit(repo: Path, first_parent: str, rev: str = "HEAD") -> tuple[list[dict], set[str]]:
    """Review `rev` if it is the two-parent merge this run just made on top of `first_parent`. A fast-forward merged
    nothing here, even onto another machine's merge commit: that machine reviewed its own."""
    ok, p2 = _git_ok(repo, ["rev-parse", "-q", "--verify", f"{rev}^2"])
    if not ok:
        return [], set()
    p1 = _git(repo, ["rev-parse", f"{rev}^1"]).strip()
    if p1 != first_parent:
        return [], set()
    base = _git(repo, ["merge-base", p1, p2.strip()]).strip()
    if not base:
        return [], set()
    touched = set(_union_files(repo, sorted(_changed(repo, base, p1) & _changed(repo, base, p2.strip()))))
    return _review_union_merge(repo, base, p1, p2.strip(), rev), touched


def _review_stash_pop(repo: Path, stash_rev: str, ours: str) -> tuple[list[dict], set[str]]:
    """Review a stash just popped onto `ours`: the stash's own parent is the base both sides started from."""
    base = _git(repo, ["rev-parse", f"{stash_rev}^1"]).strip()
    if not base:
        return [], set()
    touched = set(_union_files(repo, sorted(_changed(repo, base, ours) & _changed(repo, base, stash_rev))))
    return _review_union_merge(repo, base, ours, stash_rev, None), touched


def _after_push_merge(repo: Path, before: str, resolved: list[dict] | None = None) -> None:
    """Review the merge just made on top of `before`: union's leftovers plus any conflicts auto-resolved in it."""
    items, touched = _review_merge_commit(repo, before)
    if touched or resolved:
        _tidy_union_merge(repo, items + list(resolved or []), touched)


# ── in-place edits both machines made to one file: keep both sides (2026-10-26) ────────────────────────────────────
# Union (ADR 0076) suits files that are only appended to. These two are edited in place, so a real merge of them can
# genuinely conflict: suggestions.md is re-sorted by a script, memory notes are rewritten. Such a conflict is resolved
# here by keeping both sides in a readable form, recorded for a person on the same Health card as union's leftovers.
# Any conflict outside this set still stops for a person. Only the synced Claude dir; never the engine repo.
AUTO_RESOLVE_RE = re.compile(r"^(suggestions\.md|projects/[^/]+/memory/(?!MEMORY\.md$)[^/]+\.md)$")
SORT_SUGGESTIONS = Path(__file__).resolve().parents[1] / "skills" / "architecture-review" / "scripts" / "sort_suggestions.py"
ENTRY_RE = re.compile(r"^## .*$", re.MULTILINE)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "surrogateescape")).hexdigest()


def _auto_resolvable(repo: Path, path: str) -> bool:
    return Path(repo).name == UNION_REPO_NAME and bool(AUTO_RESOLVE_RE.match(path))


def _blob(repo: Path, spec: str) -> str | None:
    """`git show <spec>` exactly as stored, or None when it doesn't exist (a side that deleted the file)."""
    r = subprocess.run(["git", "show", spec], cwd=repo, capture_output=True, text=True, errors="surrogateescape")
    return r.stdout if r.returncode == 0 else None


def _keep_both_note(ours: str, theirs: str, label: str, day: str) -> tuple[str, str | None]:
    """The remote's note, then this machine's lines the remote doesn't have under a marked heading, in their order.
    Returns (text, the heading, or None when this side has no line the remote lacks: only removals, nothing to add)."""
    have = set(theirs.splitlines())
    extra = [line for line in ours.splitlines() if line not in have and line.strip()]
    if not extra:
        return theirs, None
    heading, n = f"## Also from {label} ({day})", 1
    while heading in have:
        n += 1
        heading = f"## Also from {label} ({day}, {n})"
    body = theirs if not theirs or theirs.endswith("\n") else theirs + "\n"
    return body + f"\n{heading}\n\n" + "\n".join(extra) + "\n", heading


def _entries(text: str) -> tuple[str, list[tuple[tuple[str, int], str]]]:
    """Preamble, then each `## ` entry keyed by (heading line, nth time that heading appears)."""
    matches = list(ENTRY_RE.finditer(text))
    if not matches:
        return text, []
    out, seen = [], {}
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        n = seen.get(m.group(0), 0)
        seen[m.group(0)] = n + 1
        out.append(((m.group(0), n), text[m.start():end].rstrip("\n") + "\n"))   # spacing is the sorter's, not content
    pre = text[:matches[0].start()]
    return (pre.rstrip("\n") + "\n" if pre.strip() else ""), out


def _three_way(b: str | None, o: str | None, t: str | None) -> list[str]:
    """One entry's surviving versions, the remote's first. A side that left it as it was takes the other's version
    (a deletion included); when both changed it differently, or one deleted what the other edited, both stay."""
    if o == t or o == b:
        return [t] if t is not None else []
    if t == b:
        return [o] if o is not None else []
    return [x for x in (t, o) if x is not None]


def _union_suggestions(base: str | None, ours: str, theirs: str) -> str:
    """suggestions.md, entry by entry: every entry either side added or edited, the remote's order first. Formatted
    the way sort_suggestions.py writes it, which then re-sorts it."""
    bp, bb = _entries(base or "")
    op, ob = _entries(ours)
    tp, tb = _entries(theirs)
    bd, od, td = dict(bb), dict(ob), dict(tb)
    pre = _three_way(bp if base is not None else None, op, tp)
    preamble = pre[0] if len(pre) == 1 else (tp if not pre else tp.rstrip("\n") + "\n" + "".join(
        line + "\n" for line in op.splitlines() if line not in set(tp.splitlines()) and line.strip()))
    keys = [k for k, _ in tb] + [k for k, _ in ob if k not in td]
    blocks = [v for k in keys for v in _three_way(bd.get(k), od.get(k), td.get(k))]
    body = "\n".join(b.rstrip("\n") + "\n" for b in blocks)
    return preamble.rstrip("\n") + "\n\n" + body if preamble.strip() and blocks else (preamble or body)


def _sort_suggestions(repo: Path) -> None:
    """Re-run the backlog's own sorter on this clone's file, if the engine has it. It reads $HOME/.claude, and the
    synced dir is always named .claude, so HOME is the clone's parent. Any failure leaves the file unsorted, never lost."""
    if not SORT_SUGGESTIONS.exists():
        return
    try:
        subprocess.run([sys.executable, str(SORT_SUGGESTIONS)], env={**os.environ, "HOME": str(Path(repo).parent)},
                       capture_output=True, timeout=60)
    except Exception:  # noqa: BLE001
        pass


def _unmerged(repo: Path) -> list[str]:
    out = _git(repo, ["-c", "core.quotePath=false", "diff", "--name-only", "--diff-filter=U", "-z"])
    return sorted({p for p in out.split("\0") if p})


def _resolve_scoped_conflicts(repo: Path) -> list[dict] | None:
    """Mid-merge: if every conflicted file is in the auto-resolve set, write each with both sides kept, stage it and
    return the review items (the caller commits). None, touching nothing, if any conflict is outside the set."""
    files = _unmerged(repo)
    if not files or not all(_auto_resolvable(repo, f) for f in files):
        return None
    label, day, items = machine_label(), datetime.now(timezone.utc).date().isoformat(), []
    for f in files:
        base, ours, theirs = (_blob(repo, f":{n}:{f}") for n in (1, 2, 3))
        heading = None
        if ours is None or theirs is None:   # one side deleted what the other edited: the edit survives
            text = ours if theirs is None else theirs
        elif f == "suggestions.md":
            text = _union_suggestions(base, ours, theirs)
        else:
            text, heading = _keep_both_note(ours, theirs, label, day)
        if text is None:
            return None
        path = repo / f
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, errors="surrogateescape")
        if f == "suggestions.md":
            _sort_suggestions(repo)
        final = path.read_text(errors="surrogateescape")
        if CONFLICT_MARKER_RE.search(final) and not any(CONFLICT_MARKER_RE.search(x or "") for x in (ours, theirs)):
            return None   # never stage markers this resolver made
        _git(repo, ["add", "--", f])
        items.append({"kind": "auto-resolved", "file": f, "line": heading, "digest": _digest(final)})
    return items


def _dirty_paths(repo: Path) -> list[str]:
    """Every changed path (untracked files one by one, renames as their two paths), except dirty content inside an
    embedded repo, which `git add` can't stage (marvin#430)."""
    out = _git(repo, ["-c", "core.quotePath=false", "status", "--porcelain=v1", "-z", "--no-renames", "-uall",
                      "--ignore-submodules=dirty"])
    return [entry[3:] for entry in out.split("\0") if len(entry) > 3]


def _merge_claude_dir(repo: Path) -> tuple[str, str, list[dict]]:
    """A real merge of origin/main into the synced Claude dir, whose local work is already committed (no stash):
    union (ADR 0076) and git's 3-way merge apply, then a conflict confined to the auto-resolve set is resolved and
    committed. `--ff` overrides a machine's merge.ff=only. Anything still dirty (a file under a live edit, a file
    with conflict markers, the sync log) stays out of the way: autostashed only when it is all union files, whose
    restore can't conflict; otherwise git refuses to overwrite it and the merge waits a cycle.
    Returns ("merged" | "refused" | "conflict", git's output, review items)."""
    subprocess.run(["git", "fetch", "origin"], cwd=repo, capture_output=True)
    leftover = [f for f in _dirty_paths(repo) if not _never_commit(f)]
    args = ["merge", "--ff", "--no-edit", "origin/main"]
    if leftover and len(_union_files(repo, leftover)) == len(leftover):
        args.insert(1, "--autostash")
    ok, out = _git_ok(repo, args)
    if ok:
        return "merged", out, []
    if not (repo / ".git" / "MERGE_HEAD").exists():
        return ("refused" if "would be overwritten" in out else "conflict"), out, []
    items = _resolve_scoped_conflicts(repo)
    if items is not None:
        ok, commit_out = _git_ok(repo, ["commit", "--no-edit"], env={"MARVIN_COMMIT_KIND": "auto-sync"})
        if ok:
            return "merged", out, items
        out += "\n" + commit_out
    subprocess.run(["git", "merge", "--abort"], cwd=repo, capture_output=True)
    return "conflict", out, []


def _commit_local(repo: Path, now: float | None) -> tuple[list[str], dict[str, str], list[str], bool, str]:
    """Commit every changed file except the held-back ones (under a live-edit lease, so maybe mid-write; or still
    holding conflict markers), in one auto-sync commit with the usual
    identity and message. The sync log only rides along with real work (alone, it would make two machines trade
    commits about each other's logs forever). Returns (committed, leased, broken, ok, git output)."""
    changed = [f for f in _dirty_paths(repo) if not _never_commit(f)]
    real = [f for f in changed if f != LOG_PATH.name]
    leased, broken = _leased_files(repo, real, now), _files_with_conflict_markers(repo, real)
    to_commit = [f for f in real if f not in leased and f not in broken]
    if not to_commit:
        return [], leased, broken, True, ""
    to_commit += [f for f in changed if f == LOG_PATH.name]
    spec = "\0".join(to_commit) + "\0"
    for args in (["add", "-A"], ["commit", "-m", f"auto-sync ({machine_label()}): {len(to_commit)} file(s) changed\n\n"
                                 + "\n".join(f"- {f}" for f in to_commit[:20])]):
        r = subprocess.run(["git", *args, "--pathspec-from-file=-", "--pathspec-file-nul"], cwd=repo, input=spec,
                           capture_output=True, text=True,
                           env={**os.environ, "MARVIN_COMMIT_KIND": "auto-sync", "GIT_LITERAL_PATHSPECS": "1"})
        if r.returncode != 0:
            return to_commit, leased, broken, False, r.stdout + r.stderr
    return to_commit, leased, broken, True, ""


def _held_note(leased: dict[str, str]) -> str:
    if not leased:
        return ""
    return f"; left {len(leased)} file(s) for the next cycle ({next(iter(leased.values()))})"


# ── leftover stashes already contained in HEAD ────────────────────────────────────────────────────────────────────
def _stash_contained(repo: Path, ref: str) -> bool:
    """True only when every file the stash holds (working tree, index and untracked parts) has exactly HEAD's
    content, so dropping it loses nothing. Any doubt is False."""
    for rev, paths in ((ref, _changed(repo, f"{ref}^1", ref)), (f"{ref}^2", _changed(repo, f"{ref}^1", f"{ref}^2")),
                       (f"{ref}^3", set(_stash_untracked_paths_of(repo, ref)))):
        if not paths:
            continue
        r = subprocess.run(["git", "--literal-pathspecs", "diff", "--quiet", "--no-renames", rev, "HEAD", "--", *sorted(paths)],
                           cwd=repo, capture_output=True)
        if r.returncode != 0:
            return False
    return True


def _stash_untracked_paths_of(repo: Path, ref: str) -> list[str]:
    if not _git_ok(repo, ["rev-parse", "-q", "--verify", f"{ref}^3"])[0]:
        return []
    return [p for p in _git(repo, ["ls-tree", "-r", "--name-only", f"{ref}^3"]).splitlines() if p]


def drop_contained_stashes(repo: Path, action: str) -> list[str]:
    """Drop each leftover stash whose content HEAD already has (a failed restore whose work was later committed by
    hand), and log it. A stash that isn't contained is kept: the run refuses and the stuck alert tells the owner."""
    n = len([line for line in _git(repo, ["stash", "list"]).splitlines() if line.strip()])
    dropped = []
    for i in reversed(range(n)):   # highest first, so the lower indices stay valid
        ref = f"stash@{{{i}}}"
        sha = _git(repo, ["rev-parse", "-q", "--verify", ref]).strip()
        if sha and _stash_contained(repo, ref) and _git_ok(repo, ["stash", "drop", ref])[0]:
            dropped.append(f"{ref} ({sha[:8]})")
    if dropped:
        _log(repo, action, f"dropped {len(dropped)} leftover stash(es) whose every file already matches HEAD (nothing lost; "
                           f"`git stash apply <sha>` still recovers one):", dropped)
    return dropped


# ── a stuck sync tells the owner once (2026-10-26) ─────────────────────────────────────────────────────────────────
# Before, a stuck repo only turned Health red; the laptop's Claude dir went four days without a push and nobody was
# told. One notification once a repo has been failing for STUCK_ALERT_AFTER_S, at most one per episode, and one when
# it clears. An episode is per repo: it opens on the first failed run (push or pull) and closes when every action that
# failed has since run healthy. Neutral runs (a deferral, a branch checked out) neither open nor close one.
STUCK_ALERT_AFTER_S = 30 * 60
_RUN: dict = {"failed": None, "neutral": False}


def _episodes_path() -> Path:
    return LOG_PATH.parent / "logs" / "code-sync-stuck.json"


def _neutral() -> None:
    _RUN["neutral"] = True


def _track_episode(repo: Path, action: str, failed: str | None, neutral: bool, now: float) -> None:
    path = _episodes_path()
    try:
        state = json.loads(path.read_text())
        state = state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        state = {}
    key, before = str(repo), json.dumps(state, sort_keys=True)
    ep = state.get(key) if isinstance(state.get(key), dict) else None
    if failed:
        ep = ep or {"since": now, "alerted": False, "failing": {}}
        ep.setdefault("failing", {})[action] = failed[:200]
        state[key] = ep
        minutes = int((now - float(ep.get("since") or now)) // 60)
        if not ep.get("alerted") and now - float(ep.get("since") or now) >= STUCK_ALERT_AFTER_S:
            ep["alerted"] = True
            notify("MARVIN code-sync STUCK", f"{Path(repo).name} on {machine_label()} has not synced for {minutes} min: "
                   f"{failed.splitlines()[0][:120]}", open_target=str(LOG_PATH))
            _log(repo, "alert", f"told the owner: sync has been failing for {minutes} min")
    elif ep and not neutral:
        ep.get("failing", {}).pop(action, None)
        if not ep.get("failing"):
            if ep.get("alerted"):
                minutes = int((now - float(ep.get("since") or now)) // 60)
                notify("MARVIN code-sync", f"{Path(repo).name} on {machine_label()} is back in sync (stuck {minutes} min)")
                _log(repo, "alert", f"told the owner: back in sync after {minutes} min")
            del state[key]
    if not state:
        path.unlink(missing_ok=True)
    elif json.dumps(state, sort_keys=True) != before:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=1))
        tmp.replace(path)


def _tracked(repo: Path, action: str, now: float | None, run) -> None:
    """Run one push or pull and feed its outcome to the stuck-episode tracker. A run that raises counts as failed."""
    _RUN.update(failed=None, neutral=False)
    try:
        run()
    except Exception as exc:
        _RUN["failed"] = _RUN["failed"] or f"{action} crashed: {type(exc).__name__}: {exc}"
        raise
    finally:
        try:
            _track_episode(Path(repo), action, _RUN["failed"], _RUN["neutral"], now if now is not None else time.time())
        except Exception:  # noqa: BLE001 -- the alert must never break sync itself
            pass


def _merge_remote(repo: Path) -> tuple[bool, str]:
    """Fetch + merge origin/main. On conflict, aborts the merge (tree left
    clean, nothing partially applied) rather than attempting resolution."""
    subprocess.run(["git", "fetch", "origin"], cwd=repo, capture_output=True)
    # --autostash (marvin#450): push() reaches here with uncommitted edits (sync-log.md after every push since #427, or
    # a file changed while the Mac slept mid-run), and a plain merge refuses: "local changes would be overwritten".
    # A clash when putting them back leaves a stash, which _stuck_from_previous_run() refuses on loudly.
    ok, output = _git_ok(repo, ["merge", "--autostash", "origin/main", "--no-edit"])
    if not ok:
        subprocess.run(["git", "merge", "--abort"], cwd=repo, capture_output=True)
        return False, output
    return True, output


# Machine-written history that must never ride along in an auto-sync commit, even on a Mac whose checkout still tracks it
# (one that hasn't pulled the untrack commit) or whose .gitignore was edited. Health's history was 191 of ~200 auto-sync
# commits on main (2026-10-17..21), each re-running CI and main-health (plan health-metrics-redo-2026-10-21, P0).
NEVER_COMMIT = ("bench/metrics/health-monitor.*",)


def _never_commit(path: str) -> bool:
    import fnmatch
    return any(fnmatch.fnmatch(path, pat) for pat in NEVER_COMMIT)


def _excluded_pathspecs() -> list[str]:
    return [f":(exclude,glob){pat}" for pat in NEVER_COMMIT]


def _guard_refusal(repo: Path) -> str | None:
    """ADR 0071: run the repo's own bin/pre-push-guard on what `push origin main` would publish.

    Called directly rather than trusting the git hook, so a clone whose hook was never installed is still checked.
    Repos without the script (~/.claude, whose remote is self-hosted) are not public and are skipped.
    Returns the guard's report on refusal, None when the push may go.
    """
    guard = repo / "bin" / "pre-push-guard"
    if not guard.exists():
        return None
    local = _git(repo, ["rev-parse", "HEAD"]).strip()
    remote_ok, remote = _git_ok(repo, ["rev-parse", "--verify", "-q", "origin/main"])
    remote = remote.strip() if remote_ok and remote.strip() else "0" * 40
    r = subprocess.run([str(guard), "origin"], cwd=repo, capture_output=True, text=True,
                       input=f"refs/heads/main {local} refs/heads/main {remote}\n")
    return None if r.returncode == 0 else (r.stderr.strip() or "pre-push guard refused")


def _refuse_push(repo: Path, report: str, files: list[str] | None = None) -> None:
    _log(repo, "push", f"REFUSING to push — the push guard blocked it; committed locally, NOT pushed:\n{report}", files)
    notify("MARVIN code-sync BLOCKED", f"Push guard refused a push [{repo.name}] — check sync-log.md", open_target=str(LOG_PATH))


def _merge_for(repo: Path) -> tuple[str, str, list[dict]]:
    """The merge push and pull use: the Claude dir's real merge, or the engine's (and instance's) --autostash one."""
    if Path(repo).name == UNION_REPO_NAME:
        return _merge_claude_dir(repo)
    ok, out = _merge_remote(repo)
    return ("merged" if ok else "conflict"), out, []


def _refuse_if_stuck(repo: Path, action: str) -> bool:
    drop_contained_stashes(repo, action)
    stuck = _stuck_from_previous_run(repo)
    if stuck:
        # No banner per run any more: the stuck-episode tracker tells the owner once, after STUCK_ALERT_AFTER_S.
        _log(repo, action, f"REFUSING to run — {stuck}, needs manual resolution before {action} can proceed")
        return True
    return False


def push(repo: Path, now: float | None = None) -> None:
    _tracked(repo, "push", now, lambda: _push(Path(repo), now))


def _push(repo: Path, now: float | None) -> None:
    label = machine_label()
    heal_stale_index_lock(repo)
    ensure_union_rule(repo)   # before any merge below (ADR 0076)

    if _refuse_if_stuck(repo, "push"):
        return
    if _skip_off_main(repo, "push"):
        _neutral()
        return

    # sync-log.md itself doesn't count as work: its own last entry trails every push, and would otherwise make every
    # push think there's real work to do. Dirty content inside an embedded repo is not ours to commit (marvin#430).
    real_changes = [f for f in _dirty_paths(repo) if f != LOG_PATH.name and not _never_commit(f)]
    if not real_changes:
        # Working tree can be clean while HEAD still holds commits that were
        # never pushed — e.g. a manual conflict-resolution `git commit` made
        # outside this script, or a pull that committed local work first.
        subprocess.run(["git", "fetch", "origin"], cwd=repo, capture_output=True)
        ahead = _git(repo, ["rev-list", "--count", "origin/main..HEAD"]).strip()
        if ahead in ("", "0"):
            # Silent when healthy, but a failure must be ended by something: Health keeps a streak per action
            # (marvin#422) and a no-op push logs nothing, so a fixed push stayed "stuck" forever (marvin#438).
            if _last_own_push_failed(repo):
                _log(repo, "push", "nothing to push — earlier failure cleared")
            return
        refused = _guard_refusal(repo)
        if refused:
            _refuse_push(repo, refused)
            return
        push_ok, push_out = _git_ok(repo, ["push", "origin", "main"])
        if push_ok:
            _log(repo, "push", f"pushed {ahead} already-committed change(s) found on a clean working tree")
            notify("MARVIN code-sync", f"Pushed {ahead} pending commit(s) from {label} [{repo.name}]")
            return
        _push_after_merge(repo, f"pushed {ahead} already-committed change(s) (merged remote changes first)", [],
                          "CONFLICT merging remote while pushing pre-existing commits — needs manual resolution")
        return

    # Partial push (2026-10-26): a file a live session is editing, or one still holding conflict markers, waits; the
    # rest is committed and pushed now. Deferring everything for one hot file kept the laptop from pushing for 4 days.
    committed, leased, broken, commit_ok, commit_out = _commit_local(repo, now)
    if not commit_ok:
        _log(repo, "push", f"commit failed:\n{commit_out}", committed)
        return
    if not committed:
        if broken:
            _refuse_markers(repo, broken, 0)
            return
        _log(repo, "push", f"deferring — {next(iter(leased.values()))}; will retry next cycle")
        _neutral()
        return

    # Logged only once the outcome is known (marvin#427); sync-log.md is merge=union, so a trailing entry is harmless.
    refused = _guard_refusal(repo)
    if refused:
        _refuse_push(repo, refused, committed)
        return
    push_ok, push_out = _git_ok(repo, ["push", "origin", "main"])
    if push_ok:
        _pushed(repo, f"committed + pushed {len(committed)} file(s){_held_note(leased)}", committed, broken)
        return
    # Rejected, most likely non-fast-forward — merge the remote's new commits into ours, then retry once.
    _push_after_merge(repo, f"committed + pushed {len(committed)} file(s) (merged remote changes first){_held_note(leased)}",
                      committed, "CONFLICT merging remote after push rejection — committed locally, NOT pushed "
                      f"(origin/main does not have it); local commit preserved, needs manual resolution:\n{push_out}", broken)


def _refuse_markers(repo: Path, broken: list[str], n_pushed: int) -> None:
    rest = f"; the other {n_pushed} file(s) were committed + pushed" if n_pushed else ""
    _log(repo, "push", f"REFUSING to commit — conflict markers found in {len(broken)} file(s), needs manual resolution "
                       f"before they can sync{rest}:", broken)


def _pushed(repo: Path, summary: str, files: list[str], broken: list[str]) -> None:
    notify("MARVIN code-sync", f"Pushed {len(files)} file(s) from {machine_label()} [{repo.name}]")
    if broken:   # the push went, but a file still needs a person: the entry must read as a failure (Health, alert)
        _refuse_markers(repo, broken, len(files))
    else:
        _log(repo, "push", summary, files)


def _push_after_merge(repo: Path, summary: str, files: list[str], conflict_summary: str, broken: list[str] = ()) -> None:
    before_merge = _git(repo, ["rev-parse", "HEAD"]).strip()
    state, merge_output, resolved = _merge_for(repo)
    if state == "refused":
        _log(repo, "push", f"deferring — committed locally, but a file still being edited here changed on the remote "
                           f"too; will merge next cycle:\n{merge_output}", files)
        _neutral()
        return
    if state != "merged":
        _log(repo, "push", f"{conflict_summary}\n{merge_output}", files)
        return
    _after_push_merge(repo, before_merge, resolved)
    retry_ok, retry_out = _git_ok(repo, ["push", "origin", "main"])
    if retry_ok:
        _pushed(repo, summary, files, list(broken))
    else:
        _log(repo, "push", f"push failed even after merge retry — committed locally, NOT pushed:\n{retry_out}", files)


def pull(repo: Path, now: float | None = None) -> None:
    _tracked(repo, "pull", now, lambda: _pull(Path(repo), now))


def _pull(repo: Path, now: float | None) -> None:
    heal_stale_index_lock(repo)
    ensure_union_rule(repo)   # before the stash, the merge and the pop (ADR 0076): all three honour it
    if _refuse_if_stuck(repo, "pull"):
        return
    if _skip_off_main(repo, "pull"):
        _neutral()
        return
    if repo.name == UNION_REPO_NAME:
        _pull_commit_first(repo, now)
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
        return

    after = _git(repo, ["rev-parse", "HEAD"]).strip()
    union_items, union_touched = _review_merge_commit(repo, before) if after != before else ([], set())

    if stashed:
        stash_rev = _git(repo, ["rev-parse", "-q", "--verify", "stash@{0}"]).strip()
        pop_ok, pop_out = _git_ok(repo, ["stash", "pop"])
        if not pop_ok:
            if UNTRACKED_OVERWRITE_RE.search(pop_out):
                candidates = [p for p in _stash_untracked_paths(repo) if (repo / p).exists()]
                if candidates and all(_is_bench_metrics_runlog(p) for p in candidates):
                    if _resolve_metrics_stash_collision(repo, candidates):
                        return
            _log(repo, "pull", f"pulled cleanly, but restoring local WIP conflicted — stash preserved, resolve by hand (`git stash list` / `git stash pop`):\n{pop_out}")
            return
        if stash_rev:
            items, touched = _review_stash_pop(repo, stash_rev, after)
            union_items, union_touched = union_items + items, union_touched | touched

    if union_touched:
        _tidy_union_merge(repo, union_items, union_touched)

    if before == after and not stashed:
        # Genuinely nothing happened — no merge, no WIP involved. Not worth
        # a log entry: logging (and self-flushing) a pure no-op only to have
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


def _pull_commit_first(repo: Path, now: float | None) -> None:
    """The synced Claude dir's pull (2026-10-26): commit local work first, then a real merge — no stash, no pop.
    A stash of days of work popped over the remote's changes conflicted more the bigger it grew, and each conflict
    stopped every later run. Committed work can't be lost by a merge; a crash between the two steps leaves an
    ordinary local commit the next run merges or pushes. The commit is pushed by the next push, never here: pull
    stays quiet (see the note at the end of the engine's pull)."""
    committed, leased, broken, ok, out = _commit_local(repo, now)
    if not ok:
        _log(repo, "pull", f"commit failed:\n{out}", committed)
        return
    before = _git(repo, ["rev-parse", "HEAD"]).strip()
    state, merge_output, resolved = _merge_claude_dir(repo)
    if state == "refused":
        _log(repo, "pull", f"deferring the merge — a file still being edited here changed on the remote too; "
                           f"will merge next cycle{_held_note(leased)}:\n{merge_output}")
        _neutral()
        return
    if state != "merged":
        kept = f"; this machine's {len(committed)} changed file(s) are committed locally, nothing lost" if committed else ""
        _log(repo, "pull", f"CONFLICT merging origin/main — merge aborted, tree left clean{kept}:\n{merge_output}")
        return
    after = _git(repo, ["rev-parse", "HEAD"]).strip()
    _after_push_merge(repo, before, resolved)
    if before == after and not committed:
        return   # a pure no-op logs nothing (see the engine's pull)
    first = f"committed {len(committed)} local file(s), then " if committed else ""
    if before == after:
        _log(repo, "pull", f"{first}already up to date{_held_note(leased)}", committed)
    else:
        _log(repo, "pull", f"{first}merged {before[:8]}..{after[:8]}{_held_note(leased)}", committed)


sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
def _mirror_log(repo: Path, line: str) -> None:
    MIRROR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with MIRROR_LOG_PATH.open("a") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()} [{repo}] {line}\n")


def _capture_box_memory(repo: Path) -> None:
    """ADR 0082: before the reset below throws away a box session's memory and handoff edits, save them as box items
    in the box outbox, for the primary Mac to pull and review. Only for the ~/.claude mirror; never stops the mirror."""
    try:
        if Path(repo).expanduser().resolve() != (Path.home() / ".claude").resolve():
            return
        import box_memory_export
        n = box_memory_export.capture(Path(repo))
        if n:
            _mirror_log(repo, f"saved {n} memory/handoff change(s) to the box outbox for review")
    except Exception as e:
        _mirror_log(repo, f"box memory capture failed: {str(e)[:200]}")


def mirror(repo: Path) -> None:
    """Code sync for a pull-only node (mac-mini-2012, ADR 0069): make `repo` identical to origin/main.

    Never pushes and never writes the synced sync-log.md. Anything on the box that would be discarded -- local commits,
    edits to tracked files, untracked files an incoming file would overwrite -- is saved under MIRROR_BACKUP_DIR first.
    Untracked and ignored files are otherwise left alone (Claude's sign-in lives in one). A failure leaves the tree as
    it was and goes to the error log, so Health sees it."""
    ok, out = _git_ok(repo, ["fetch", "-q", "origin", "main"])
    if not ok:
        _mirror_log(repo, f"fetch failed: {out.strip()[:200]}")
        error_log.record("sync:mirror", f"fetch failed in {Path(repo).name}", raw=out)
        return
    target = _git(repo, ["rev-parse", "origin/main"]).strip()
    head = _git(repo, ["rev-parse", "HEAD"]).strip()
    dirty = _git(repo, ["status", "--porcelain", "--untracked-files=no"]).strip()
    if head == target and not dirty:
        return

    if dirty:
        _capture_box_memory(repo)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = MIRROR_BACKUP_DIR / Path(repo).name / stamp
    saved = []
    if dirty:
        backup.mkdir(parents=True, exist_ok=True)
        (backup / "uncommitted.patch").write_text(_git(repo, ["diff", "HEAD"]))
        saved.append("uncommitted edits")
    local_commits = _git(repo, ["rev-list", f"{target}..HEAD"]).split()
    if local_commits:
        backup.mkdir(parents=True, exist_ok=True)
        (backup / "local-commits.patch").write_text(_git(repo, ["format-patch", "--stdout", f"{target}..HEAD"]))
        saved.append(f"{len(local_commits)} local commit(s)")
    incoming = set(_git(repo, ["ls-tree", "-r", "--name-only", target]).splitlines())
    clobbered = [f for f in _git(repo, ["ls-files", "--others", "--exclude-standard"]).splitlines() if f in incoming]
    for f in clobbered:
        dest = backup / "untracked" / f
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((Path(repo) / f).read_bytes())
    if clobbered:
        saved.append(f"{len(clobbered)} untracked file(s) an incoming file replaces")

    ok, out = _git_ok(repo, ["reset", "-q", "--hard", target])
    if not ok:
        _mirror_log(repo, f"reset failed: {out.strip()[:200]}")
        error_log.record("sync:mirror", f"reset failed in {Path(repo).name}", raw=out)
        return
    _mirror_log(repo, f"now at {target[:8]}" + (f"; saved {', '.join(saved)} to {backup}" if saved else ""))


import job_events  # noqa: E402  (run log shown in the dashboard's Health tab)


@job_events.reported("code-sync-push", "Code sync (git pull/push)")
def peer_care_after_sync(action: str, repo: Path, spawn=subprocess.Popen) -> None:
    """marvin#847 (design #769 section 3, "heartbeat missing"): the end of each engine pull (mirror on the 2012) checks the peers this
    machine watches. It adds no clock: it rides the sync that runs anyway. Detached, so a slow probe (or a wake that
    waits two minutes) never holds the sync up; a failure to start it never breaks the sync."""
    if action not in ("pull", "mirror") or Path(repo).expanduser().resolve() != DEFAULT_REPO.expanduser().resolve():
        return
    script = Path(__file__).resolve().parent / "peer_care.py"
    try:
        spawn([sys.executable, str(script), "check-all", "--trigger", "code-sync"], start_new_session=True,
              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def main() -> None:
    if len(sys.argv) not in (2, 3) or sys.argv[1] not in ("push", "pull", "mirror"):
        print("usage: code_sync.py {push|pull|mirror} [repo-path]", file=sys.stderr)
        sys.exit(1)
    repo = Path(sys.argv[2]).expanduser() if len(sys.argv) == 3 else DEFAULT_REPO
    asked = sys.argv[1]
    import machine_profile
    if asked != "mirror" and machine_profile.pull_only():
        # ADR 0069: a pull-only node never commits or pushes. Callers written for the Macs (the session-start hook's
        # `pull`, a handoff's `push`) get a mirror and nothing, so a session at the box can't touch the synced tree.
        if asked == "push":
            return
        sys.argv[1] = "mirror"
    action = {"push": push, "pull": pull, "mirror": mirror}[sys.argv[1]]
    # ADR 0071: the owner's private instance is its own repo nested at <engine>/instance/; it syncs with the engine,
    # so every existing caller (launchd job, handoff hook) covers it with no config. No instance (a fresh install,
    # the Kali node by design) syncs exactly as before. try/finally: a failing engine step never strands it.
    nested = repo / "instance"
    try:
        job_events.step(f"{sys.argv[1]} {repo}")
        action(repo)
    finally:
        if (nested / ".git").exists():
            job_events.step(f"{sys.argv[1]} {nested}")
            action(nested)
        peer_care_after_sync(sys.argv[1], repo)


if __name__ == "__main__":
    main()
