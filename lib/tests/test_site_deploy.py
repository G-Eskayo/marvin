"""The site's ship step and its alarm (marvin#1122, ADR 0080 I4). Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_site_deploy.py -v

"Shipped" for a site that deploys through Actions means GitHub's Pages deployment for that merge succeeded. Then each
ticket the shipped merges closed gets one comment with the live link. A failed publish opens one ticket through
main_red's path (never one that holds a merge), says nothing more for a re-run of the same commit, and closes when a
later publish succeeds. Health reads the deployments too, so a publish that never ran still shows.

GitHub and git are recorded fakes; the trouble cases are the point: still running, never triggered, API errors, a
success on an older commit, two merges close together.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

import site_deploy as sd  # noqa: E402

REPO = "o/marvin"
RUN = "https://github.com/o/marvin/actions/runs/7"
URL = "https://marvin.gileskayo.me/"
NOW = datetime(2026, 11, 4, 20, 0, tzinfo=timezone.utc)
FIX_TITLE = re.compile(r"\bmain\s+(?:is\s+)?red\b", re.I)   # dashboard/webhook-server/merge_order.js


def _err(args):
    return subprocess.CalledProcessError(1, ["gh", *args], "", "HTTP 502")


class FakeGh:
    """A tiny GitHub: open alarm tickets, tickets' comments, deployments with statuses, commit -> PRs -> tickets."""

    def __init__(self, open_alarm=(), deployments=(), pulls=None, closes=None, comments=None, fail=()):
        self.calls: list[list[str]] = []
        self.open_alarm = list(open_alarm)
        self.deployments = list(deployments)          # newest first: (id, sha, state, url)
        self.pulls = pulls or {}                      # commit -> [pr numbers]
        self.closes = closes or {}                    # pr -> [ticket numbers]
        self.comments = {k: list(v) for k, v in (comments or {}).items()}   # ticket -> [bodies]
        self.fail = set(fail)                         # substrings of a call that GitHub refuses

    def __call__(self, args: list[str]) -> str:
        self.calls.append(args)
        joined = " ".join(args)
        if any(f in joined for f in self.fail):
            raise _err(args)
        if args[:2] == ["issue", "list"]:
            return json.dumps([{"number": n, "title": "x"} for n in self.open_alarm])
        if args[:2] == ["issue", "create"]:
            return "https://github.com/o/marvin/issues/950\n"
        if args[:2] == ["issue", "view"]:
            n = int(args[2])
            return json.dumps({"body": "", "comments": [{"body": b} for b in self.comments.get(n, [])]})
        if args[:2] == ["issue", "comment"]:
            n = int(args[2])
            self.comments.setdefault(n, []).append(args[args.index("--body") + 1])
            return ""
        if args[:2] == ["pr", "view"]:
            n = int(args[2])
            return json.dumps({"closingIssuesReferences": [{"number": t} for t in self.closes.get(n, [])]})
        if args[0] == "api":
            path = args[1]
            if "/deployments?" in path:
                return json.dumps([{"id": i, "sha": s} for i, s, _, _ in self.deployments])
            m = re.search(r"/deployments/(\d+)/statuses", path)
            if m:
                d = next(d for d in self.deployments if d[0] == int(m.group(1)))
                return json.dumps([] if d[2] is None else [{"state": d[2], "environment_url": d[3]}])
            m = re.search(r"/commits/([0-9a-f]+)/pulls", path)
            if m:
                return json.dumps([{"number": n, "merged_at": "2026-11-04T19:00:00Z"} for n in self.pulls.get(m.group(1), [])])
        return ""

    def made(self, *prefix):
        return [c for c in self.calls if c[:len(prefix)] == list(prefix)]


class FakeGit:
    """A linear main: `history` oldest first; `site` the commits that touched the site; `when` commit times."""

    def __init__(self, history, site, when=None):
        self.history, self.site, self.when = list(history), set(site), when or {}

    def ancestor(self, a, b):
        if a not in self.history or b not in self.history:
            return None
        return self.history.index(a) <= self.history.index(b)

    def site_commits(self, a, b):
        i, j = self.history.index(a), self.history.index(b)
        return [c for c in self.history[i + 1:j + 1] if c in self.site]

    def last_site_change(self):
        for c in reversed(self.history):
            if c in self.site:
                return c, self.when.get(c, NOW - timedelta(hours=3))
        return None, None


A, B, C, S = "a" * 40, "b" * 40, "c" * 40, "d" * 40
OK = {"build": {"result": "success"}, "deploy": {"result": "success"}}
DEPLOY_FAILED = {"build": {"result": "success"}, "deploy": {"result": "failure"}}
BUILD_FAILED = {"build": {"result": "failure"}, "deploy": {"result": "skipped"}}
CANCELLED = {"build": {"result": "success"}, "deploy": {"result": "cancelled"}}


def _labels(call):
    return [call[i + 1] for i, a in enumerate(call) if a == "--label"]


# ── the alarm: one ticket, never one that holds a merge ─────────────────────────────────────────────────────────

def test_a_failed_publish_opens_one_ticket_that_never_holds_a_merge():
    gh = FakeGh()
    out = sd.report(DEPLOY_FAILED, S, RUN, REPO, URL, gh=gh, git=FakeGit([S], [S]))
    assert out["action"] == "opened"
    (create,) = gh.made("issue", "create")
    labels = _labels(create)
    assert "site-deploy-failed" in labels and "bug" in labels
    assert "main-red" not in labels and "priority:p0" not in labels   # the gate's isRedTicket reads these
    title = create[create.index("--title") + 1]
    assert S[:7] in title and not FIX_TITLE.search(title)
    assert "ready-for-agent" not in labels   # a Pages setting can't be fixed by an agent; triage decides


def test_a_build_that_failed_before_the_deploy_is_an_unpublished_site_too():
    gh = FakeGh()
    out = sd.report(BUILD_FAILED, S, RUN, REPO, URL, gh=gh, git=FakeGit([S], [S]))
    assert out["action"] == "opened"
    body = gh.made("issue", "create")[0]
    assert "Build site" in body[body.index("--body") + 1]


def test_a_rerun_of_the_same_commit_does_not_nag():
    gh = FakeGh(open_alarm=[950], comments={950: [f"Still not published at `{S[:7]}`"]})
    out = sd.report(DEPLOY_FAILED, S, RUN, REPO, URL, gh=gh, git=FakeGit([S], [S]))
    assert out["action"] == "already" and not gh.made("issue", "comment")


def test_a_new_commit_that_also_fails_adds_one_line_to_the_open_ticket():
    gh = FakeGh(open_alarm=[950], comments={950: [f"`{B[:7]}`"]})
    out = sd.report(DEPLOY_FAILED, S, RUN, REPO, URL, gh=gh, git=FakeGit([B, S], [B, S]))
    assert out["action"] == "attached" and len(gh.made("issue", "comment")) == 1
    assert not gh.made("issue", "create")


def test_a_later_success_clears_the_alarm():
    gh = FakeGh(open_alarm=[950], deployments=[(2, S, "success", URL)])
    out = sd.report(OK, S, RUN, REPO, URL, gh=gh, git=FakeGit([S], [S]))
    assert out["action"] == "closed" and gh.made("issue", "close")[0][2] == "950"


def test_a_cancelled_publish_says_nothing_either_way():
    """Two merges close together: GitHub replaces the waiting publish with the newer one. The older run is cancelled;
    the newer run reports for both."""
    gh = FakeGh(open_alarm=[950])
    out = sd.report(CANCELLED, S, RUN, REPO, URL, gh=gh, git=FakeGit([S], [S]))
    assert out["action"] == "none" and "shipped" not in out
    assert not gh.made("issue", "close") and not gh.made("issue", "comment")


# ── the ship step: one live-link comment per shipped ticket ─────────────────────────────────────────────────────

def test_a_shipped_merge_comments_the_live_link_on_the_ticket_it_closed():
    gh = FakeGh(deployments=[(2, S, "success", URL), (1, A, "success", URL)], pulls={S: [40]}, closes={40: [12]})
    out = sd.report(OK, S, RUN, REPO, URL, gh=gh, git=FakeGit([A, S], [A, S]))
    assert out["shipped"]["commented"] == [12]
    (comment,) = gh.comments[12]
    assert URL in comment and S[:7] in comment and sd.MARKER in comment


def test_two_merges_close_together_both_tickets_hear_and_an_engine_only_merge_does_not():
    # A shipped before; B (site) and C (engine only) merged, B's publish was cancelled, S's publish carries B too.
    gh = FakeGh(deployments=[(3, S, "success", URL), (2, B, "failure", None), (1, A, "success", URL)],
                pulls={B: [41], C: [42], S: [43]}, closes={41: [21], 42: [22], 43: [23]})
    out = sd.ship(S, URL, RUN, REPO, gh=gh, git=FakeGit([A, B, C, S], [A, B, S]))
    assert sorted(out["commented"]) == [21, 23]
    assert 22 not in gh.comments


def test_a_publish_somewhere_else_is_not_the_last_ship():
    # A legacy main:/docs build at g-eskayo.github.io isn't the site: the tickets since the last real publish all hear.
    gh = FakeGh(deployments=[(3, S, "success", URL), (2, B, "success", "https://g-eskayo.github.io/marvin/"),
                             (1, A, "success", URL)], pulls={B: [41], S: [43]}, closes={41: [21], 43: [23]})
    out = sd.ship(S, URL, RUN, REPO, gh=gh, git=FakeGit([A, B, S], [A, B, S]))
    assert sorted(out["commented"]) == [21, 23]


def test_a_ticket_that_already_has_its_live_link_is_left_alone():
    gh = FakeGh(deployments=[(2, S, "success", URL)], pulls={S: [40]}, closes={40: [12]},
                comments={12: [f"Live: {URL} {sd.MARKER}"]})
    out = sd.ship(S, URL, RUN, REPO, gh=gh, git=FakeGit([S], [S]))
    assert out["commented"] == [] and len(gh.comments[12]) == 1


def test_a_part_of_pr_closes_nothing_so_nothing_is_said():
    gh = FakeGh(deployments=[(2, S, "success", URL)], pulls={S: [40]}, closes={40: []})
    assert sd.ship(S, URL, RUN, REPO, gh=gh, git=FakeGit([S], [S]))["commented"] == []


def test_github_refusing_one_lookup_does_not_stop_the_others():
    gh = FakeGh(deployments=[(3, S, "success", URL), (1, A, "success", URL)], pulls={B: [41], S: [43]},
                closes={41: [21], 43: [23]}, fail={f"commits/{B}/pulls"})
    out = sd.ship(S, URL, RUN, REPO, gh=gh, git=FakeGit([A, B, S], [A, B, S]))
    assert out["commented"] == [23] and out["errors"]


def test_the_deployments_api_failing_still_ships_this_merge():
    gh = FakeGh(pulls={S: [43]}, closes={43: [23]}, fail={"/deployments?"})
    out = sd.ship(S, URL, RUN, REPO, gh=gh, git=FakeGit([A, S], [A, S]))
    assert out["commented"] == [23] and out["errors"]


def test_a_last_good_publish_not_on_mains_line_ships_only_this_merge():
    # A force-pushed main: the old deployment's commit isn't an ancestor any more.
    gh = FakeGh(deployments=[(2, S, "success", URL), (1, "e" * 40, "success", URL)], pulls={B: [41], S: [43]},
                closes={41: [21], 43: [23]})
    out = sd.ship(S, URL, RUN, REPO, gh=gh, git=FakeGit([A, B, S], [A, B, S]))
    assert out["commented"] == [23]


def test_no_page_url_from_the_deploy_falls_back_to_the_configured_site():
    gh = FakeGh(pulls={S: [43]}, closes={43: [23]})
    sd.ship(S, "", RUN, REPO, gh=gh, git=FakeGit([S], [S]))
    assert "https://marvin.gileskayo.me" in gh.comments[23][0]


# ── Health: a publish that never ran still shows; one that's running doesn't alarm ─────────────────────────────────

def test_health_is_green_when_mains_latest_site_change_is_live():
    gh = FakeGh(deployments=[(2, S, "success", URL)])
    r = sd.health(REPO, gh=gh, git=FakeGit([A, S], [S]), now=NOW)
    assert r["severity"] == "green" and URL in r["detail"]


def test_health_does_not_call_a_publish_somewhere_else_live_on_the_domain():
    """Found live 2026-11-04: the legacy Pages build (main:/docs) records github-pages deployments too, at
    g-eskayo.github.io/marvin/. That's not the site at marvin.gileskayo.me."""
    gh = FakeGh(deployments=[(2, S, "success", "https://g-eskayo.github.io/marvin/")])
    r = sd.health(REPO, gh=gh, git=FakeGit([A, S], [S]), now=NOW)
    assert r["severity"] == "yellow" and "marvin.gileskayo.me" in r["detail"] and "g-eskayo.github.io" in r["detail"]


def test_health_is_green_when_a_later_commits_publish_carries_the_change():
    gh = FakeGh(deployments=[(2, C, "success", URL)])
    r = sd.health(REPO, gh=gh, git=FakeGit([A, B, C], [B, C]), now=NOW)
    assert r["severity"] == "green"


def test_health_waits_quietly_while_the_publish_runs():
    gh = FakeGh(deployments=[(2, S, "in_progress", None), (1, A, "success", URL)])
    r = sd.health(REPO, gh=gh, git=FakeGit([A, S], [A, S]), now=NOW)
    assert r["severity"] == "yellow" and "publishing" in r["detail"]


def test_health_gives_a_fresh_merge_time_before_calling_a_missing_publish_red():
    gh = FakeGh(deployments=[(1, A, "success", URL)])
    git = FakeGit([A, S], [A, S], when={S: NOW - timedelta(minutes=5)})
    assert sd.health(REPO, gh=gh, git=git, now=NOW)["severity"] == "yellow"


def test_health_is_red_when_the_publish_never_ran_and_the_live_site_is_older():
    gh = FakeGh(deployments=[(1, A, "success", URL)])
    r = sd.health(REPO, gh=gh, git=FakeGit([A, S], [A, S]), now=NOW)
    assert r["severity"] == "red" and S[:7] in r["detail"] and A[:7] in r["detail"]


def test_health_is_red_when_the_latest_publish_failed():
    gh = FakeGh(deployments=[(2, S, "failure", None), (1, A, "success", URL)])
    r = sd.health(REPO, gh=gh, git=FakeGit([A, S], [A, S]), now=NOW)
    assert r["severity"] == "red" and "failed" in r["detail"]


def test_health_never_calls_red_on_what_it_could_not_read():
    gh = FakeGh(fail={"/deployments?"})
    r = sd.health(REPO, gh=gh, git=FakeGit([A, S], [S]), now=NOW)
    assert r["severity"] == "unknown"


def test_health_has_nothing_to_say_before_the_site_ever_changed():
    gh = FakeGh()
    r = sd.health(REPO, gh=gh, git=FakeGit([A], []), now=NOW)
    assert r["severity"] == "green" and not gh.calls   # no GitHub calls spent on a site that never changed


def test_the_site_paths_come_from_the_workflow_itself():
    paths = sd.site_paths()
    assert "site/**" in paths and ".github/workflows/site.yml" in paths


# ── wiring ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_workflow_reports_after_every_publish_on_main():
    import yaml
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "site.yml").read_text())
    job = wf["jobs"]["report"]
    assert "always()" in job["if"] and "github.event_name == 'push'" in job["if"]
    assert set(job["needs"]) == {"build", "deploy"}
    assert job["permissions"] == {"issues": "write", "contents": "read", "deployments": "read", "pull-requests": "read"}
    run = " ".join(s.get("run", "") for s in job["steps"])
    assert "lib/site_deploy.py report" in run and "toJSON(needs)" in json.dumps(job)
    assert "needs.deploy.outputs.page_url" in json.dumps(job)
    assert wf["jobs"]["deploy"]["outputs"]["page_url"] == "${{ steps.deployment.outputs.page_url }}"


def test_health_runs_the_site_check():
    import health_checks as hc
    ids = [c[0] for c in hc.default_checks({}, [])]
    assert "site:published" in ids
