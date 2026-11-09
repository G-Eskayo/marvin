#!/usr/bin/env python3
"""main_red.py — when a merge turns main red, open the fix-forward ticket at once (marvin#826 step 4).

Every merge to main runs the full suite in CI (no $MARVIN_BASE there: lib/affected_tests.py runs everything). CI's
`main-red` job then calls this with each check's result. The owner's rule (#826): "when main is red, the tickets
that make it green are always top priority", and the merge gate keeps refusing PRs while main is red (MAIN_RED).

  red      (any check failed) open one ticket labelled priority:p0, ready-for-agent, bug and main-red, naming what
           failed, the commit and the run; a later red push adds a comment to that ticket instead of opening another.
           lib/ticket_pipeline.py dispatches a main-red ticket before every other ticket, p0s included.
  green    (every check passed) close the open main-red ticket, saying at which commit.
  unknown  (a check was cancelled, e.g. by a newer push, or skipped, or nothing ran) do nothing: it says nothing about main.

Uses the `gh` on PATH with $GH_TOKEN (CI's token, issues: write). Labels it needs are made if missing, never
rewritten. O(1) GitHub calls per push: one list, then one create, comment or close.

    main_red.py report --sha <sha> --run <url> --results '<json>'
      results: {"<check or job>": "success|failure|cancelled|skipped"} or CI's toJSON(needs)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

LABEL = "main-red"
LABELS = ["priority:p0", "ready-for-agent", "bug", LABEL]
_RED = {"failure", "timed_out"}


def _gh(args: list[str]) -> str:
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=True, timeout=60).stdout


def title(sha: str) -> str:
    return f"Main is red at {sha[:7]}: fix forward"


def ticket_body(failed: list[str], sha: str, run_url: str) -> str:
    names = ", ".join(failed)
    return f"""Main went red after a merge: **{names}** failed on `{sha[:7]}` ([the run]({run_url})). Opened by CI's
`main-red` job (lib/main_red.py, #826). While main is red the merge gate refuses every PR (MAIN_RED), so this
ticket goes before all other work.

## What to build
Make main green again by fixing forward:
1. Open the run above and read which tests failed and why.
2. Find the merge that broke them (`git log` on main since the last green run).
3. Fix the cause, test-first. Revert the breaking merge only if a fix is not small; say which in the PR.

## Acceptance criteria
- [ ] The full suite passes on main in CI after this ticket's PR merges (this ticket then closes itself)
- [ ] The failing tests named in the run pass, and none were skipped or deleted to get there

## How we'll try to break it
- Run the failing tests again on a clean checkout of main, not only in the worktree that fixed them.
- Check that the fix doesn't just hide the failure (a skip, a widened tolerance, a deleted assertion).
"""


def _verdict(results: dict) -> tuple[str, list[str]]:
    states = {k: (v.get("result") if isinstance(v, dict) else v) for k, v in results.items()}
    failed = sorted(k for k, v in states.items() if v in _RED)
    if failed:
        return "red", failed
    if states and all(v == "success" for v in states.values()):
        return "green", []
    return "unknown", []


def _ensure_label(gh, repo: str, name: str, color: str, description: str) -> None:
    try:
        gh(["label", "create", name, "--repo", repo, "--color", color, "--description", description])
    except subprocess.CalledProcessError:
        pass  # it exists already: leave it as its owner set it


@dataclass(frozen=True)
class Kind:
    """One thing on main that opens a ticket when it fails and closes it when it passes again. MAIN is the fix-forward
    ticket (#826). lib/site_deploy.py adds the site's publish (#1122), which must never hold a merge, so its labels
    carry no main-red and no p0 (the gate's isRedTicket reads those)."""
    label: str
    labels: list[str]
    label_help: str
    title: Callable[[str], str]
    body: Callable[[list[str], str, str], str]
    closed: Callable[[str, str], str]
    still: Callable[[str, list[str], str], str]
    once_per_commit: bool = False   # a re-run of the same commit adds nothing to the open ticket
    extra: dict = field(default_factory=dict)


MAIN = Kind(
    label=LABEL, labels=LABELS, label_help="Main is red: fix forward before anything else (#826)", title=title,
    body=ticket_body,
    closed=lambda sha, run: f"Main is green again at `{sha[:7]}` ([the run]({run})): every required check passed. Closing.",
    still=lambda sha, failed, run: f"Still red at `{sha[:7]}`: {', '.join(failed)} failed ([the run]({run})).")


def _mentions(gh, repo: str, number: int, sha: str) -> bool:
    """Does the open ticket already name this commit (its body or any comment)?"""
    try:
        d = json.loads(gh(["issue", "view", str(number), "--repo", repo, "--json", "body,comments"]) or "{}")
    except (subprocess.CalledProcessError, ValueError):
        return False
    texts = [d.get("body") or ""] + [(c or {}).get("body") or "" for c in d.get("comments") or []]
    return any(f"`{sha[:7]}`" in t for t in texts)


def report(results: dict, sha: str, run_url: str, repo: str, gh=_gh, kind: Kind = MAIN) -> dict:
    state, failed = _verdict(results)
    if state == "unknown":
        return {"state": state, "ticket": None, "action": "none"}
    found = json.loads(gh(["issue", "list", "--repo", repo, "--state", "open", "--label", kind.label,
                           "--json", "number,title", "--limit", "5"]) or "[]")
    current = min((t["number"] for t in found), default=None)
    if state == "green":
        if current is None:
            return {"state": state, "ticket": None, "action": "none"}
        gh(["issue", "close", str(current), "--repo", repo, "--comment", kind.closed(sha, run_url)])
        return {"state": state, "ticket": current, "action": "closed"}
    if current is not None:
        if kind.once_per_commit and _mentions(gh, repo, current, sha):
            return {"state": state, "ticket": current, "action": "already"}
        gh(["issue", "comment", str(current), "--repo", repo, "--body", kind.still(sha, failed, run_url)])
        return {"state": state, "ticket": current, "action": "attached"}
    project = f"project:{repo.split('/')[-1]}"
    _ensure_label(gh, repo, kind.label, "b60205", kind.label_help)
    _ensure_label(gh, repo, project, "c5def5", f"Work on {repo.split('/')[-1]}")
    args = ["issue", "create", "--repo", repo, "--title", kind.title(sha), "--body", kind.body(failed, sha, run_url)]
    for label in [*kind.labels, project]:
        args += ["--label", label]
    url = gh(args).strip()
    return {"state": state, "ticket": int(url.rstrip("/").split("/")[-1]), "action": "opened"}


def _job_names(results: dict) -> dict:
    """CI hands over job ids (python-tests); the ticket names checks as people see them (Python tests)."""
    try:
        import yaml
        jobs = yaml.safe_load((Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml").read_text())["jobs"]
    except Exception:  # noqa: BLE001 -- the ids are still a fine name
        return results
    return {(jobs.get(k) or {}).get("name", k): v for k, v in results.items()}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="main_red.py")
    ap.add_argument("cmd", choices=["report"])
    ap.add_argument("--sha", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--results", required=True)
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    a = ap.parse_args(argv)
    try:
        results = json.loads(a.results)
    except ValueError as e:
        sys.exit(f"main_red: --results is not JSON ({e})")
    if not isinstance(results, dict) or not a.repo:
        sys.exit("main_red: --results must be an object, and --repo (or $GITHUB_REPOSITORY) is needed")
    print(json.dumps(report(_job_names(results), a.sha, a.run, a.repo, gh=_gh)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
