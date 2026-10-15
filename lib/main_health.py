"""Is the base branch green? Checked on a clean checkout of origin/main, recorded, and shown in Health.

On 2026-10-07 main went red because of a bad test, and nobody knew until a PR was denied for it. This keeps a record:
whenever origin/main has a new commit, run the whole Python suite on a clean checkout and write the answer to
~/.claude/logs/main-health.json (read by the Health check `main:green`). The ticket-pipeline scan starts it in the
background, so a scan never waits on it. Unlike the merge gate it runs EVERYTHING, including the tests that read other
repos' data, which the gate leaves out.

A single-flight lock prevents concurrent runs from starving the machine. Test-irrelevant changes (docs, logs, auto-sync
commits) are skipped — their verdict is carried forward from the last real run, tagged with the sha that was actually
tested.

    python main_health.py refresh        check now (skips when origin/main has not moved)
"""
from __future__ import annotations

import fcntl
import fnmatch
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

STATE = Path.home() / ".claude" / "logs" / "main-health.json"
LOCK = Path.home() / ".claude" / "logs" / "main-health.lock"
REPO_DIR = Path.home() / ".agents"
VENV_PY = REPO_DIR / "venv" / "bin" / "python"

SUITE_TIMEOUT_S = 1800
WORKTREE_REMOVE_TIMEOUT_S = 60
LOCK_STALE_SECONDS = SUITE_TIMEOUT_S + 600

# Repo docs that real tests in lib/tests read from disk and assert content about (confirmed 2026-10-15,
# ticket #457 review): never carry past a change to these even though they match TEST_IRRELEVANT below.
# A future test that starts reading a new doc file must add it here too.
TEST_RELEVANT_DOCS = (
    "CONTEXT.md",           # lib/tests/* check domain docs for consistency
    "docs/north-stars.md",  # lib/tests/test_north_stars.py asserts its exact text
    "docs/impact.md",       # lib/tests/test_impact_showcase.py asserts headings + evidence links
    "README.md",            # lib/tests/test_impact_showcase.py asserts a docs/impact.md link inside it
)

# Patterns for changes that do not affect pytest results (fnmatch, applies recursively).
# When a commit contains ONLY these paths, the prior test verdict is carried forward.
TEST_IRRELEVANT = (
    "bench/metrics/*", # Benchmark metrics are recorded but don't change the test suite
    "*.md",            # Markdown files (including repo root READMEs)
    "*.log",           # Log files
    "sync-log.md",     # Auto-sync log (may be re-edited by code-sync on every run)
)


def failed_ids(output: str) -> list[str]:
    return [m.group(1) for m in re.finditer(r"^FAILED\s+(\S+)", output, re.M)]


def _is_test_irrelevant(path: str) -> bool:
    """Whether a changed path does not affect pytest results."""
    if path in TEST_RELEVANT_DOCS:
        return False
    if path.startswith("lib/tests/"):
        return False
    return any(fnmatch.fnmatch(path, pattern) for pattern in TEST_IRRELEVANT)


def _lock_is_stale(lock_path: Path, now: datetime | None = None) -> bool:
    """Whether a lock file is stale (dead process or too old)."""
    now = now or datetime.now(timezone.utc)
    try:
        data = json.loads(lock_path.read_text())
        pid = data.get("pid")
        started_at_str = data.get("started_at")
        if not pid or not started_at_str:
            return True
        started_at = datetime.fromisoformat(started_at_str)
        age = (now - started_at).total_seconds()
        if age > LOCK_STALE_SECONDS:
            return True
        # Check if PID is alive by sending signal 0 (no-op, just liveness check)
        try:
            os.kill(pid, 0)
            return False  # Process is alive
        except ProcessLookupError:
            return True  # Process is dead
        except PermissionError:
            return False  # Exists, just owned by someone else -- still alive
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return True  # Lock is unreadable, corrupted, or malformed -- don't let it wedge forever


def _acquire_lock(lock_path: Path, now: datetime | None = None) -> bool:
    """Try to acquire the lock. Returns True if acquired, False if a live run already holds it.

    The stale-or-not decision and the takeover write happen inside a brief OS flock on a persistent
    sidecar file, so two processes racing to steal the same stale lock can never both win: whichever
    one is inside the flock writes the fresh lock; the other reads it back as live and backs off.
    The sidecar is never deleted -- it only ever guards this one short critical section, not the
    lifetime of a run, so there is nothing to clean up and nothing to go stale.
    """
    now = now or datetime.now(timezone.utc)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path = lock_path.with_name(lock_path.name + ".meta")
    meta_fd = os.open(str(meta_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(meta_fd, fcntl.LOCK_EX)
        if lock_path.exists() and not _lock_is_stale(lock_path, now=now):
            return False
        lock_path.write_text(json.dumps({"pid": os.getpid(), "started_at": now.isoformat()}))
        return True
    finally:
        fcntl.flock(meta_fd, fcntl.LOCK_UN)
        os.close(meta_fd)


def _release_lock(lock_path: Path) -> None:
    """Release the lock by removing the lock file, but only if we own it."""
    meta_path = lock_path.with_name(lock_path.name + ".meta")
    meta_fd = os.open(str(meta_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(meta_fd, fcntl.LOCK_EX)
        # Check pid to ensure we own the lock before unlinking
        try:
            data = json.loads(lock_path.read_text())
            if data.get("pid") == os.getpid():
                lock_path.unlink()
        except (OSError, ValueError, json.JSONDecodeError):
            pass  # Lock already gone or unreadable, nothing to do
    finally:
        fcntl.flock(meta_fd, fcntl.LOCK_UN)
        os.close(meta_fd)


def _changed_paths(prior_sha: str, new_sha: str) -> list[str] | None:
    """Get the list of changed file paths between two commits. Returns None if diff fails."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{prior_sha}..{new_sha}"],
            cwd=REPO_DIR,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        return result.stdout.strip().split("\n") if result.stdout.strip() else []
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
        return None


def _head() -> str | None:
    try:
        subprocess.run(["git", "fetch", "-q", "origin", "main"], cwd=REPO_DIR, capture_output=True, timeout=60, check=True)
        return subprocess.run(["git", "rev-parse", "--short", "origin/main"], cwd=REPO_DIR, capture_output=True, text=True, timeout=20, check=True).stdout.strip()
    except Exception:  # noqa: BLE001 -- offline: keep the last answer
        return None


def _run_suite(run=subprocess.run) -> tuple[bool, list[str], str]:
    tmp = tempfile.mkdtemp(prefix="main-health-")
    try:
        run(["git", "worktree", "add", "-q", "--detach", tmp, "origin/main"], cwd=REPO_DIR, check=True, capture_output=True, timeout=120)
        p = run([str(VENV_PY), "-m", "pytest", "lib/tests", "-q", "-p", "no:cacheprovider"], cwd=tmp,
                capture_output=True, text=True, timeout=SUITE_TIMEOUT_S)
        last = [l for l in p.stdout.strip().splitlines() if l.strip()][-1:] or [""]
        return p.returncode == 0, failed_ids(p.stdout), last[0].strip(" =")
    finally:
        run(["git", "worktree", "remove", "--force", tmp], cwd=REPO_DIR, capture_output=True, timeout=WORKTREE_REMOVE_TIMEOUT_S)


def refresh(state_path: Path = STATE, lock_path: Path = LOCK, head=_head, run_suite=_run_suite,
             changed_paths=_changed_paths, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    prior = {}
    try:
        prior = json.loads(Path(state_path).read_text())
    except (OSError, ValueError):
        pass

    # Try to acquire lock before fetching head
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if not _acquire_lock(lock_path, now=now):
        return {**prior, "ran": False, "skipped": "already running"}

    try:
        sha = head()
        if sha is None or sha == prior.get("sha"):
            return {**prior, "ran": False}

        # Check if we can carry forward the previous result (test-irrelevant changes only)
        if prior.get("ok") is True:  # Only carry green; red is a terminal failure, never carried forward
            # If already carried, compare against the original tested sha, not the intermediate carried one
            test_ref_sha = prior.get("carried_from") or prior.get("sha")
            paths = changed_paths(test_ref_sha, sha)
            if paths is not None and all(_is_test_irrelevant(p) for p in paths):
                # All changes are test-irrelevant, carry the prior verdict
                res = {
                    "sha": sha,
                    "ok": prior.get("ok"),
                    "failed": prior.get("failed", []),
                    "summary": prior.get("summary", ""),
                    "checked_at": now.isoformat(),
                    "carried": True,
                    "carried_from": test_ref_sha,
                    "ran": False,
                }
                Path(state_path).parent.mkdir(parents=True, exist_ok=True)
                Path(state_path).write_text(json.dumps({k: v for k, v in res.items() if k != "ran"}))
                return res

        # Run the full suite
        ok, failed, summary = run_suite()
        res = {"sha": sha, "ok": ok, "failed": failed, "summary": summary, "checked_at": now.isoformat(), "ran": True}
        Path(state_path).parent.mkdir(parents=True, exist_ok=True)
        Path(state_path).write_text(json.dumps({k: v for k, v in res.items() if k != "ran"}))
        return res
    finally:
        _release_lock(lock_path)


if __name__ == "__main__":
    if sys.argv[1:] != ["refresh"]:
        sys.exit("usage: main_health.py refresh")
    print(json.dumps(refresh()))
