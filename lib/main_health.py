"""Is the base branch green? Checked on a clean checkout of origin/main, recorded, and shown in Health.

On 2026-10-07 main went red because of a bad test, and nobody knew until a PR was denied for it. This keeps a record:
whenever origin/main has a new commit, run the whole Python suite on a clean checkout and write the answer to
~/.claude/logs/main-health.json (read by the Health check `main:green`). The ticket-pipeline scan starts it in the
background, so a scan never waits on it. Unlike the merge gate it runs EVERYTHING, including the tests that read other
repos' data, which the gate leaves out.

    python main_health.py refresh        check now (skips when origin/main has not moved)
"""
from __future__ import annotations

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


def _run_suite() -> tuple[bool, list[str], str]:
    tmp = tempfile.mkdtemp(prefix="main-health-")
    try:
        subprocess.run(["git", "worktree", "add", "-q", "--detach", tmp, "origin/main"], cwd=REPO_DIR, check=True, capture_output=True, timeout=120)
        p = subprocess.run([str(VENV_PY), "-m", "pytest", "lib/tests", "-q", "-p", "no:cacheprovider"], cwd=tmp,
                           capture_output=True, text=True, timeout=1800)
        last = [l for l in p.stdout.strip().splitlines() if l.strip()][-1:] or [""]
        return p.returncode == 0, failed_ids(p.stdout), last[0].strip(" =")
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", tmp], cwd=REPO_DIR, capture_output=True)


def refresh(state_path: Path = STATE, head=_head, run_suite=_run_suite, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    prior = {}
    try:
        prior = json.loads(Path(state_path).read_text())
    except (OSError, ValueError):
        pass
    sha = head()
    if sha is None or sha == prior.get("sha"):
        return {**prior, "ran": False}
    ok, failed, summary = run_suite()
    res = {"sha": sha, "ok": ok, "failed": failed, "summary": summary, "checked_at": now.isoformat(), "ran": True}
    Path(state_path).parent.mkdir(parents=True, exist_ok=True)
    Path(state_path).write_text(json.dumps({k: v for k, v in res.items() if k != "ran"}))
    return res


if __name__ == "__main__":
    if sys.argv[1:] != ["refresh"]:
        sys.exit("usage: main_health.py refresh")
    print(json.dumps(refresh()))
