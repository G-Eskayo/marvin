"""Is the base branch green? Checked on a clean checkout of origin/main, recorded, and shown in Health.

On 2026-10-07 main went red because of a bad test, and nobody knew until a PR was denied for it. This keeps a record:
whenever origin/main has a new commit, run the whole Python suite on a clean checkout and write the answer to
~/.claude/logs/main-health.json (read by the Health check `main:green`). The ticket-pipeline scan starts it in the
background, so a scan never waits on it. Unlike the merge gate it runs EVERYTHING, including the tests that read other
repos' data, which the gate leaves out.

    python main_health.py refresh        check now (skips when origin/main has not moved)

Once per change that can matter, one at a time (marvin#457 "main-health runs pile up (3 full test suites at once) and
starve the merge gate: single-flight lock + skip docs/log-only commits"; pipeline review 2026-10-21, F1/F11):
- Single flight: a non-blocking flock beside the state file. A refresh that finds one running returns at once
  ("busy"); the lock dies with its process, so it can never go stale.
- Only when code moved: 191 of ~200 auto-sync commits on main change only bench/metrics/health-monitor.*, and each one
  ran the 7-minute suite. When everything that changed since the last checked commit is machine data (bench/metrics/,
  *.log, *.jsonl) or a doc no test reads (*.md, docs/; "reads" = a test file names it, by `git grep`), the last verdict
  is carried forward to the new commit instead. A merge that touches code still runs once.
- Coalesced (marvin#940): a refresh that finds one running leaves a mark (`.again` beside the state file) and returns.
  The running one, once it has recorded its answer, sees the mark and checks again on the newest main: a burst of
  merges during a run costs one more run, not one per merge. The 2026-10-30 memory fill was these runs piling up.
- In the machine's one test slot (lib/test_slot.py): it waits behind the merge gate and any other test run, merges
  first, and its pytest-xdist workers are sized to free memory, not cores.
Cost: O(changed paths) git calls per refresh; one suite run per code-changing move of main, never two at once.
"""
from __future__ import annotations

import fcntl
import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

STATE = Path.home() / ".claude" / "logs" / "main-health.json"
REPO_DIR = Path.home() / ".agents"
VENV_PY = REPO_DIR / "venv" / "bin" / "python"


def failed_ids(output: str) -> list[str]:
    return [m.group(1) for m in re.finditer(r"^FAILED\s+(\S+)", output, re.M)]


def _head() -> str | None:
    try:
        subprocess.run(["git", "fetch", "-q", "origin", "main"], cwd=REPO_DIR, capture_output=True, timeout=60, check=True)
        return subprocess.run(["git", "rev-parse", "--short", "origin/main"], cwd=REPO_DIR, capture_output=True, text=True, timeout=20, check=True).stdout.strip()
    except Exception:  # noqa: BLE001 -- offline: keep the last answer
        return None


def parallel_args(python: Path = VENV_PY, workers=None) -> list[str]:
    """`-n N` when the venv has pytest-xdist (391 s serial vs 39 s on the M4, 2026-10-21), N = the workers that fit in
    free memory now (test_slot.workers, marvin#940); otherwise serial, with a line saying why. Asked of the venv's own
    python: this script itself may run under another interpreter."""
    try:
        ok = subprocess.run([str(python), "-c", "import xdist"], capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.SubprocessError):
        ok = False
    if ok:
        if workers is None:
            import test_slot
            workers = test_slot.workers
        return ["-n", str(workers())]
    print(f"[main-health] pytest-xdist is not installed in {python}: running the suite serially (slower). "
          f"Fix: {python} -m pip install pytest-xdist", file=sys.stderr)
    return []


def _run_suite() -> tuple[bool, list[str], str]:
    import test_slot
    with test_slot.slot("main-health (after-merge full suite)"):
        return _run_suite_in_slot()


def _run_suite_in_slot() -> tuple[bool, list[str], str]:
    tmp = tempfile.mkdtemp(prefix="main-health-")
    try:
        subprocess.run(["git", "worktree", "add", "-q", "--detach", tmp, "origin/main"], cwd=REPO_DIR, check=True, capture_output=True, timeout=120)
        # Niced: a background backstop must not starve the merge gate or Gil's own work (marvin#457).
        p = subprocess.run(["nice", "-n", "10", str(VENV_PY), "-m", "pytest", "lib/tests", "-q", "-p", "no:cacheprovider",
                            *parallel_args()], cwd=tmp, capture_output=True, text=True, timeout=1800)
        last = [l for l in p.stdout.strip().splitlines() if l.strip()][-1:] or [""]
        return p.returncode == 0, failed_ids(p.stdout), last[0].strip(" =")
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", tmp], cwd=REPO_DIR, capture_output=True)


# Machine-written data: never read by a test as code. Docs are skipped only when no test names them.
_DATA = re.compile(r"^bench/metrics/|\.(?:log|jsonl)$")
_DOC = re.compile(r"^docs/|\.md$")
_TEST_DIRS = ["lib/tests", "tests", "skills", "brain-map", "conftest.py"]


def _git(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO_DIR, capture_output=True, text=True, timeout=timeout)


def _changed_paths(old: str, new: str) -> list[str] | None:
    """Paths changed between two commits, or None when that can't be worked out (then the suite runs)."""
    try:
        p = _git("diff", "--name-only", old, new)
    except (OSError, subprocess.SubprocessError):
        return None
    return [l for l in p.stdout.splitlines() if l.strip()] if p.returncode == 0 else None


def _named_by_a_test(path: str, sha: str) -> bool:
    """Does any test file at ``sha`` mention this file's name? Unknown counts as yes (run the suite)."""
    try:
        p = _git("grep", "-q", "-F", "-e", Path(path).name, sha, "--", *_TEST_DIRS)
    except (OSError, subprocess.SubprocessError):
        return True
    return p.returncode != 1  # 0 found, 1 not found, anything else an error


def needs_suite(changed: list[str] | None, named_by_a_test) -> bool:
    """True unless every changed path is machine data or a doc no test reads."""
    if changed is None:
        return True
    for path in changed:
        if _DATA.search(path):
            continue
        if _DOC.search(path) and not named_by_a_test(path):
            continue
        return True
    return False


def _write(state_path: Path, health_record: dict) -> None:
    Path(state_path).parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(state_path).with_suffix(".tmp")
    tmp.write_text(json.dumps({k: v for k, v in health_record.items() if k != "ran"}))
    tmp.replace(state_path)  # Health never reads a half-written answer


def refresh(state_path: Path = STATE, head=_head, run_suite=_run_suite, now: datetime | None = None,
            changed=_changed_paths, named_by_a_test=_named_by_a_test) -> dict:
    Path(state_path).parent.mkdir(parents=True, exist_ok=True)
    again = Path(state_path).with_suffix(".again")
    with open(Path(state_path).with_suffix(".lock"), "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            again.touch()   # the running one checks the newest main once more when it ends
            return {"ran": False, "busy": True}
        while True:
            again.unlink(missing_ok=True)
            res = _refresh_once(state_path, head, run_suite, now or datetime.now(timezone.utc), changed, named_by_a_test)
            if not again.exists():
                return res


def _refresh_once(state_path, head, run_suite, now, changed, named_by_a_test) -> dict:
    prior = {}
    try:
        prior = json.loads(Path(state_path).read_text())
    except (OSError, ValueError):
        pass
    sha = head()
    if sha is None or sha == prior.get("sha"):
        return {**prior, "ran": False}
    if prior.get("sha") and "ok" in prior and not needs_suite(changed(prior["sha"], sha), lambda p: named_by_a_test(p, sha)):
        res = {**{k: v for k, v in prior.items() if k in ("ok", "failed", "summary")}, "sha": sha,
               "tested_sha": prior.get("tested_sha", prior["sha"]), "checked_at": now.isoformat(),
               "carried": f"only docs or machine data changed since {prior['sha']}", "ran": False}
        _write(state_path, res)
        return res
    ok, failed, summary = run_suite()
    res = {"sha": sha, "ok": ok, "failed": failed, "summary": summary, "checked_at": now.isoformat(), "ran": True}
    _write(state_path, res)
    return res

if __name__ == "__main__":
    if sys.argv[1:] != ["refresh"]:
        sys.exit("usage: main_health.py refresh")
    print(json.dumps(refresh()))
