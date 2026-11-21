"""ticket_queue: the scanner's dispatch order across projects, as rows for the Activity tab's "Next up" strip."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ticket_queue as tq  # noqa: E402


def issue(n, title="t", created="2026-10-01T00:00:00Z", score=0.0, labels=()):
    return {"number": n, "title": title, "createdAt": created, "_score": score,
            "labels": [{"name": l} for l in labels]}


def build(per_repo, machines=None):
    return tq.build_queue(
        repos=list(per_repo),
        ready=lambda repo: per_repo[repo],
        machines=lambda repo: (machines or {}).get(repo, ["mac-mini-1"]))


def test_orders_across_projects_by_the_scanners_order_key():
    q = build({
        "o/a": [issue(1, score=1.0), issue(2, score=5.0)],
        "o/b": [issue(7, score=9.0, labels=["priority:p0"])],
    })
    assert [(r["repo"], r["number"]) for r in q] == [("o/b", 7), ("o/a", 2), ("o/a", 1)]  # label first, then score
    assert q[0]["number"] == 7                      # the priority label wins
    assert [r["position"] for r in q] == [1, 2, 3]


def test_row_carries_title_priority_machines_and_project_name():
    q = build({"o/clarity": [issue(36, "Speech languages", labels=["priority:p1"])]}, {"o/clarity": ["mac-mini-1", "macbook-pro-1"]})
    assert q[0] == {"position": 1, "repo": "o/clarity", "project": "clarity", "number": 36, "title": "Speech languages",
                    "priority": "p1", "score": 0.0, "machines": ["mac-mini-1", "macbook-pro-1"], "createdAt": "2026-10-01T00:00:00Z"}


def test_unprioritised_ticket_has_no_priority():
    assert build({"o/a": [issue(1)]})[0]["priority"] is None


def test_empty_when_nothing_is_ready():
    assert build({"o/a": []}) == []


def test_a_project_that_cannot_be_read_does_not_hide_the_others():
    def ready(repo):
        if repo == "o/bad":
            raise RuntimeError("gh down")
        return [issue(1)]
    q = tq.build_queue(repos=["o/bad", "o/a"], ready=ready, machines=lambda r: [])
    assert [r["number"] for r in q] == [1]


# --- what is running now: live processes joined with their titles (a claim label outlives the run, so it is not used) ---

def test_running_tickets_pair_each_process_with_its_title_and_machine():
    procs = [{"machine": "mac-mini-1", "repo": "o/a", "number": 1}, {"machine": "macbook-pro-1", "repo": "o/b", "number": 7}]
    issues = {"o/a": [{"number": 1, "title": "x"}], "o/b": [{"number": 7, "title": "z"}]}
    assert tq.running_tickets(procs, fetch=lambda repo: issues[repo]) == [
        {"repo": "o/a", "project": "a", "number": 1, "title": "x", "machine": "mac-mini-1"},
        {"repo": "o/b", "project": "b", "number": 7, "title": "z", "machine": "macbook-pro-1"}]


def test_a_ticket_whose_project_cannot_be_read_still_shows_by_number():
    def fetch(repo):
        raise RuntimeError("gh down")
    got = tq.running_tickets([{"machine": "m", "repo": "o/bad", "number": 4}], fetch=fetch)
    assert got[0]["title"] == "#4" and got[0]["machine"] == "m"


def test_nothing_running_is_empty():
    assert tq.running_tickets([], fetch=lambda r: []) == []


# --- deduplication: one repo queried twice should not duplicate its tickets ---

def test_duplicate_repos_in_queue_are_deduplicated():
    """If build_queue receives the same repo twice, each ticket should appear only once."""
    per_repo = {"o/a": [issue(1, score=1.0), issue(2, score=2.0)]}
    q = tq.build_queue(
        repos=["o/a", "o/a"],  # same repo twice
        ready=lambda repo: per_repo[repo],
        machines=lambda repo: ["m1"])
    # Should still have 2 tickets, not 4
    assert len(q) == 2
    assert [r["number"] for r in q] == [2, 1]  # sorted by score
    # Positions should be 1, 2 not 1, 2, 3, 4
    assert [r["position"] for r in q] == [1, 2]


def test_same_ticket_number_from_different_repos_are_kept_separate():
    """Multiple repos with the same ticket number keep both (different (repo, number) keys)."""
    q = tq.build_queue(
        repos=["o/a", "o/b"],
        ready=lambda repo: {
            "o/a": [issue(1, score=5.0)],
            "o/b": [issue(1, score=1.0)]  # same ticket #1, different repo
        }[repo],
        machines=lambda repo: ["m1"])
    # Should have both tickets since they have different (repo, number) keys
    assert len(q) == 2
    assert [r["number"] for r in q] == [1, 1]
    assert q[0]["repo"] == "o/a"  # o/a's ticket 1 first (higher score)
    assert q[1]["repo"] == "o/b"


def test_all_duplicate_tickets_across_multiple_identical_repos():
    """Edge case: same repo appears multiple times with same tickets; each ticket appears once."""
    per_repo = {"o/a": [issue(3, score=3.0), issue(7, score=7.0)]}
    q = tq.build_queue(
        repos=["o/a", "o/a", "o/a"],  # same repo three times
        ready=lambda repo: per_repo[repo],
        machines=lambda repo: ["m1"])
    # Should have only 2 tickets, with positions 1 and 2
    assert len(q) == 2
    assert [r["number"] for r in q] == [7, 3]  # sorted by score descending
    assert [r["position"] for r in q] == [1, 2]
