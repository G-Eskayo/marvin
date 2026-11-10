#!/usr/bin/env python3
"""mac-mini-2012 as an extra test runner for the merge gate (marvin #933): never the verdict.

When the gate retests a marvin PR, it also hands the box the exact rebased commit; the box runs the Python suite
(`-n 8`) on it and the result is recorded next to the Mac's verdict for the same commit. The gate never waits for the
box, and nothing the box says changes whether a PR merges (the owner's `trial-work` decision on the instance's
calibration PR #6, marvin #623: "an extra runner, never the gate's verdict").

    submit --tree DIR --label L   (the gate, ~20 ms) pin HEAD with a ref, start `run` detached, return at once
    run ID --repo R --sha S       (detached) bundle the commits the box lacks, run the suite there, record the outcome
    verdict --sha S --outcome passed|failed   (the gate) the Mac's verdict; failing test names on stdin
    show [--last N]               box vs Mac per commit, disagreements first

How the commit gets there: the rebased commit exists only on this Mac until the gate pushes it, and the box is pull-only
(ADR 0069). So this Mac makes a git bundle of the commits after the box's own checkout (tens of KB) and sends it on the
run's stdin; the box clones its checkout `--shared` into /tmp, fetches the bundle, runs, and deletes it all. Nothing
is pushed anywhere and the box's checkout is not changed.

Outcomes: passed, failed (with the failing tests), timeout (480 s, killed on the box), offline (unreachable or busy),
error (the hand-off itself failed). Only passed/failed are compared with the Mac; the rest are "no result".
Every line goes to ~/.claude/logs/box-runs.jsonl. MARVIN_BOX_RUNNER=off turns it off.
"""
from __future__ import annotations

import argparse
import base64
import fcntl
import json
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import task_dispatch  # noqa: E402

LOG = Path.home() / ".claude" / "logs" / "box-runs.jsonl"
LOG_LOCK = Path.home() / ".claude" / "logs" / "box-runs.lock"
BOX_HOST = "mac-mini-2012"
TIMEOUT_S = 480          # 3x the box's measured 158 s at -n 8 (#623), the amendment's number
WORKERS = 8
REF_PREFIX = "refs/box-runs/"
FAILED_LINE = re.compile(r"^(?:FAILED|ERROR) (\S+::\S+|\S+\.py)")
PROPOSALS_ROOT = Path.home() / ".claude" / "proposals"
TRUST_STREAK = 20


def _git(repo: str | Path, *args: str, binary: bool = False, check: bool = True):
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=not binary, timeout=60)
    if check and p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {(p.stderr if not binary else p.stderr.decode(errors='replace'))[:300]}")
    return p.stdout if binary else p.stdout.strip()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append(entry: dict) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.write(json.dumps({"t": _now(), **entry}) + "\n")


def _lines() -> list[dict]:
    if not LOG.exists():
        return []
    out = []
    for line in LOG.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def failing_tests(output: str) -> list[str]:
    """Test ids from pytest's short summary (`FAILED path::name - msg`, `ERROR path::name`), sorted and unique."""
    names = {m.group(1) for line in (output or "").splitlines() if (m := FAILED_LINE.match(line.strip()))}
    return sorted(names)


def box_command(workers: int = WORKERS) -> str:
    """What runs on the box: the bundle arrives base64 on stdin. Exit 3 means the hand-off failed (not the tests)."""
    return (
        '( d="$(mktemp -d /tmp/box-run-XXXXXX)"; trap \'rm -rf "$d"\' EXIT; '
        'base64 -d > "$d/run.bundle" && '
        'git clone -q --shared --no-checkout "$HOME/.agents" "$d/repo" && '
        'git -C "$d/repo" fetch -q "$d/run.bundle" "+refs/box-runs/*:refs/box-runs/*" && '
        'git -C "$d/repo" checkout -q --detach "$(git -C "$d/repo" bundle list-heads "$d/run.bundle" | '
        'awk \'NR==1{print $1}\')" || exit 3; '
        'cd "$d/repo" && echo "commit $(git rev-parse HEAD)"; '
        f'MARVIN_MERGE_GATE=1 "$HOME/.agents/venv/bin/python" -m pytest -q -n {int(workers)} -p no:cacheprovider '
        '2>&1 | tail -n 80; exit ${PIPESTATUS[0]} )'
    )


def box_head() -> str | None:
    """The commit the box's own checkout is at (the bundle's base), or None if the box can't be asked."""
    try:
        p = subprocess.run(["ssh", *task_dispatch.SSH_OPTS, BOX_HOST, "git -C ~/.agents rev-parse HEAD"],
                           capture_output=True, text=True, timeout=15)
    except Exception:
        return None
    head = p.stdout.strip()
    return head if p.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", head) else None


def _is_commit(repo: str, rev: str) -> bool:
    return subprocess.run(["git", "-C", repo, "cat-file", "-e", f"{rev}^{{commit}}"], capture_output=True,
                          timeout=30).returncode == 0


def make_bundle(repo: str, sha: str, base: str | None) -> bytes:
    """Commits from the box's checkout `base` (exclusive) to `sha`, under one ref in refs/box-runs/. The merge-base
    is the prerequisite, so a box checkout ahead of or beside this commit still works. With `base` unknown here, or
    no common commit, this raises rather than ship the whole repo (~90 MB)."""
    if not base or not _is_commit(repo, base):
        raise RuntimeError("the box's checkout commit is not known on this Mac (fetch origin main first)")
    mb = _git(repo, "merge-base", sha, base, check=False)
    if not mb:
        raise RuntimeError("the box's checkout shares no history with this commit")
    if mb == sha:   # the box already has this commit; a bundle can't be empty, so include the commit itself
        mb = _git(repo, "rev-parse", "--verify", "-q", f"{sha}^", check=False)   # "" for a root commit
    ref = f"{REF_PREFIX}bundle-{uuid.uuid4().hex[:8]}"
    _git(repo, "update-ref", ref, sha)
    try:
        return _git(repo, "bundle", "create", "-", ref, *([f"^{mb}"] if mb else []), binary=True)
    finally:
        _git(repo, "update-ref", "-d", ref, check=False)


def submit(tree: str, label: str, spawn=subprocess.Popen) -> dict | None:
    """Called by the gate as its tests start. Must be quick and must never raise into the gate."""
    if os.environ.get("MARVIN_BOX_RUNNER", "on").lower() in ("off", "0", "no"):
        return None
    try:
        sha = _git(tree, "rev-parse", "HEAD")
        common = _git(tree, "rev-parse", "--path-format=absolute", "--git-common-dir")
        repo = str(Path(common).parent) if Path(common).name == ".git" else common
        run_id = uuid.uuid4().hex[:10]
        _git(tree, "update-ref", REF_PREFIX + run_id, sha)   # the scratch clone goes away; the commit must not
        _append({"event": "sent", "id": run_id, "label": label, "sha": sha})
        spawn([sys.executable, str(Path(__file__).resolve()), "run", run_id, "--repo", repo, "--sha", sha,
               "--label", label], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
              start_new_session=True)
        return {"id": run_id, "sha": sha}
    except Exception as exc:
        return None


def run(run_id: str, repo: str, sha: str, label: str) -> None:
    """Detached background process: bundle the commits the gate can't reach, ssh to the box, send them, record the
    outcome. Error strings are truncated to fit the log line."""
    def log_outcome(event: str, **kw):
        _append({"event": event, "id": run_id, "sha": sha, **kw})
    try:
        head = box_head()
        if not head:
            return log_outcome("offline")
        try:
            bundle = make_bundle(repo, sha, head)
        except RuntimeError as e:
            return log_outcome("error", msg=str(e)[:200])
        try:
            p = subprocess.run(
                ["ssh", *task_dispatch.SSH_OPTS, BOX_HOST, box_command()],
                input=base64.b64encode(bundle), capture_output=True, timeout=TIMEOUT_S + 30, text=False)
        except subprocess.TimeoutExpired:
            return log_outcome("timeout")
        except Exception as e:
            return log_outcome("error", msg=str(e)[:200])
        output = p.stdout.decode(errors="replace")
        if p.returncode == 0:
            outcome = "passed"
        elif p.returncode == 3:
            outcome = "error"
            return log_outcome(outcome, msg="hand-off failed (not tests)")
        elif p.returncode < 128:
            outcome = "failed"
        else:
            outcome = "error"
        tests = failing_tests(output) if outcome == "failed" else []
        log_outcome(outcome, tests=tests, label=label)
    except Exception:
        pass


def verdict(sha: str, outcome: str, repo: str = ".") -> None:
    """Called by the gate after its own suite finishes. Failing test names come from stdin."""
    tests = [line.strip() for line in sys.stdin if line.strip()]
    _append({"event": "verdict", "sha": sha, "outcome": outcome, "tests": tests, "repo": repo})


def agreement_streak(rows: list[dict] | None = None) -> int:
    """Count consecutive True agree values from the end, skipping None, stopping at False."""
    if rows is None:
        rows = _lines()
    streak = 0
    for row in reversed(rows):
        if row.get("event") != "compare":
            continue
        agree = row.get("agree")
        if agree is None:
            continue  # skip None without ending the streak
        if agree is False:
            break  # stop at first False
        streak += 1
    return streak


def _maybe_propose_trust() -> None:
    """Check if a trust proposal already exists; if not and streak ≥ TRUST_STREAK, propose once."""
    rows = _lines()
    # Don't retry if we've already tried (success or error marker)
    if any(r.get("event") == "trust-proposed" for r in rows):
        return
    if agreement_streak(rows) < TRUST_STREAK:
        return
    try:
        import proposals  # noqa: E402
        title = "Gate box runner: propose as a second required runner after 20 consecutive agreements"
        problem = "The mac-mini-2012 box has been a non-blocking extra runner for 20+ consecutive gate runs with full agreement with the Mac's verdicts. Time to judge whether to make it a required runner."
        fix = "Create a proposal to make mac-mini-2012 a required runner (owner decision)."
        why = "Removes manual counting and asking; the owner stays in control of the judgment via the Proposal."
        area = "gate"
        size = "Small"
        source = "box_runner.agreement_streak()"
        proposals.add(PROPOSALS_ROOT, {
            "title": title,
            "problem": problem,
            "fix": fix,
            "why": why,
            "north_star": 2,
            "area": area,
            "size": size,
            "source": source,
        })
        _append({"event": "trust-proposed", "ok": True, "sha": "HEAD"})
    except Exception as e:
        _append({"event": "trust-proposed", "error": str(e)[:200]})


def compare(sha: str, repo: str = ".") -> dict | None:
    """Compare box and Mac outcomes for the same commit. Returns None if the commit hasn't been compared yet."""
    # Check before acquiring lock (fast path for already-compared commits)
    rows = _lines()
    compares = [r for r in rows if r.get("event") == "compare"]
    if any(r.get("sha") == sha for r in compares):
        return None

    # Acquire exclusive lock for the critical section: read-check-append-maybe_propose
    LOG_LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOG_LOCK.open("a") as lock_fh:
        fcntl.flock(lock_fh, fcntl.LOCK_EX)
        try:
            # Re-read and re-check under lock to catch concurrent updates
            rows = _lines()
            compares = [r for r in rows if r.get("event") == "compare"]
            if any(r.get("sha") == sha for r in compares):
                return None

            box_row = next((r for r in reversed(rows) if r.get("event") == "failed" and r.get("sha") == sha), None)
            box_row = box_row or next((r for r in reversed(rows) if r.get("event") == "passed" and r.get("sha") == sha), None)
            box_row = box_row or next((r for r in reversed(rows) if r.get("event") in ("timeout", "offline", "error") and r.get("sha") == sha), None)
            verdict_row = next((r for r in reversed(rows) if r.get("event") == "verdict" and r.get("sha") == sha), None)
            if not box_row or not verdict_row:
                return None
            if box_row.get("event") in ("timeout", "offline", "error"):
                agree = None
            else:
                agree = (box_row.get("event") == "passed") == (verdict_row.get("outcome") == "passed")
            out = {"event": "compare", "sha": sha, "box": box_row.get("event"), "mac": verdict_row.get("outcome"), "agree": agree}
            _append(out)
            _maybe_propose_trust()
            return out
        finally:
            fcntl.flock(lock_fh, fcntl.LOCK_UN)


def show(last: int | None = None) -> None:
    """Print box vs Mac per commit, disagreements first."""
    rows = _lines()
    compares = [r for r in rows if r.get("event") == "compare"]
    if last:
        compares = compares[-last:]
    disagree = [r for r in compares if r.get("agree") is False]
    agree = [r for r in compares if r.get("agree") is True]
    for r in disagree + agree:
        print(f"{r.get('sha', '')[:8]}  box={r.get('box', '?'):8}  mac={r.get('mac', '?'):8}  {'✓' if r.get('agree') else '✗'}")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    subparsers = p.add_subparsers(dest="command", help="command")

    submit_p = subparsers.add_parser("submit")
    submit_p.add_argument("--tree", required=True)
    submit_p.add_argument("--label", required=True)

    run_p = subparsers.add_parser("run")
    run_p.add_argument("run_id")
    run_p.add_argument("--repo", required=True)
    run_p.add_argument("--sha", required=True)
    run_p.add_argument("--label", required=True)

    verdict_p = subparsers.add_parser("verdict")
    verdict_p.add_argument("--sha", required=True)
    verdict_p.add_argument("--outcome", required=True, choices=["passed", "failed"])
    verdict_p.add_argument("--repo", default=".")

    compare_p = subparsers.add_parser("compare")
    compare_p.add_argument("--sha", required=True)
    compare_p.add_argument("--repo", default=".")

    show_p = subparsers.add_parser("show")
    show_p.add_argument("--last", type=int)

    args = p.parse_args()
    if args.command == "submit":
        result = submit(args.tree, args.label)
        if result:
            print(json.dumps(result))
    elif args.command == "run":
        run(args.run_id, args.repo, args.sha, args.label)
    elif args.command == "verdict":
        verdict(args.sha, args.outcome, args.repo)
    elif args.command == "compare":
        result = compare(args.sha, args.repo)
        if result:
            print(json.dumps(result))
    elif args.command == "show":
        show(args.last)


if __name__ == "__main__":
    main()
