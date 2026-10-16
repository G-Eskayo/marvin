"""Is the base branch green? Checked on a clean checkout of origin/main, recorded, and shown in Health.

On 2026-10-07 main went red because of a bad test, and nobody knew until a PR was denied for it. This keeps a record:
whenever origin/main has a new commit, run the whole Python suite on a clean checkout and write the answer to
~/.claude/logs/main-health.json (read by the Health check `main:green`). The ticket-pipeline scan starts it in the
background, so a scan never waits on it. Unlike the merge gate it runs EVERYTHING, including the tests that read other
repos' data, which the gate leaves out.

Concurrent scans are serialized by an atomic lock file: only one suite runs at a time. If a scan is already running,
`refresh()` returns immediately with `skipped: True` so the ticket pipeline never waits more than a few seconds.

Diffs touching only docs and logs are skipped: their verdict never changes the test result, so we carry forward the
prior state and save the suite runtime. This is the fix for issue #457 (Approve & Merge pile-up on 2026-10-15).

    python main_health.py refresh        check now (skips when origin/main has not moved)
"""
from __future__ import annotations

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

SUITE_TIMEOUT_S = 1800  # 30 minutes max for the full test suite

# Paths whose changes cannot affect test results (issue #457): diffs touching ONLY
# these patterns skip the suite and carry forward the prior verdict.
SKIP_PATTERNS = [
    "*.md",              # docs/adr, docs/design, any .md file at any depth
    "*.log",             # .claude/logs/*.log, etc
    "*sync-log.md",      # .claude/sync-log.md, cross-machine sync records
    "bench/metrics/**",  # microbenchmark results, not tests
    "docs/**",           # doc-only commits that can't affect code
]


def _lock_info(lock_path: Path) -> dict | None:
    """Read and parse a lock file. Returns {pid, started_at} or None if unreadable/invalid."""
    try:
        data = json.loads(lock_path.read_text())
        if isinstance(data, dict) and "pid" in data and "started_at" in data:
            return data
    except (OSError, ValueError):
        pass
    return None


def _lock_is_stale(lock_info: dict, now: datetime) -> bool:
    """Check if a lock's PID is dead or its started_at is past the suite timeout."""
    pid = lock_info.get("pid")
    if pid is not None:
        try:
            os.kill(pid, 0)  # signal 0: check if process exists without sending a signal
        except (OSError, ProcessLookupError):
            return True  # PID is dead
    started_str = lock_info.get("started_at")
    if started_str:
        try:
            started = datetime.fromisoformat(started_str)
            elapsed = (now - started).total_seconds()
            if elapsed > SUITE_TIMEOUT_S:
                return True  # exceeded timeout
        except ValueError:
            return True  # unparseable timestamp
    return False


def _acquire_lock(lock_path: Path, pid: int, now: datetime) -> bool:
    """Atomically acquire a lock. Returns True on success, False if already held by a live process.
    If the lock exists but is stale, take it over. Raises on unexpected errors."""
    lock_data = {"pid": pid, "started_at": now.isoformat()}
    lock_json = json.dumps(lock_data)

    # Ensure parent directory exists
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    # Try atomic create (fail if already exists).
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        os.write(fd, lock_json.encode())
        os.close(fd)
        return True
    except FileExistsError:
        pass  # lock already exists; check if it's stale
    except OSError as e:
        # Permission errors, disk full, etc. — fail safe, don't crash
        raise e

    # Lock exists; check staleness and retry once if stale.
    info = _lock_info(lock_path)
    if info is None or _lock_is_stale(info, now):
        # Stale lock: remove and retry.
        try:
            lock_path.unlink()
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            os.write(fd, lock_json.encode())
            os.close(fd)
            return True
        except (FileExistsError, OSError):
            return False  # Someone else took it or it failed again; give up
    return False  # Lock is held by a live process


def _release_lock(lock_path: Path, pid: int) -> None:
    """Remove the lock file only if it's still ours (PID matches)."""
    info = _lock_info(lock_path)
    if info and info.get("pid") == pid:
        try:
            lock_path.unlink()
        except OSError:
            pass  # best effort; lock will age out anyway


def _changed_paths(old_sha: str | None, new_sha: str, repo_dir: Path = REPO_DIR) -> list[str] | None:
    """Return the list of paths changed between old_sha and new_sha. Returns None on error."""
    if old_sha is None:
        return None  # can't diff against a missing prior SHA
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{old_sha}..{new_sha}"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        return result.stdout.strip().split("\n") if result.stdout.strip() else []
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return None  # git failed; fail safe and run the suite


def _skippable(paths: list[str]) -> bool:
    """Check if a list of paths matches ONLY skip patterns. Empty list is vacuously true."""
    if not paths:
        return True
    for p in paths:
        if not any(fnmatch.fnmatch(p, pattern) for pattern in SKIP_PATTERNS):
            return False  # found a path that's not skippable
    return True


def failed_ids(output: str) -> list[str]:
    return [m.group(1) for m in re.finditer(r"^FAILED\s+(\S+)", output, re.M)]


def _head() -> str | None:
    try:
        subprocess.run(["git", "fetch", "-q", "origin", "main"], cwd=REPO_DIR, capture_output=True, timeout=60, check=True)
        return subprocess.run(["git", "rev-parse", "--short", "origin/main"], cwd=REPO_DIR, capture_output=True, text=True, timeout=20, check=True).stdout.strip()
    except Exception:  # noqa: BLE001 -- offline: keep the last answer
        return None


def _run_suite() -> tuple[bool, list[str], str]:
    tmp = tempfile.mkdtemp(prefix="main-health-")
    try:
        subprocess.run(["git", "worktree", "add", "-q", "--detach", tmp, "origin/main"], cwd=REPO_DIR, check=True, capture_output=True, timeout=120)
        p = subprocess.run([str(VENV_PY), "-m", "pytest", "lib/tests", "-q", "-p", "no:cacheprovider"], cwd=tmp,
                           capture_output=True, text=True, timeout=SUITE_TIMEOUT_S)
        last = [l for l in p.stdout.strip().splitlines() if l.strip()][-1:] or [""]
        return p.returncode == 0, failed_ids(p.stdout), last[0].strip(" =")
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", tmp], cwd=REPO_DIR, capture_output=True)


def refresh(state_path: Path = STATE, head=_head, run_suite=_run_suite, now: datetime | None = None,
            lock_path: Path = LOCK, changed_paths=_changed_paths) -> dict:
    now = now or datetime.now(timezone.utc)
    prior = {}
    try:
        prior = json.loads(Path(state_path).read_text())
    except (OSError, ValueError):
        pass
    sha = head()
    if sha is None or sha == prior.get("sha"):
        return {**prior, "ran": False}

    # Try to acquire the lock. If another instance is running, return skipped.
    pid = os.getpid()
    try:
        if not _acquire_lock(lock_path, pid, now):
            return {**prior, "ran": False, "skipped": "already running"}
    except OSError:
        # Unexpected error acquiring lock (permissions, etc.); skip gracefully
        return {**prior, "ran": False}

    try:
        # Check if we can skip this SHA based on changed paths.
        prior_sha = prior.get("sha")
        # First-ever run: always run the suite (fail safe: nothing to diff against)
        if prior_sha is not None:
            paths = changed_paths(prior_sha, sha)
            if paths is not None and _skippable(paths):
                # Diff touches only skip-pattern files; carry forward the prior verdict
                carried = {k: prior[k] for k in ["ok", "failed", "summary"] if k in prior}
                res = {
                    "sha": sha,
                    "checked_at": now.isoformat(),
                    "carried": True,
                    "carried_from": prior_sha,
                    "ran": True,
                    **carried,  # ok, failed, summary from prior
                }
                Path(state_path).parent.mkdir(parents=True, exist_ok=True)
                Path(state_path).write_text(json.dumps(res))
                return res

        # Run the suite (inside try/except so exceptions don't corrupt state).
        try:
            ok, failed, summary = run_suite()
        except Exception:
            # Suite raised; don't update state, leave it unchanged for the next attempt
            return {**prior, "ran": False}

        res = {"sha": sha, "ok": ok, "failed": failed, "summary": summary, "checked_at": now.isoformat(), "ran": True}
        Path(state_path).parent.mkdir(parents=True, exist_ok=True)
        Path(state_path).write_text(json.dumps(res))
        return res
    finally:
        _release_lock(lock_path, pid)


if __name__ == "__main__":
    if sys.argv[1:] != ["refresh"]:
        sys.exit("usage: main_health.py refresh")
    print(json.dumps(refresh()))
