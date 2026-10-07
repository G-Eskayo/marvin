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


def current_queue() -> list[dict]:
    import project_profile as pp
    import ticket_pipeline as tp
    repos = [tp.REPO, *pp.dispatchable_repos()]
    return build_queue(
        repos,
        ready=lambda r: tp._unclaimed_ready_tickets(r),
        machines=lambda r: list(tp.MARVIN_MACHINES) if r == tp.REPO else pp.load_profile(r).get("machines", []))


if __name__ == "__main__":
    print(json.dumps(current_queue()))
