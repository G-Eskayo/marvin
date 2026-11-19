"""The ticket scanner's queue, for the dashboard's Activity tab ("Next up", ADR 0053).

Built from ticket_pipeline's own `_unclaimed_ready_tickets` and `_order_key`, so what the strip shows is what the
scanner will dispatch, in that order. Each ticket appears once (deduplicated by (repo, number)). `python ticket_queue.py` prints the rows as JSON.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


GITHUB_FEED_PATH = Path.home() / ".claude" / "logs" / "github-feed.json"
GITHUB_FEED_STALE_MS = 10 * 60_000  # 10 min; same as github_feed.js STALE_MS


def _read_issues_from_feed(repo: str) -> list[dict] | None:
    """Read issues from the Mini's github-feed.json if fresh, None if missing or stale."""
    if not GITHUB_FEED_PATH.exists():
        return None
    try:
        with open(GITHUB_FEED_PATH) as f:
            feed = json.load(f)
        repo_data = feed.get("repos", {}).get(repo, {})
        issues_entry = repo_data.get("issues", {})
        if not issues_entry.get("value"):
            return None
        # Check if the feed is fresh: compare both the read time and alive_at.
        at = issues_entry.get("at")
        alive_at = feed.get("alive_at")
        now_ms = time.time() * 1000
        # Feed is stale if either the repo's data or the Mini's last check is too old.
        if at and now_ms - at > GITHUB_FEED_STALE_MS:
            return None
        if alive_at and now_ms - alive_at > GITHUB_FEED_STALE_MS:
            return None
        return issues_entry.get("value")
    except Exception:
        return None


def _priority(issue: dict):
    import ticket_policy
    rank = ticket_policy.priority_rank(issue)
    return None if rank is None else f"p{rank}"


def build_queue(repos, ready, machines) -> list[dict]:
    """Every project's ready tickets merged into one list in dispatch order. `ready(repo)` and `machines(repo)` are
    injected so the order logic is testable without GitHub; a project that cannot be read is skipped, not fatal.
    Each (repo, ticket_number) pair appears at most once, keeping the first occurrence."""
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
    seen = set()
    deduped = []
    for repo, t in pairs:
        key = (repo, t["number"])
        if key not in seen:
            seen.add(key)
            deduped.append((repo, t))
    return [{"position": i, "repo": repo, "project": repo.split("/")[-1], "number": t["number"], "title": t["title"],
             "priority": _priority(t), "score": t.get("_score", 0.0), "machines": list(machines(repo)),
             "createdAt": t["createdAt"]}
            for i, (repo, t) in enumerate(deduped, 1)]


def running_tickets(processes, fetch) -> list[dict]:
    """The tickets being worked on now (live run_ticket processes, see running_tickets.py), each with its title from
    `fetch(repo)` (that project's open issues, injected for tests). A claim label is NOT used: it outlives the run."""
    titles: dict[str, dict[int, str]] = {}
    out = []
    for p in processes:
        repo = p["repo"]
        if repo not in titles:
            try:
                titles[repo] = {i["number"]: i["title"] for i in fetch(repo)}
            except Exception as exc:  # noqa: BLE001
                print(f"[ticket-queue] {repo} unreadable: {exc}", file=sys.stderr)
                titles[repo] = {}
        out.append({"repo": repo, "project": repo.split("/")[-1], "number": p["number"],
                    "title": titles[repo].get(p["number"], f"#{p['number']}"), "machine": p["machine"]})
    return out


def _fetch_open(repo: str) -> list[dict]:
    """Fetch open issues from the feed if available, otherwise call gh directly."""
    # Try feed first (read-only, fast).
    issues = _read_issues_from_feed(repo)
    if issues is not None:
        # Feed has the full data; just extract number, title, labels for this use.
        return [{"number": i["number"], "title": i["title"], "labels": i.get("labels", [])} for i in issues]
    # Feed not available; call GitHub directly.
    import subprocess
    p = subprocess.run(["gh", "issue", "list", "--repo", repo, "--state", "open", "--limit", "200", "--json", "number,title,labels"],
                       capture_output=True, text=True, timeout=30)
    if p.returncode != 0:
        raise RuntimeError(p.stderr[:200])
    return json.loads(p.stdout)


def current_queue() -> list[dict]:
    import project_profile as pp
    import ticket_pipeline as tp
    repos = list(dict.fromkeys([tp.REPO, *pp.dispatchable_repos()]))
    return build_queue(
        repos,
        ready=lambda r: tp._unclaimed_ready_tickets(r),
        machines=lambda r: list(tp.MARVIN_MACHINES) if r == tp.REPO else pp.load_profile(r).get("machines", []))


def current() -> dict:
    """What the dashboard shows: the tickets running now and the queue behind them."""
    import running_tickets as rt
    return {"running": running_tickets(rt.current(), _fetch_open), "queue": current_queue()}


if __name__ == "__main__":
    print(json.dumps(current()))
