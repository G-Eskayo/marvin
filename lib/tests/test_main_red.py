"""marvin#826 step 4: every merge to main runs the full suite; when main goes red, a fix-forward ticket opens at once,
labelled priority:p0 and dispatched before anything else. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_main_red.py -v

The owner's answer on #826: "when main is red, the tickets that make it green are always top priority". CI's
`main-red` job calls lib/main_red.py after the checks on every push to main. GitHub is a recorded fake here (tests
never reach real GitHub); the ticket body goes through the real triage and the real dispatch order.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

import main_red as mr  # noqa: E402
import ticket_pipeline as tp  # noqa: E402
import ticket_policy as pol  # noqa: E402

RUN = "https://github.com/o/marvin/actions/runs/1"


class FakeGh:
    """Records every gh call; answers `issue list` with the open main-red tickets it holds."""

    def __init__(self, open_tickets=()):
        self.calls: list[list[str]] = []
        self.open = list(open_tickets)

    def __call__(self, args: list[str]) -> str:
        self.calls.append(args)
        if args[:2] == ["issue", "list"]:
            return json.dumps([{"number": n, "title": f"Main is red ({n})"} for n in self.open])
        if args[:2] == ["issue", "create"]:
            return "https://github.com/o/marvin/issues/901\n"
        return ""

    def made(self, *prefix: str) -> list[list[str]]:
        return [c for c in self.calls if c[:len(prefix)] == list(prefix)]


def _flag(call: list[str], flag: str) -> list[str]:
    return [call[i + 1] for i, a in enumerate(call) if a == flag]


RED = {"Rules": "success", "Python tests": "failure", "Dashboard unit tests": "success"}
GREEN = {"Rules": "success", "Python tests": "success", "Dashboard unit tests": "success"}


def test_a_red_main_opens_one_p0_fix_forward_ticket_that_names_what_failed():
    gh = FakeGh()
    r = mr.report(RED, sha="abc1234def", run_url=RUN, repo="o/marvin", gh=gh)
    assert r == {"state": "red", "ticket": 901, "action": "opened"}
    (create,) = gh.made("issue", "create")
    labels = _flag(create, "--label")
    assert {"priority:p0", "ready-for-agent", "bug", mr.LABEL, "project:marvin"} <= set(labels)
    body = _flag(create, "--body")[0]
    assert "Python tests" in body and "abc1234" in body and RUN in body
    assert "Dashboard unit tests" not in body.split("## What to build")[0]  # only what failed is named as failing


def test_the_ticket_passes_triage_as_ready_for_an_agent():
    body = mr.ticket_body(["Python tests"], "abc1234def", RUN)
    issue = {"title": mr.title("abc1234def"), "body": body, "labels": []}
    assert pol.triage_verdict(issue)["state"] == "ready-for-agent"


def test_a_second_red_push_adds_to_the_open_ticket_instead_of_opening_another():
    gh = FakeGh(open_tickets=[777])
    r = mr.report(RED, sha="fff0000", run_url=RUN, repo="o/marvin", gh=gh)
    assert r == {"state": "red", "ticket": 777, "action": "attached"}
    assert gh.made("issue", "create") == []
    (comment,) = gh.made("issue", "comment")
    assert comment[2] == "777" and "fff0000" in _flag(comment, "--body")[0]


def test_green_again_closes_the_open_ticket_and_says_at_which_commit():
    gh = FakeGh(open_tickets=[777])
    assert mr.report(GREEN, sha="9999999", run_url=RUN, repo="o/marvin", gh=gh) == \
        {"state": "green", "ticket": 777, "action": "closed"}
    (close,) = gh.made("issue", "close")
    assert close[2] == "777" and "9999999" in _flag(close, "--comment")[0]


def test_green_with_nothing_open_does_nothing():
    gh = FakeGh()
    assert mr.report(GREEN, sha="1", run_url=RUN, repo="o/marvin", gh=gh)["action"] == "none"
    assert [c[:2] for c in gh.calls] == [["issue", "list"]]


@pytest.mark.parametrize("results", [
    {"Rules": "success", "Python tests": "cancelled"},  # a newer push cancelled this run: says nothing about main
    {"Rules": "success", "Python tests": "skipped"},  # on main nothing should skip: not proof of green
    {},
])
def test_a_cancelled_or_empty_run_is_neither_red_nor_green(results):
    gh = FakeGh(open_tickets=[777])
    assert mr.report(results, sha="1", run_url=RUN, repo="o/marvin", gh=gh)["state"] == "unknown"
    assert gh.made("issue", "close") == [] and gh.made("issue", "create") == []


def test_the_label_is_made_if_missing_and_an_existing_one_is_left_alone():
    gh = FakeGh()
    mr.report(RED, sha="1", run_url=RUN, repo="o/marvin", gh=gh)
    made = gh.made("label", "create")
    assert {c[2] for c in made} == {mr.LABEL, "project:marvin"}
    assert all("--force" not in c for c in made)  # never rewrites a label someone already set up


def test_the_cli_reads_the_results_ci_hands_it(monkeypatch, capsys):
    gh = FakeGh()
    monkeypatch.setattr(mr, "_gh", gh)
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/marvin")
    code = mr.main(["report", "--sha", "abc", "--run", RUN, "--results", json.dumps(RED)])
    assert code == 0 and json.loads(capsys.readouterr().out)["ticket"] == 901


def test_unreadable_results_fail_loudly():
    with pytest.raises(SystemExit):
        mr.main(["report", "--sha", "abc", "--run", RUN, "--results", "{nope"])


# ── dispatched first ────────────────────────────────────────────────────────

def _ticket(n, labels, created="2026-10-01T00:00:00Z"):
    return {"number": n, "labels": [{"name": l} for l in labels], "createdAt": created, "_score": 30.0}


def test_the_main_red_ticket_is_dispatched_before_older_p0_bugs():
    older = _ticket(1, ["priority:p0", "bug", "ready-for-agent"], "2026-09-01T00:00:00Z")
    red = _ticket(2, ["priority:p0", "bug", "ready-for-agent", mr.LABEL], "2026-10-30T00:00:00Z")
    assert min([older, red], key=tp._order_key)["number"] == 2


# ── CI wiring ───────────────────────────────────────────────────────────────

def test_ci_reports_main_after_every_push_to_it_with_every_checks_result():
    jobs = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text())["jobs"]
    job = jobs["main-red"]
    assert "github.event_name == 'push'" in job["if"] and "always()" in job["if"]
    import required_checks
    test_jobs = {k for k, j in jobs.items() if j.get("name") in required_checks.names(ROOT) and k != "secret-scan"}
    assert test_jobs <= set(job["needs"])
    assert job["permissions"] == {"issues": "write", "contents": "read"}
    run = " ".join(s.get("run", "") for s in job["steps"])
    assert "lib/main_red.py report" in run and "toJSON(needs)" in json.dumps(job)
