#!/usr/bin/env python3
"""mac-mini-2012 as an extra test runner for the merge gate (marvin #933): never the verdict.

When the gate retests a marvin PR, it also hands the box the exact rebased commit; the box runs the Python suite
(`-n 8`) on it and the result is recorded next to the Mac's verdict for the same commit. The gate never waits for the
box, and nothing the box says changes whether a PR merges (Gil's `trial-work` decision on G-Eskayo/marvin-instance
PR #6: "an extra runner, never the gate's verdict").

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
BOX_HOST = "mac-mini-2012"
TIMEOUT_S = 480          # 3x the box's measured 158 s at -n 8 (#623), the amendment's number
WORKERS = 8
REF_PREFIX = "refs/box-runs/"
FAILED_LINE = re.compile(r"^(?:FAILED|ERROR) (\S+::\S+|\S+\.py)")


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
        try:
            _append({"event": "box", "label": label, "outcome": "error", "error": f"submit: {exc}"[:300]})
        except Exception:
            pass
        return None


def classify(r: task_dispatch.DispatchResult) -> str:
    if r.ok:
        return "passed"
    if r.timed_out:
        return "timeout"
    if r.unreachable or r.device_id is None:
        return "offline"
    m = re.match(r"exit (\d+)", r.error or "")
    code = int(m.group(1)) if m else None
    if code == 1 and failing_tests(r.output or ""):
        return "failed"
    return "error"


def run(run_id: str, repo: str, sha: str, label: str, dispatch=task_dispatch.dispatch, head=box_head) -> dict:
    started = time.monotonic()
    entry = {"event": "box", "id": run_id, "label": label, "sha": sha}
    try:
        base = head()
        if base is None:
            entry.update(outcome="offline", error="the box could not be asked for its checkout")
            return entry
        stdin = base64.b64encode(make_bundle(repo, sha, base)).decode()
        r = dispatch(box_command(), need="test", timeout=TIMEOUT_S, fallback=False, stdin=stdin,
                     task_label=f"gate box run {label}")
        entry.update(outcome=classify(r), ran_on=r.device_id, failing=failing_tests(r.output or ""),
                     summary=((r.output or "").strip().splitlines() or [""])[-1][:200],
                     error=None if r.ok else (r.error or "")[:300])
        return entry
    except Exception as exc:
        entry.update(outcome="error", error=str(exc)[:300])
        return entry
    finally:
        entry["seconds"] = round(time.monotonic() - started, 1)
        _git(repo, "update-ref", "-d", REF_PREFIX + run_id, check=False)
        _append(entry)
        compare(sha)


def verdict(sha: str, outcome: str, output: str = "") -> None:
    _append({"event": "mac", "sha": sha, "outcome": outcome, "failing": failing_tests(output)})
    compare(sha)


def compare(sha: str) -> dict | None:
    """When both the box and the Mac have a result for `sha`, record whether they agree (once per pair)."""
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with (LOG.parent / "box-runs.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        lines = [l for l in _lines() if l.get("sha") == sha]
        box = next((l for l in reversed(lines) if l.get("event") == "box"), None)
        mac = next((l for l in reversed(lines) if l.get("event") == "mac"), None)
        if not box or not mac or any(l.get("event") == "compare" and l.get("box_t") == box["t"] and
                                     l.get("mac_t") == mac["t"] for l in lines):
            return None
        out = {"event": "compare", "sha": sha, "label": box.get("label"), "box_t": box["t"], "mac_t": mac["t"],
               "box": box.get("outcome"), "mac": mac.get("outcome")}
        if box.get("outcome") not in ("passed", "failed"):
            out["agree"] = None   # no box result to compare
        else:
            b, m = set(box.get("failing") or []), set(mac.get("failing") or [])
            out["agree"] = box["outcome"] == mac["outcome"] and b == m
            out["box_only"] = sorted(b - m)
            out["mac_only"] = sorted(m - b)
        _append(out)
        return out


def show(last: int = 20) -> str:
    rows = [l for l in _lines() if l.get("event") == "compare"][-last:]
    rows.sort(key=lambda r: (r.get("agree") is not False,))
    if not rows:
        return "no box runs compared yet"
    out = ["| commit | PR | box | Mac | agree | box only | Mac only |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        agree = {True: "yes", False: "**NO**", None: "no result"}[r.get("agree")]
        out.append(f"| {r['sha'][:8]} | {r.get('label') or ''} | {r['box']} | {r['mac']} | {agree} | "
                   f"{', '.join(r.get('box_only') or [])} | {', '.join(r.get('mac_only') or [])} |")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("submit")
    s.add_argument("--tree", required=True)
    s.add_argument("--label", default="")
    r = sub.add_parser("run")
    r.add_argument("id")
    r.add_argument("--repo", required=True)
    r.add_argument("--sha", required=True)
    r.add_argument("--label", default="")
    v = sub.add_parser("verdict")
    v.add_argument("--sha", required=True)
    v.add_argument("--outcome", required=True, choices=["passed", "failed"])
    sh = sub.add_parser("show")
    sh.add_argument("--last", type=int, default=20)
    a = ap.parse_args(argv)
    if a.cmd == "submit":
        print(json.dumps(submit(a.tree, a.label)))
    elif a.cmd == "run":
        print(json.dumps(run(a.id, a.repo, a.sha, a.label)))
    elif a.cmd == "verdict":
        verdict(a.sha, a.outcome, "" if sys.stdin.isatty() else sys.stdin.read())
    else:
        print(show(a.last))
    return 0


if __name__ == "__main__":
    sys.exit(main())
