"""Is the base branch green? Checked on a clean checkout of origin/main, recorded, and shown in Health.

On 2026-10-07 main went red because of a bad test, and nobody knew until a PR was denied for it. This keeps a record:
whenever origin/main has a new commit, run the whole Python suite on a clean checkout and write the answer to
~/.claude/logs/main-health.json (read by the Health check `main:green`). The ticket-pipeline scan starts it in the
background, so a scan never waits on it. Unlike the merge gate it runs EVERYTHING, including the tests that read other
repos' data, which the gate leaves out.

Single-flight lock: concurrent refreshes are allowed, but only one test run per git commit. If the lock is
stale (the prior run crashed or took >30min), a new run takes over. Skips test when only docs/bench-metrics changed.

    python main_health.py refresh        check now (skips when origin/main has not moved)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

STATE = Path.home() / ".claude" / "logs" / "main-health.json"
REPO_DIR = Path.home() / ".agents"
VENV_PY = REPO_DIR / "venv" / "bin" / "python"
SUITE_TIMEOUT_S = 1800
WORKTREE_SETUP_S = 120


def failed_ids(output: str) -> list[str]:
    return [m.group(1) for m in re.finditer(r"^FAILED\s+(\S+)", output, re.M)]


# Skip-path logic: changes to only these paths do not trigger a suite run.
# Pattern: docs/ and bench/metrics/ are documentation; .md files are typically not test-critical.
# If ALL changed files match these patterns, the suite run is skipped, and the prior result is carried forward.
_SKIP_PREFIXES = ("docs/", "bench/metrics/")
_SKIP_SUFFIX = ".md"


def _is_skippable(path: str) -> bool:
    """A file path is skippable if it starts with a skip-prefix or ends with .md."""
    return path.endswith(_SKIP_SUFFIX) or any(path.startswith(p) for p in _SKIP_PREFIXES)


def _changed_paths(repo_dir: Path, old_sha: str, new_sha: str) -> list[str] | None:
    """Return list of file paths changed between two commits, or None if the diff fails."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", old_sha, new_sha],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        return result.stdout.strip().splitlines()
    except Exception:
        return None


def _pid_alive(pid: int) -> bool:
    """Check if a process is still running. Returns True for PermissionError (process exists, different owner)."""
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except (OSError, ProcessLookupError):
        return False


def _is_stale(lock_mtime: float, now: datetime | None = None) -> bool:
    """Check if lock file is older than SUITE_TIMEOUT_S + WORKTREE_SETUP_S."""
    now = now or datetime.now(timezone.utc)
    return (now.timestamp() - lock_mtime) >= (SUITE_TIMEOUT_S + WORKTREE_SETUP_S)


def _acquire_lock(lock_path: Path) -> bool:
    """Acquire the single-flight lock atomically. Returns True if acquired.
    If lock exists but the process is dead or lock is stale, takes it over."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    payload = f"{os.getpid()}\n{datetime.now(timezone.utc).timestamp()}"
    try:
        # Try to create the lock file atomically (fails if it exists).
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        os.write(fd, payload.encode())
        os.close(fd)
        return True
    except FileExistsError:
        # Lock exists. Check if we can take it over.
        try:
            content = lock_path.read_text().strip().split("\n")
            if len(content) >= 1:
                pid = int(content[0])
                mtime = float(content[1]) if len(content) > 1 else 0
                # Take over if process is dead or lock is stale.
                if not _pid_alive(pid) or _is_stale(mtime):
                    # Unlink the stale/dead lock and retry the atomic create.
                    try:
                        os.unlink(lock_path)
                    except FileNotFoundError:
                        # Someone else already took it; we lost the race.
                        return False
                    # Retry the atomic create.
                    try:
                        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
                        os.write(fd, payload.encode())
                        os.close(fd)
                        return True
                    except FileExistsError:
                        # Lost race to another process.
                        return False
        except (ValueError, OSError, IndexError):
            pass
        return False
    except OSError:
        return False


def _release_lock(lock_path: Path) -> None:
    """Release the lock by deleting the file, but only if its PID matches the current process. Never raises."""
    try:
        content = lock_path.read_text().strip().split("\n")
        if content and int(content[0]) == os.getpid():
            lock_path.unlink()
    except (OSError, ValueError, IndexError):
        pass


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
            repo_dir: Path | None = None, lock_path: Path | None = None, changed_paths=_changed_paths) -> dict:
    now = now or datetime.now(timezone.utc)
    repo_dir = repo_dir or REPO_DIR
    lock_path = lock_path or (Path(state_path).parent / "main-health.lock")
    prior = {}
    try:
        prior = json.loads(Path(state_path).read_text())
    except (OSError, ValueError):
        pass
    sha = head()
    if sha is None or sha == prior.get("sha"):
        return {**prior, "ran": False}

    # Check for carry: if only skippable files changed, skip the run and carry the prior result.
    tested_sha = prior.get("tested_sha") or prior.get("sha")
    if tested_sha and tested_sha != sha:
        paths = changed_paths(repo_dir, tested_sha, sha)
        if paths is not None and all(_is_skippable(p) for p in paths):
            # All changes are skippable; carry forward the prior result.
            res = {**prior, "sha": sha, "tested_sha": tested_sha, "carried": True, "checked_at": now.isoformat()}
            Path(state_path).parent.mkdir(parents=True, exist_ok=True)
            Path(state_path).write_text(json.dumps({k: v for k, v in res.items() if k != "ran"}))
            return {**res, "ran": True}  # Return ran=True so the caller knows we processed it.

    # Acquire lock for running the suite.
    if not _acquire_lock(lock_path):
        # Could not acquire lock; return prior state.
        return {**prior, "ran": False}

    try:
        try:
            ok, failed, summary = run_suite()
            res = {"sha": sha, "tested_sha": sha, "ok": ok, "failed": failed, "summary": summary, "checked_at": now.isoformat(), "ran": True}
        except Exception:
            return {**prior, "ran": False}
        Path(state_path).parent.mkdir(parents=True, exist_ok=True)
        Path(state_path).write_text(json.dumps({k: v for k, v in res.items() if k != "ran"}))
        return res
    finally:
        _release_lock(lock_path)


if __name__ == "__main__":
    if sys.argv[1:] != ["refresh"]:
        sys.exit("usage: main_health.py refresh")
    print(json.dumps(refresh()))
