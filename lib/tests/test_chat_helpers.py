"""Tests for chat_helpers.py (#612): helpers started from a chat get a run log the Activity tab shows.
    ~/.agents/venv/bin/python -m pytest lib/tests/test_chat_helpers.py -v
Every test writes under tmp_path (or a temp HOME for the subprocess ones), never the real ~/.claude.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import chat_helpers as ch  # noqa: E402

T0 = datetime(2026, 10, 22, 15, tzinfo=timezone.utc)
SESSION = "b41ed591-f7da-40f3-8ec4-73db4398eb1b"


def env(tmp_path, *, request="fix the docs search", meta=None):
    """A fake ~/.claude: jobs dir, the live sessions list, and a parent transcript with a subagents folder."""
    root = tmp_path / "claude"
    proj = root / "projects" / "-Users-gil"
    (proj / SESSION / "subagents").mkdir(parents=True)
    transcript = proj / f"{SESSION}.jsonl"
    transcript.write_text("{}\n")
    sessions = root / "logs" / "sessions-active.json"
    sessions.parent.mkdir(parents=True)
    sessions.write_text(json.dumps({"sessions": {SESSION: {"request": request, "last": 0, "files": {}}}}))
    if meta:
        for aid, m in meta.items():
            (proj / SESSION / "subagents" / f"agent-{aid}.meta.json").write_text(json.dumps(m))
    return {"jobs": root / "logs" / "jobs", "sessions": sessions, "transcript": str(transcript)}


def fire(e, event, now=T0, **payload):
    base = {"session_id": SESSION, "transcript_path": e["transcript"], "cwd": "/Users/gil"}
    ch.handle(event, json.dumps({**base, **payload}), jobs_dir=e["jobs"], sessions_path=e["sessions"],
              machine="macbook-pro", now=now)


def doc(e, aid):
    return json.loads((e["jobs"] / f"helper-{aid}.json").read_text())


# ── the life of one helper ──────────────────────────────────────────────────

def test_a_started_helper_is_a_running_run_log_with_its_chat_and_machine(tmp_path):
    e = env(tmp_path, meta={"a1": {"description": "Diagnose dashboard Docs search", "agentType": "general-purpose"}})
    fire(e, "start", hook_event_name="SubagentStart", agent_id="a1", agent_type="general-purpose")
    d = doc(e, "a1")
    assert d["job"] == "helper-a1" and d["kind"] == "helper"
    assert d["label"] == "Diagnose dashboard Docs search"  # from the meta file Claude Code writes at launch
    h = d["helper"]
    assert h["session"] == SESSION and h["chat"] == "fix the docs search" and h["machine"] == "macbook-pro"
    assert h["transcript"].endswith(f"{SESSION}/subagents/agent-a1.jsonl")
    run = d["runs"][-1]
    assert run["status"] == "running" and run["started_at"] == T0.isoformat() and run["finished_at"] is None


def test_the_agent_tool_result_names_a_helper_the_meta_file_had_not_named_yet(tmp_path):
    e = env(tmp_path)
    fire(e, "start", agent_id="a1", agent_type="general-purpose")
    assert doc(e, "a1")["label"] == "general-purpose"  # best we know at start
    fire(e, "launched", tool_name="Agent", tool_input={"description": "Fix gh_watch"},
         tool_response={"status": "async_launched", "agentId": "a1", "description": "Fix gh_watch"})
    assert doc(e, "a1")["label"] == "Fix gh_watch"
    assert doc(e, "a1")["runs"][-1]["status"] == "running"


def test_a_handback_report_becomes_the_summary_and_its_tickets_and_prs_become_links(tmp_path):
    e = env(tmp_path)
    fire(e, "start", agent_id="a1", agent_type="general-purpose")
    report = ("Filed G-Eskayo/marvin#612 and opened https://github.com/G-Eskayo/marvin/pull/613.\n\n"
              "Also see #609 and `#999 in code` and https://github.com/G-Eskayo/clarity-captions/issues/48")
    fire(e, "report", tool_name="SubagentHandback", agent_id="a1", tool_input={"message": report})
    assert doc(e, "a1")["runs"][-1]["status"] == "running"  # the report alone does not end it
    fire(e, "stop", now=T0 + timedelta(minutes=7), agent_id="a1", agent_type="general-purpose",
         last_assistant_message="")
    d = doc(e, "a1")
    run = d["runs"][-1]
    assert run["status"] == "passed" and run["finished_at"] == (T0 + timedelta(minutes=7)).isoformat()
    assert run["summary"].startswith("Filed G-Eskayo/marvin#612") and "\n" not in run["summary"]
    links = d["helper"]["links"]
    assert {"kind": "ticket", "repo": "G-Eskayo/marvin", "number": 612} in links
    assert {"kind": "pr", "repo": "G-Eskayo/marvin", "number": 613} in links
    assert {"kind": "ticket", "repo": "G-Eskayo/clarity-captions", "number": 48} in links
    # a bare #609 belongs to the repo the report itself names first; code spans are not references
    assert {"kind": "ticket", "repo": "G-Eskayo/marvin", "number": 609} in links
    assert not any(l["number"] == 999 for l in links)
    assert "report" not in d["helper"]  # the full report is not kept: the file stays small


def test_without_a_handback_the_last_message_is_the_result(tmp_path):
    e = env(tmp_path)
    fire(e, "start", agent_id="a1", agent_type="Explore")
    fire(e, "stop", agent_id="a1", agent_type="Explore", last_assistant_message="**Found it**: the index is stale.")
    run = doc(e, "a1")["runs"][-1]
    assert run["status"] == "passed" and run["summary"] == "Found it: the index is stale."


def test_a_helper_that_ends_with_no_result_at_all_is_failed(tmp_path):
    e = env(tmp_path)
    fire(e, "start", agent_id="a1", agent_type="general-purpose")
    fire(e, "stop", agent_id="a1", agent_type="general-purpose", last_assistant_message="   ")
    run = doc(e, "a1")["runs"][-1]
    assert run["status"] == "failed" and run["error"]


def test_a_foreground_result_arriving_after_the_stop_does_not_reopen_it(tmp_path):
    e = env(tmp_path)
    fire(e, "start", agent_id="a1", agent_type="general-purpose")
    fire(e, "stop", agent_id="a1", agent_type="general-purpose", last_assistant_message="done")
    fire(e, "launched", tool_name="Agent", tool_response={"status": "completed", "agentId": "a1", "content": []},
         tool_input={"description": "Quick look"})
    d = doc(e, "a1")
    assert d["runs"][-1]["status"] == "passed" and d["label"] == "Quick look"


def test_a_stop_with_no_start_still_records_the_helper(tmp_path):
    e = env(tmp_path)
    fire(e, "stop", agent_id="a1", agent_type="general-purpose", last_assistant_message="All good")
    run = doc(e, "a1")["runs"][-1]
    assert run["status"] == "passed" and run["summary"] == "All good"


def test_internal_agents_with_no_type_are_not_helpers(tmp_path):
    """/btw and prompt suggestions fire SubagentStop with agent_type "" (Claude Code docs): not a helper row."""
    e = env(tmp_path)
    fire(e, "start", agent_id="a1", agent_type="")
    fire(e, "stop", agent_id="a2", agent_type="", last_assistant_message="x")
    assert not e["jobs"].exists() or not list(e["jobs"].glob("helper-*.json"))


def test_the_agent_prefix_some_payloads_carry_is_the_same_helper(tmp_path):
    e = env(tmp_path)
    fire(e, "start", agent_id="agent-a1", agent_type="Explore")
    fire(e, "stop", agent_id="a1", agent_type="Explore", last_assistant_message="ok")
    assert [p.name for p in e["jobs"].glob("helper-*.json")] == ["helper-a1.json"]


# ── trying to break it ──────────────────────────────────────────────────────

def test_garbage_and_hostile_payloads_write_nothing_and_never_raise(tmp_path):
    e = env(tmp_path)
    for raw in ("", "not json", "[1,2]", "null", '{"agent_id": 5}', '{"agent_id": "../../etc/passwd", "agent_type": "x"}',
                '{"agent_id": "a/b", "agent_type": "x"}', '{"agent_id": "' + "a" * 500 + '", "agent_type": "x"}',
                json.dumps({"agent_id": "a1", "agent_type": "x", "transcript_path": 7, "session_id": {"x": 1}})):
        for event in ("start", "launched", "report", "stop", "bogus"):
            ch.handle(event, raw, jobs_dir=e["jobs"], sessions_path=e["sessions"], machine="m", now=T0)
    names = sorted(p.name for p in e["jobs"].glob("*.json")) if e["jobs"].exists() else []
    assert names in ([], ["helper-a1.json"])  # only the well-formed id with a bad transcript type got through
    assert not (tmp_path / "etc").exists()


def test_a_huge_report_is_cut_to_a_bounded_summary_and_link_list(tmp_path):
    e = env(tmp_path)
    fire(e, "start", agent_id="a1", agent_type="x")
    big = "x" * 300 + " " + " ".join(f"G-Eskayo/marvin#{n}" for n in range(1, 2000))
    fire(e, "stop", agent_id="a1", agent_type="x", last_assistant_message=big)
    d = doc(e, "a1")
    assert len(d["runs"][-1]["summary"]) <= ch.SUMMARY_CHARS
    assert len(d["helper"]["links"]) <= ch.MAX_LINKS
    assert (e["jobs"] / "helper-a1.json").stat().st_size < 8000


def test_a_corrupt_run_log_is_replaced_not_fatal(tmp_path):
    e = env(tmp_path)
    e["jobs"].mkdir(parents=True)
    (e["jobs"] / "helper-a1.json").write_text("{half")
    fire(e, "stop", agent_id="a1", agent_type="x", last_assistant_message="ok")
    assert doc(e, "a1")["runs"][-1]["status"] == "passed"


def test_two_helpers_at_once_each_keep_their_own_row(tmp_path):
    e = env(tmp_path)
    errors = []

    def life(aid):
        try:
            fire(e, "start", agent_id=aid, agent_type="x")
            for _ in range(5):
                fire(e, "launched", tool_response={"status": "async_launched", "agentId": aid, "description": f"job {aid}"})
            fire(e, "stop", agent_id=aid, agent_type="x", last_assistant_message=f"result {aid}")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=life, args=(f"a{i}",)) for i in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors
    for i in range(6):
        d = doc(e, f"a{i}")
        assert d["label"] == f"job a{i}" and d["runs"][-1]["summary"] == f"result a{i}" and len(d["runs"]) == 1


def test_retention_keeps_only_the_newest_helpers_but_never_a_live_one(tmp_path):
    e = env(tmp_path)
    fire(e, "start", now=T0, agent_id="old0", agent_type="x")  # still running, and its transcript is fresh
    Path(doc(e, "old0")["helper"]["transcript"]).write_text("{}\n")
    for i in range(1, ch.KEEP + 10):
        fire(e, "stop", now=T0 + timedelta(seconds=i), agent_id=f"h{i:03d}", agent_type="x", last_assistant_message="ok")
        past = time.time() - 86400 + i  # finished earlier than the live ones
        os.utime(e["jobs"] / f"helper-h{i:03d}.json", (past, past))
    fire(e, "start", now=T0 + timedelta(minutes=1), agent_id="new", agent_type="x")  # pruning runs on a start
    names = {p.name for p in e["jobs"].glob("helper-*.json")}
    assert "helper-old0.json" in names and "helper-new.json" in names
    assert len(names) <= ch.KEEP + 1
    assert "helper-h001.json" not in names and f"helper-h{ch.KEEP + 9:03d}.json" in names
    assert not [p for p in e["jobs"].glob(".helper-*.lock") if not (e["jobs"] / p.name[1:].replace(".lock", ".json")).exists()]


def test_a_killed_helper_is_stale_once_its_transcript_goes_quiet(tmp_path):
    """No stop event ever comes for a helper killed mid-run: it must not read "running" forever."""
    e = env(tmp_path)
    fire(e, "start", agent_id="a1", agent_type="x")
    d = doc(e, "a1")
    transcript = Path(d["helper"]["transcript"])
    transcript.write_text("{}\n")
    started = T0.timestamp()
    os.utime(transcript, (started + 60, started + 60))
    assert ch.state_of(d, now=started + 60 + ch.STALE_S - 1) == "running"
    assert ch.state_of(d, now=started + 60 + ch.STALE_S + 1) == "stale"
    transcript.unlink()  # no transcript at all: measured from the start
    assert ch.state_of(d, now=started + ch.STALE_S + 1) == "stale"


def _run_cli(home, stdin, *args):
    return subprocess.run([sys.executable, str(LIB / "chat_helpers.py"), "hook", *args], input=stdin,
                          capture_output=True, text=True, timeout=20, env={**os.environ, "HOME": str(home)})


def test_the_hook_exits_0_silently_on_garbage_and_with_no_logs_dir(tmp_path):
    home = tmp_path / "home"
    home.mkdir()  # no ~/.claude at all
    for stdin, event in (("garbage{", "start"), ("", "stop"), (json.dumps({"agent_id": "a1", "agent_type": "x"}), "start"),
                         ("{}", "nope")):
        p = _run_cli(home, stdin, event)
        assert p.returncode == 0 and p.stdout == "", (event, p.stdout, p.stderr)
    assert (home / ".claude" / "logs" / "jobs" / "helper-a1.json").exists()  # created the folder when it could
    p = _run_cli(home, "{}")  # no event named
    assert p.returncode == 0 and p.stdout == ""


def test_the_hook_exits_0_when_the_logs_dir_cannot_be_written(tmp_path):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "logs").write_text("a file where the folder should be")
    p = _run_cli(home, json.dumps({"agent_id": "a1", "agent_type": "x"}), "start")
    assert p.returncode == 0 and p.stdout == ""
