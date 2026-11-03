#!/usr/bin/env python3
"""main_ci.py: is main green? GitHub CI's answer for main's current head commit, the only judge (marvin#1094).

The owner, 2026-11-03: "GitHub's CI is the only judge of whether main is green." Before this the Mini's local full suite
(lib/main_health.py) was a second judge, and the two disagreed: 13 main-red fixes and 4 gate/queue tweaks in four days
were tests that failed on one Mac only (live claims, pgrep, another repo's working copy) while CI on main was green.
CI runs the full suite on every push to main (.github/workflows/ci.yml: no MARVIN_BASE on a push), so it is already
the verdict; this module reads it.

    verdict(sha, landed_at, check_runs, now, required) -> {sha, state, failing, pending, reason, deadline_at, runs}
      state  green    every required check (.github/required-checks.json names) passed on THIS commit
             red      a required check failed or timed out on this commit
             pending  CI is still checking this commit (or has not started yet); the merge queue waits
             late     CI has not reported by the deadline (DEADLINE_MIN after the commit landed): the queue allows one
                      local run (main_health.py refresh) as the fallback, and its reason says so
             unknown  GitHub could not be read (read() only); never green
      Only runs whose head_sha is this commit count: a result for an older commit never judges the head. A re-run
      beside the old run: the newer wins. Cancelled (a newer push) says nothing, like a run not started.
    read(repo, sha=None) -> the verdict for main's head (or that sha): two GitHub calls.

    main_ci.py verdict [--repo R] [--base main] [--sha S]    print the verdict as JSON (the merge queue calls this)

Cost: O(check runs on one commit); two REST calls per read, no polling (callers read on a trigger).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# CI's full run on main takes 20-27 min (2026-11-03, the last 8 pushes); Python tests' own job limit is 60 min. Past
# this many minutes after the commit landed with no verdict, CI is treated as silent and one local run stands in.
DEADLINE_MIN = 45
_PASSED = {"success", "skipped", "neutral"}
_RED = {"failure", "timed_out", "action_required", "startup_failure"}
_REQUIRED_FILE = Path(__file__).resolve().parents[1] / ".github" / "required-checks.json"


def required_names(path: Path = _REQUIRED_FILE) -> list[str]:
    """The check names branch protection requires (marvin#826), as CI names its jobs."""
    try:
        return [c["name"] for c in json.loads(Path(path).read_text())["checks"] if c.get("name")]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def _when(s) -> datetime | None:
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _latest(runs: list[dict], sha: str) -> dict[str, dict]:
    """Per check name, the newest run on this commit (a run not started yet is newer than any started one)."""
    out: dict[str, dict] = {}
    far = datetime.max.replace(tzinfo=timezone.utc)
    for r in runs or []:
        if not isinstance(r, dict) or str(r.get("head_sha", "")).lower() != sha.lower() or not r.get("name"):
            continue
        cur = out.get(r["name"])
        if cur is None or (_when(r.get("started_at")) or far) >= (_when(cur.get("started_at")) or far):
            out[r["name"]] = r
    return out


def verdict(sha: str, landed_at: datetime | None, check_runs: list[dict], now: datetime | None = None,
            required: list[str] | None = None, deadline_min: int = DEADLINE_MIN) -> dict:
    now = now or datetime.now(timezone.utc)
    required = required_names() if required is None else required
    latest = _latest(check_runs, sha)
    failing, pending = [], []
    for name in required:
        r = latest.get(name)
        if r is None or r.get("status") != "completed" or r.get("conclusion") == "cancelled":
            pending.append(name)
        elif r.get("conclusion") in _RED:
            failing.append(name)
        elif r.get("conclusion") not in _PASSED:
            pending.append(name)
    deadline = (landed_at or now) + timedelta(minutes=deadline_min)
    short = sha[:7]
    if failing:
        state, reason = "red", f"GitHub's CI failed on main @ {short}: {', '.join(failing)}"
    elif not pending and required:
        state, reason = "green", f"GitHub's CI passed on main @ {short}"
    elif now >= deadline:
        waited = int((now - (landed_at or now)).total_seconds() // 60)
        state, reason = "late", (f"CI hasn't reported on main @ {short} in {waited} min, so main is being checked "
                                 f"on this Mac once instead")
    else:
        state, reason = "pending", f"CI is still checking main @ {short} ({', '.join(pending)})"
    return {"sha": sha, "state": state, "failing": failing, "pending": pending, "reason": reason,
            "deadline_at": deadline.isoformat(),
            "runs": [{"name": n, "status": r.get("status"), "conclusion": r.get("conclusion")} for n, r in sorted(latest.items())]}


def _gh(args: list[str]) -> str:
    import gh_env
    return gh_env.run(["gh", *args]).stdout


def read(repo: str, base: str = "main", sha: str | None = None, gh=_gh, now: datetime | None = None,
         required: list[str] | None = None) -> dict:
    try:
        commit = json.loads(gh(["api", f"repos/{repo}/commits/{sha or base}"]) or "{}")
        head = commit.get("sha") or sha
        landed = _when(((commit.get("commit") or {}).get("committer") or {}).get("date"))
        runs = json.loads(gh(["api", f"repos/{repo}/commits/{head}/check-runs?per_page=100"]) or "{}").get("check_runs", [])
    except Exception as e:  # noqa: BLE001 -- unreadable is "unknown", never a guess of green
        return {"sha": sha, "state": "unknown", "failing": [], "pending": [], "runs": [], "deadline_at": None,
                "reason": f"GitHub's CI result for main could not be read: {str(e)[:160]}"}
    return verdict(head, landed, runs, now=now, required=required)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="main_ci.py")
    ap.add_argument("cmd", choices=["verdict"])
    ap.add_argument("--repo", default=None)
    ap.add_argument("--base", default="main")
    ap.add_argument("--sha", default=None)
    a = ap.parse_args(argv)
    if not a.repo:
        import instance
        a.repo = instance.engine_repo()
    print(json.dumps(read(a.repo, a.base, a.sha, gh=_gh)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
