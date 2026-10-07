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


# --- what is running now: open tickets carrying a claim label, on whichever machine claimed them ---

def test_running_tickets_are_the_claimed_open_ones_with_their_machine():
    issues = {"o/a": [{"number": 1, "title": "x", "labels": [{"name": "claimed:mac-mini"}, {"name": "ready-for-agent"}]},
                      {"number": 2, "title": "y", "labels": [{"name": "ready-for-agent"}]}],
              "o/b": [{"number": 7, "title": "z", "labels": [{"name": "claimed:macbook-pro"}]}]}
    got = tq.running_tickets(["o/a", "o/b"], fetch=lambda repo: issues[repo])
    assert got == [{"repo": "o/a", "project": "a", "number": 1, "title": "x", "machine": "mac-mini-1"},
                   {"repo": "o/b", "project": "b", "number": 7, "title": "z", "machine": "macbook-pro-1"}]


def test_an_unreadable_project_is_skipped_when_listing_running_tickets():
    def fetch(repo):
        if repo == "o/bad":
            raise RuntimeError("gh down")
        return [{"number": 1, "title": "x", "labels": [{"name": "claimed:mac-mini"}]}]
    assert [r["number"] for r in tq.running_tickets(["o/bad", "o/a"], fetch=fetch)] == [1]


def test_an_unknown_claim_label_keeps_its_own_name_as_the_machine():
    got = tq.running_tickets(["o/a"], fetch=lambda r: [{"number": 1, "title": "x", "labels": [{"name": "claimed:node-3"}]}])
    assert got[0]["machine"] == "node-3"
