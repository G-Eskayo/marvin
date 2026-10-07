"""The ticket scanner's queue, for the dashboard's Activity tab ("Next up", ADR 0053).

Built from ticket_pipeline's own `_unclaimed_ready_tickets` and `_order_key`, so what the strip shows is what the
scanner will dispatch, in that order. `python ticket_queue.py` prints the rows as JSON.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _priority(issue: dict):
    import ticket_policy
    rank = ticket_policy.priority_rank(issue)
    return None if rank is None else f"p{rank}"


def build_queue(repos, ready, machines) -> list[dict]:
    """Every project's ready tickets merged into one list in dispatch order. `ready(repo)` and `machines(repo)` are
    injected so the order logic is testable without GitHub; a project that cannot be read is skipped, not fatal."""
    import ticket_pipeline as tp
    pairs = []
    for repo in repos:
        try:
            tickets = ready(repo)
        except Exception as exc:  # noqa: BLE001
            print(f"[ticket-queue] {repo} unreadable: {exc}", file=sys.stderr)
            continue
        pairs.extend((repo, t) for t in tickets)
    pairs.sort(key=lambda p: tp._order_key(p[1]))
    return [{"position": i, "repo": repo, "project": repo.split("/")[-1], "number": t["number"], "title": t["title"],
             "priority": _priority(t), "score": t.get("_score", 0.0), "machines": list(machines(repo)),
             "createdAt": t["createdAt"]}
            for i, (repo, t) in enumerate(pairs, 1)]


_MACHINE_OF_CLAIM = {"mac-mini": "mac-mini-1", "macbook-pro": "macbook-pro-1"}   # the inverse of ticket_pipeline._label_for_device


def running_tickets(repos, fetch) -> list[dict]:
    """Open tickets carrying a `claimed:<machine>` label: what is being worked on now, on either machine. `fetch(repo)`
    returns that project's open issues (injected for tests); a project that cannot be read is skipped."""
    out = []
    for repo in repos:
        try:
            issues = fetch(repo)
        except Exception as exc:  # noqa: BLE001
            print(f"[ticket-queue] {repo} unreadable: {exc}", file=sys.stderr)
            continue
        for i in issues:
            claim = next((l["name"].split(":", 1)[1] for l in i.get("labels", []) if l["name"].startswith("claimed:")), None)
            if claim:
                out.append({"repo": repo, "project": repo.split("/")[-1], "number": i["number"], "title": i["title"],
                            "machine": _MACHINE_OF_CLAIM.get(claim, claim)})
    return out


def _fetch_open(repo: str) -> list[dict]:
    import subprocess
    p = subprocess.run(["gh", "issue", "list", "--repo", repo, "--state", "open", "--limit", "200", "--json", "number,title,labels"],
                       capture_output=True, text=True, timeout=30)
    if p.returncode != 0:
        raise RuntimeError(p.stderr[:200])
    return json.loads(p.stdout)


def current_queue() -> list[dict]:
    import project_profile as pp
    import ticket_pipeline as tp
    repos = [tp.REPO, *pp.dispatchable_repos()]
    return build_queue(
        repos,
        ready=lambda r: tp._unclaimed_ready_tickets(r),
        machines=lambda r: list(tp.MARVIN_MACHINES) if r == tp.REPO else pp.load_profile(r).get("machines", []))


def current() -> dict:
    """What the dashboard shows: the tickets running now and the queue behind them."""
    import project_profile as pp
    import ticket_pipeline as tp
    return {"running": running_tickets([tp.REPO, *pp.dispatchable_repos()], _fetch_open), "queue": current_queue()}


if __name__ == "__main__":
    print(json.dumps(current()))
