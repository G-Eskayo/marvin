"""Does work for a ticket already exist? Deterministic, checked BEFORE the pipeline claims it.

Labels are what people and agents *said*; git is what happened. A ticket can sit `ready-for-agent`
long after a commit, an open PR, a pipeline branch or a rescue ref exists for it. Dispatching it
anyway burns a model run to rediscover (or duplicate) that work. `evidence_for` is pure over facts
gathered once per repo by `gather`; `verdict` folds the evidence into one of:

  in-flight   an open PR, pipeline branch or rescue ref exists  -> never dispatch; a human reviews it
  looks-done  commits on the base branch mention the ticket     -> never dispatch; a human closes it
  clear       nothing found                                     -> safe to dispatch

The same evidence feeds the Activity boards (dashboard/electron/main/board.js) so cards show it.
"""
from __future__ import annotations

import json
import re
import subprocess

TIMEOUT = 60


def _mentions(text: str, n: int) -> bool:
    return bool(re.search(rf"#{n}(?!\d)", text or ""))


def _named(ref: str, n: int) -> bool:
    return bool(re.search(rf"[/-]{n}(?![\d])", ref))


def evidence_for(n: int, facts: dict) -> list[dict]:
    ev: list[dict] = []
    for pr in facts.get("prs", []):
        if _mentions(pr.get("body"), n) or _named(pr.get("headRefName", ""), n):
            ev.append({"kind": "open-pr", "ref": f"PR #{pr['number']}", "detail": "open pull request"})
    for b in facts.get("branches", []):
        if _named(b, n):
            ev.append({"kind": "branch", "ref": b, "detail": "pipeline branch exists"})
    for r in facts.get("rescue", []):
        if _named(r.rsplit("/", 1)[0], n):
            ev.append({"kind": "rescue-ref", "ref": r, "detail": "a prior run's work was preserved"})
    for sha, subject in facts.get("commits", []):
        if _mentions(subject, n) and not re.search(r"\brevert", subject, re.I):
            ev.append({"kind": "commit", "ref": sha, "detail": subject})
    return ev


def verdict(evidence: list[dict]) -> str:
    kinds = {e["kind"] for e in evidence}
    if kinds & {"open-pr", "branch", "rescue-ref"}:
        return "in-flight"
    return "looks-done" if "commit" in kinds else "clear"


def _sh(args, cwd=None) -> str:
    p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT)
    return p.stdout if p.returncode == 0 else ""


def gather(repo: str, clone: str | None, base: str = "origin/main") -> dict | None:
    """Facts for one repo, or None when they can't be read (callers then fall back to dispatching
    as before rather than stalling the whole pipeline on a gh/git hiccup)."""
    prs_raw = _sh(["gh", "pr", "list", "-R", repo, "--state", "open", "--limit", "200",
                   "--json", "number,body,headRefName"])
    if not prs_raw:
        return None
    facts: dict = {"prs": json.loads(prs_raw), "branches": [], "rescue": [], "commits": []}
    if clone:
        subprocess.run(["git", "fetch", "-q", "origin"], cwd=clone, capture_output=True, timeout=TIMEOUT)
        facts["branches"] = [b.strip() for b in _sh(["git", "branch", "-r", "--list", "origin/pipeline/*"], clone).splitlines()]
        facts["rescue"] = [l.split("\t")[1] for l in _sh(["git", "ls-remote", "origin", "refs/rescue/*"], clone).splitlines() if "\t" in l]
        facts["commits"] = [tuple(l.split(" ", 1)) for l in _sh(["git", "log", base, "--format=%h %s", "-n", "2000"], clone).splitlines() if " " in l]
    return facts


def report(numbers, facts: dict) -> dict:
    """{"<n>": {"verdict", "evidence"}} for the tickets that have any; what the dashboard reads."""
    out = {}
    for n in numbers:
        ev = evidence_for(n, facts)
        if ev:
            out[str(n)] = {"verdict": verdict(ev), "evidence": ev[:4]}
    return out


if __name__ == "__main__":  # python3 ticket_evidence.py report <owner/repo>  -> JSON on stdout
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import ticket_pipeline as tp
    if len(sys.argv) != 3 or sys.argv[1] != "report":
        sys.exit("usage: ticket_evidence.py report <owner/repo>")
    repo = sys.argv[2]
    facts = tp._evidence_facts(repo)
    nums = [i["number"] for i in json.loads(_sh(["gh", "issue", "list", "--repo", repo, "--state", "open",
                                                  "--limit", "1000", "--json", "number"]) or "[]")]
    print(json.dumps(report(nums, facts) if facts else {}))
