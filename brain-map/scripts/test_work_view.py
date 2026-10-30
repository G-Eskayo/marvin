#!/usr/bin/env python3
"""Tests for work_view.py, the Work half of the map's Body and Work mock-up (#854).

Work is one node per monitored system or project, from the project catalog, holding the workers doing work on it:
chat helpers and spawned agents (their run logs), pipeline builders (ticket stages) and the scheduled jobs that serve
it (the job catalog's declared goal). The ticket's break-it list is here: 0, 42 and 30-worker projects, a worker or
job whose project can't be found (Unassigned, never dropped), and 50 helpers starting and stopping in a minute.

    ~/.agents/venv/bin/python -m pytest brain-map/scripts/test_work_view.py -v
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import work_view as wv  # noqa: E402

T0 = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)
NOW = T0.timestamp()
OWNER = "pat-example"


def iso(dt: datetime) -> str:
    return dt.isoformat()


def project(pid, *, status="active", repo=None, paths=(), name=None):
    return {"id": pid, "name": name or pid, "status": status, "repo": repo, "localPaths": list(paths)}


def catalog(n=2):
    base = [project("marvin", repo=f"{OWNER}/marvin", paths=["/h/.agents"]),
            project("seal", repo=f"{OWNER}/seal", paths=["/h/Developer/seal"])]
    return base + [project(f"p{i}", repo=f"{OWNER}/p{i}", paths=[f"/h/Developer/p{i}"]) for i in range(max(0, n - 2))]


def helper(aid, *, cwd="", status="running", started=T0 - timedelta(minutes=1), finished=None, links=(), label=None,
           chat="fix the docs"):
    return {"job": f"helper-{aid}", "label": label or f"helper {aid}", "kind": "helper",
            "helper": {"agent_id": aid, "agent_type": "general-purpose", "session": "s1", "chat": chat, "cwd": cwd,
                       "transcript": "", "links": list(links)},
            "runs": [{"status": status, "started_at": iso(started), "finished_at": iso(finished) if finished else None}]}


def stages(*events):
    return [{"stage": s, "status": st, "timestamp": iso(at), "title": t} for s, st, at, t in events]


def by_id(workers):
    return {w["id"]: w for w in workers}


# ── projects ────────────────────────────────────────────────────────────────

def test_monitored_projects_are_the_active_and_recent_ones_including_marvin():
    cat = catalog() + [project("old", status="dormant"), project("gone", status="archived"), project("new", status="recent")]
    assert [p["id"] for p in wv.monitored_projects(cat)] == ["marvin", "seal", "new"]


def test_zero_projects_still_gives_a_work_half_with_unassigned():
    workers = wv.helper_workers([helper("a1", cwd="/h/Developer/seal")], [], NOW)
    tree = wv.work_trunk([], workers)
    assert [c["id"] for c in tree["children"]] == [wv.UNASSIGNED]
    assert [w["id"] for w in tree["children"][0]["children"]] == ["helper:a1"]


def test_forty_two_projects_are_all_shown():
    projects = wv.monitored_projects(catalog(42))
    tree = wv.work_trunk(projects, [])
    assert len([c for c in tree["children"] if c["id"] != wv.UNASSIGNED]) == 42


def test_a_project_with_thirty_workers_shows_all_thirty():
    projects = wv.monitored_projects(catalog())
    docs = [helper(f"a{i:02d}", cwd="/h/Developer/seal") for i in range(30)]
    tree = wv.work_trunk(projects, wv.helper_workers(docs, projects, NOW))
    seal = next(c for c in tree["children"] if c["projectId"] == "seal")
    assert len(seal["children"]) == 30
    assert len({w["id"] for w in seal["children"]}) == 30


# ── which project a helper works on ─────────────────────────────────────────

def test_a_helper_goes_under_the_project_its_folder_is_in_longest_path_wins():
    projects = wv.monitored_projects([project("outer", paths=["/h/Developer"]), project("seal", paths=["/h/Developer/seal"])])
    w = wv.helper_workers([helper("a1", cwd="/h/Developer/seal/Sources")], projects, NOW)
    assert w[0]["project"] == "seal"


def test_a_folder_that_only_shares_a_prefix_is_not_inside_the_project():
    projects = wv.monitored_projects([project("seal", paths=["/h/Developer/seal"])])
    w = wv.helper_workers([helper("a1", cwd="/h/Developer/seal-icons")], projects, NOW)
    assert w[0]["project"] is None


def test_a_helper_in_a_worktree_is_placed_by_the_repo_its_folder_pushes_to():
    projects = wv.monitored_projects(catalog())
    remote = {"/tmp/wt-1": f"{OWNER}/Seal"}  # case differs from the catalog: still the same repo
    w = wv.helper_workers([helper("a1", cwd="/tmp/wt-1")], projects, NOW, remote_of=remote.get)
    assert w[0]["project"] == "seal"


def test_a_helper_with_no_folder_match_is_placed_by_the_tickets_its_report_names():
    projects = wv.monitored_projects(catalog())
    links = [{"kind": "pr", "repo": f"{OWNER}/seal", "number": 3}, {"kind": "ticket", "repo": f"{OWNER}/seal", "number": 2},
             {"kind": "ticket", "repo": f"{OWNER}/marvin", "number": 9}]
    w = wv.helper_workers([helper("a1", cwd="/h", links=links, status="failed", finished=T0)], projects, NOW)
    assert w[0]["project"] == "seal"


def test_a_helper_whose_project_cant_be_found_is_unassigned_never_dropped():
    projects = wv.monitored_projects(catalog())
    workers = wv.helper_workers([helper("a1", cwd="/somewhere/else")], projects, NOW, remote_of=lambda _c: None)
    tree = wv.work_trunk(projects, workers)
    unassigned = next(c for c in tree["children"] if c["id"] == wv.UNASSIGNED)
    assert [w["id"] for w in unassigned["children"]] == ["helper:a1"]


def test_a_worker_for_a_project_not_on_the_map_is_unassigned():
    workers = [{"id": "helper:x", "name": "x", "kind": "helper", "state": "running", "project": "ghost", "desc": ""}]
    tree = wv.work_trunk(wv.monitored_projects(catalog()), workers)
    assert next(c for c in tree["children"] if c["id"] == wv.UNASSIGNED)["children"][0]["id"] == "helper:x"


def test_a_chat_helper_and_a_spawned_agent_are_told_apart_by_whether_a_chat_started_it():
    w = by_id(wv.helper_workers([helper("a1"), helper("a2", chat="")], [], NOW))
    assert (w["helper:a1"]["kind"], w["helper:a2"]["kind"]) == ("helper", "agent")
    assert w["helper:a1"]["agent"] == "a1"


# ── alive, finished, died ───────────────────────────────────────────────────

def test_a_helper_that_finished_cleanly_leaves_at_once():
    w = wv.helper_workers([helper("done", status="passed", finished=T0 - timedelta(seconds=1))], [], NOW)
    assert w == []


def test_a_running_helper_has_not_ended():
    assert wv.helper_workers([helper("a1")], [], NOW)[0]["ended"] is None


def test_a_helper_that_failed_is_red_and_one_killed_mid_run_is_too():
    docs = [helper("f", status="failed", finished=T0 - timedelta(minutes=1)),
            helper("killed", started=T0 - timedelta(minutes=20))]  # no stop and quiet past chat_helpers.STALE_S
    w = by_id(wv.helper_workers(docs, [], NOW))
    assert w["helper:f"]["state"] == "failed"
    assert w["helper:killed"]["state"] == "failed"


def test_a_dead_helper_stays_red_however_long_ago_it_died():
    # Gil, 2026-10-30: no fading. Red until a retry passes or someone dismisses it (the page's tray).
    docs = [helper("old-fail", status="failed", finished=T0 - timedelta(days=9)),
            helper("old-kill", started=T0 - timedelta(days=3))]
    w = by_id(wv.helper_workers(docs, [], NOW))
    assert w["helper:old-fail"]["state"] == w["helper:old-kill"]["state"] == "failed"
    # `ended` names this one failure, so a dismissal of it doesn't hide a later one
    assert w["helper:old-fail"]["ended"] == (T0 - timedelta(days=9)).timestamp()


def test_fifty_helpers_starting_and_stopping_in_a_minute():
    projects = wv.monitored_projects(catalog())
    start = T0 - timedelta(seconds=60)
    running, stopped = [], []
    for i in range(50):
        began = start + timedelta(seconds=i)
        running.append(helper(f"c{i:02d}", cwd="/h/Developer/seal", started=began))
        stopped.append(helper(f"c{i:02d}", cwd="/h/Developer/seal", started=began, status="passed",
                              finished=began + timedelta(seconds=10)))
    during = wv.helper_workers(running, projects, NOW)
    assert len(during) == 50 and len({w["id"] for w in during}) == 50
    assert wv.helper_workers(stopped, projects, NOW) == []


def test_broken_helper_logs_are_skipped_not_fatal():
    docs = [{}, {"runs": "no"}, {"helper": "x", "runs": [{}]}, helper("ok")]
    assert [w["id"] for w in wv.helper_workers(docs, [], NOW)] == ["helper:ok"]


# ── pipeline builders ───────────────────────────────────────────────────────

def test_a_ticket_being_built_is_a_running_builder_under_its_project():
    projects = wv.monitored_projects(catalog())
    st = {(f"{OWNER}/seal", 7): stages(("claimed", "passed", T0 - timedelta(minutes=3), "Add face-to-face"),
                                       ("executing", "started", T0 - timedelta(minutes=2), None))}
    w = wv.builder_workers(st, projects, NOW)
    assert w == [{"id": f"builder:{OWNER}/seal#7", "name": "#7 Add face-to-face", "kind": "builder", "state": "running",
                  "project": "seal", "ended": None, "desc": "Pipeline builder: executing started"}]
    assert not hasattr(wv, "FADE_S")  # no fading (Gil, 2026-10-30)


def test_a_builder_that_finished_leaves_and_one_that_died_is_red_until_a_retry_passes():
    st = {(f"{OWNER}/marvin", 1): stages(("done", "passed", T0 - timedelta(seconds=5), None)),
          (f"{OWNER}/marvin", 3): stages(("verifying", "failed", T0 - timedelta(days=4), None)),
          (f"{OWNER}/marvin", 4): stages(("executing", "started", T0 - timedelta(minutes=35), None)),  # went quiet
          (f"{OWNER}/marvin", 5): stages(("verifying", "failed", T0 - timedelta(hours=2), None),     # the retry
                                         ("claimed", "started", T0 - timedelta(hours=1), None),
                                         ("done", "passed", T0 - timedelta(minutes=50), None))}
    w = by_id(wv.builder_workers(st, wv.monitored_projects(catalog()), NOW))
    assert f"builder:{OWNER}/marvin#1" not in w
    assert w[f"builder:{OWNER}/marvin#3"]["state"] == "failed"
    assert w[f"builder:{OWNER}/marvin#4"]["state"] == "failed"
    assert f"builder:{OWNER}/marvin#5" not in w


def test_a_builder_for_a_repo_with_no_project_is_unassigned():
    st = {(f"{OWNER}/unknown", 1): stages(("planning", "started", T0, None))}
    assert wv.builder_workers(st, wv.monitored_projects(catalog()), NOW)[0]["project"] is None


def test_empty_or_unreadable_ticket_timelines_are_skipped():
    st = {(f"{OWNER}/marvin", 1): [], (f"{OWNER}/marvin", 2): [{"stage": "x"}]}
    assert wv.builder_workers(st, [], NOW) == []


# ── scheduled jobs ──────────────────────────────────────────────────────────

JOBS = {
    "for-seal": {"machine": "mini", "goal": "project:seal"},
    "north-star": {"machine": "both", "goal": "ns1"},
    "no-goal": {"machine": "both", "goal": None},
    "lost-goal": {"machine": "both", "goal": "project:not-in-catalog"},
    "switched-off": {"machine": "none", "goal": "project:seal"},
}


ALL_RUNNING = {name: {"runs": [{"status": "running", "started_at": iso(T0)}]} for name in JOBS}


def test_each_job_goes_under_the_project_its_declared_goal_names():
    w = by_id(wv.job_workers(JOBS, ALL_RUNNING, [], wv.monitored_projects(catalog()), NOW))
    assert w["job:for-seal"]["project"] == "seal"
    assert w["job:north-star"]["project"] == "marvin"  # the north stars are MARVIN's own


def test_a_job_with_no_declared_goal_is_unassigned():
    w = by_id(wv.job_workers(JOBS, ALL_RUNNING, [], wv.monitored_projects(catalog()), NOW))
    assert w["job:no-goal"]["project"] is None
    assert w["job:lost-goal"]["project"] is None


RUNNING = {"runs": [{"status": "running", "started_at": iso(T0 - timedelta(minutes=2))}]}


def test_a_job_running_here_but_not_in_the_catalog_is_unassigned_not_dropped():
    logs = {"mystery": RUNNING, "for-seal": RUNNING}
    w = by_id(wv.job_workers(JOBS, logs, ["mystery", "for-seal"], wv.monitored_projects(catalog()), NOW))
    assert w["job:mystery"]["project"] is None and w["job:mystery"]["state"] == "running"
    assert len([k for k in w if k == "job:for-seal"]) == 1


def test_a_job_shows_only_while_running_or_red_after_a_failure():
    logs = {"for-seal": RUNNING,
            "north-star": {"runs": [{"status": "failed", "started_at": iso(T0 - timedelta(hours=2)),
                                     "finished_at": iso(T0 - timedelta(hours=2))}]},
            "no-goal": {"runs": [{"status": "running", "started_at": iso(T0 - timedelta(hours=2))}]},  # crashed
            "lost-goal": {"runs": [{"status": "passed", "started_at": iso(T0), "finished_at": iso(T0)}]},
            "switched-off": RUNNING}
    w = by_id(wv.job_workers(JOBS, logs, [], wv.monitored_projects(catalog()), NOW))
    assert w["job:for-seal"]["state"] == "running"
    assert w["job:north-star"]["state"] == "failed"
    assert w["job:no-goal"]["state"] == "failed"
    assert "job:lost-goal" not in w      # idle: not drawn
    assert "job:switched-off" not in w   # off: not drawn, whatever its log says
    assert w["job:north-star"]["ended"] == (T0 - timedelta(hours=2)).timestamp()


def test_a_failed_job_whose_next_run_passed_is_gone():
    logs = {"for-seal": {"runs": [{"status": "failed", "started_at": iso(T0 - timedelta(hours=2))},
                                  {"status": "passed", "started_at": iso(T0), "finished_at": iso(T0)}]}}
    assert wv.job_workers(JOBS, logs, [], wv.monitored_projects(catalog()), NOW) == []


# ── the whole half, from disk ───────────────────────────────────────────────

def test_read_live_reads_every_source_and_survives_junk(tmp_path):
    claude = tmp_path / "claude"
    jobs_dir = claude / "logs" / "jobs"
    stages_dir = claude / "logs" / "ticket-stages"
    jobs_dir.mkdir(parents=True)
    stages_dir.mkdir(parents=True)
    (claude / "catalog").mkdir()
    (claude / "catalog" / "projects.m1.json").write_text(json.dumps({"projects": catalog()}))
    (jobs_dir / "helper-a1.json").write_text(json.dumps(helper("a1", cwd="/h/Developer/seal")))
    (jobs_dir / "helper-bad.json").write_text("{not json")
    (jobs_dir / "for-seal.json").write_text(json.dumps({"runs": [{"status": "running", "started_at": iso(T0)}]}))
    (stages_dir / f"{OWNER}__seal-7.json").write_text(json.dumps(stages(("planning", "started", T0, "x"))))
    (stages_dir / "junk.json").write_text("[]")
    doc = wv.read_live(claude_dir=claude, jobs=JOBS, loaded=[], now=NOW, remote_of=lambda _c: None)
    ids = {w["id"]: w for w in doc["workers"]}
    assert ids["helper:a1"]["project"] == "seal"
    assert ids["job:for-seal"]["state"] == "running"
    assert ids[f"builder:{OWNER}/seal#7"]["project"] == "seal"
    assert [p["id"] for p in doc["projects"]] == ["marvin", "seal"]


def test_read_live_with_no_catalog_or_logs_is_empty_not_a_crash(tmp_path):
    doc = wv.read_live(claude_dir=tmp_path / "nothing", jobs={}, loaded=[], now=NOW)
    assert doc["projects"] == [] and doc["workers"] == []


def test_the_writer_replaces_work_json_whole(tmp_path):
    out = tmp_path / "work.json"
    out.write_text("old")
    wv.write(out, {"projects": [], "workers": []})
    assert json.loads(out.read_text())["workers"] == []
    assert not list(tmp_path.glob(".*tmp"))


def test_the_cli_runs_with_an_empty_home(tmp_path):
    out = tmp_path / "work.json"
    r = subprocess.run([sys.executable, str(Path(wv.__file__)), "--out", str(out)], env={"HOME": str(tmp_path)},
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert json.loads(out.read_text())["workers"] is not None


# ── a dead worker also clears when its ticket closed or its PR merged (Gil, 2026-10-30) ──
# Read from what is already on this Mac: each project's own clone (its main branch as last fetched) and the
# dashboard's merged-PR list. No GitHub call per worker. What can't be read stays red, saying so.

def git_repo(tmp_path, subjects):
    d = tmp_path / "clone"
    d.mkdir()
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x",
           "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    run = lambda *a: subprocess.run(["git", *a], cwd=d, env=env, check=True, capture_output=True)
    run("init", "-q", "-b", "main")
    for s in subjects:
        run("commit", "-q", "--allow-empty", "-m", s)
    run("update-ref", "refs/remotes/origin/main", "HEAD")
    return d


def test_the_clones_main_says_which_tickets_were_done_and_which_prs_merged(tmp_path):
    clone = git_repo(tmp_path, ["Fix the thing (#12)", "Merge pull request #30 from o/ticket-31-x", "docs: notes on #13",
                                "Implements #14 and more", "Revert \"Fix other (#15)\""])
    st = wv.RepoState.from_clone(str(clone))
    assert st.ticket_done(12) and st.ticket_done(14)
    assert not st.ticket_done(13) and not st.ticket_done(15)  # a docs mention and a revert don't count
    assert st.pr_merged(30) and not st.pr_merged(12 + 100)


def test_a_folder_that_is_not_a_clone_reads_as_unknown(tmp_path):
    assert wv.RepoState.from_clone(str(tmp_path)) is None
    assert wv.RepoState.from_clone(str(tmp_path / "gone")) is None


def test_the_dashboards_merged_pr_list_counts_too():
    st = wv.RepoState([], merged_prs={41})
    assert st.pr_merged(41)


def dead_builder(n, at=T0 - timedelta(days=3)):
    return {(f"{OWNER}/marvin", n): stages(("verifying", "failed", at, None))}


def settled_by(states):
    return wv.settled_by(states)


def test_a_dead_builder_whose_ticket_was_merged_since_leaves():
    states = {f"{OWNER}/marvin".lower(): wv.RepoState(["Close the gap (#7)"])}
    assert wv.builder_workers(dead_builder(7), wv.monitored_projects(catalog()), NOW, settled=settled_by(states)) == []


def test_a_dead_builder_with_nothing_merged_stays_red():
    states = {f"{OWNER}/marvin".lower(): wv.RepoState(["Something else (#8)"])}
    w = wv.builder_workers(dead_builder(7), wv.monitored_projects(catalog()), NOW, settled=settled_by(states))
    assert w[0]["state"] == "failed" and "couldn't confirm" not in w[0]["desc"]


def test_a_dead_builder_whose_repo_cant_be_read_stays_red_saying_so():
    w = wv.builder_workers(dead_builder(7), wv.monitored_projects(catalog()), NOW, settled=settled_by({}))
    assert w[0]["state"] == "failed" and "couldn't confirm" in w[0]["desc"]
    assert w[0]["confirmed"] is False


def test_a_dead_helper_clears_when_a_pr_or_ticket_its_report_names_has_merged():
    states = {f"{OWNER}/seal": wv.RepoState(["Merge pull request #5 from o/x"]), f"{OWNER}/marvin": wv.RepoState(["Do it (#9)"])}
    dead = lambda aid, links: helper(aid, status="failed", finished=T0, links=links)
    docs = [dead("pr", [{"kind": "pr", "repo": f"{OWNER}/Seal", "number": 5}]),
            dead("ticket", [{"kind": "ticket", "repo": f"{OWNER}/marvin", "number": 9}]),
            dead("open", [{"kind": "ticket", "repo": f"{OWNER}/marvin", "number": 10}]),
            dead("nothing", [])]
    w = by_id(wv.helper_workers(docs, wv.monitored_projects(catalog()), NOW, remote_of=lambda _c: None,
                                settled=settled_by(states)))
    assert set(w) == {"helper:open", "helper:nothing"}
    assert "couldn't confirm" not in w["helper:open"]["desc"]
    assert "couldn't confirm" in w["helper:nothing"]["desc"]  # its report names no ticket or PR to check


def test_a_running_worker_is_never_cleared_by_old_merges():
    states = {f"{OWNER}/seal": wv.RepoState(["Done (#7)"])}
    st = {(f"{OWNER}/seal", 7): stages(("executing", "started", T0, None))}
    assert wv.builder_workers(st, wv.monitored_projects(catalog()), NOW, settled=settled_by(states))[0]["state"] == "running"


def test_read_live_reads_each_projects_clone_once(tmp_path, monkeypatch):
    clone = git_repo(tmp_path, ["Fix (#7)"])
    claude = tmp_path / "claude"
    (claude / "logs" / "ticket-stages").mkdir(parents=True)
    (claude / "catalog").mkdir()
    (claude / "catalog" / "projects.m.json").write_text(json.dumps({"projects": [
        project("seal", repo=f"{OWNER}/seal", paths=[str(clone)])]}))
    for n in (7, 8):
        (claude / "logs" / "ticket-stages" / f"{OWNER}__seal-{n}.json").write_text(
            json.dumps(stages(("verifying", "failed", T0, None))))
    (claude / "logs" / "mr-history.json").write_text(json.dumps({"merged": [{"repo": f"{OWNER}/seal", "number": 8,
                                                                              "title": "Implement #8"}]}))
    reads = []
    real = wv.RepoState.from_clone
    monkeypatch.setattr(wv.RepoState, "from_clone", staticmethod(lambda p: reads.append(p) or real(p)))
    doc = wv.read_live(claude_dir=claude, jobs={}, loaded=[], now=NOW, remote_of=lambda _c: None)
    assert [w["id"] for w in doc["workers"]] == []  # 7 merged on main; 8's PR is in the dashboard's merged list
    assert reads == [str(clone)]
