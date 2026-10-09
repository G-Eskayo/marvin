"""Tests for session_work.py (sessions know what other sessions are working on, #326). Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_session_work.py -v
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import session_work as sw  # noqa: E402

T = 1_800_000_000.0


def git(cwd, *a):
    subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True)


def test_a_worktree_copy_and_the_main_checkout_are_the_same_file(tmp_path):
    main = tmp_path / "repo"
    main.mkdir()
    git(main, "init", "-q", "-b", "main"); git(main, "config", "user.email", "t@t"); git(main, "config", "user.name", "t")
    (main / "lib").mkdir(); (main / "lib" / "a.py").write_text("x\n")
    git(main, "add", "-A"); git(main, "commit", "-qm", "c")
    wt = tmp_path / "wt"
    git(main, "worktree", "add", "-q", str(wt))
    assert sw.file_key(str(main / "lib" / "a.py")) == sw.file_key(str(wt / "lib" / "a.py"))
    assert sw.file_key(str(main / "lib" / "a.py"))[1] == "lib/a.py"
    assert sw.file_key(str(tmp_path / "loose.txt")) == (None, str(tmp_path / "loose.txt"))


def test_another_live_session_editing_the_same_file_is_an_overlap():
    st = {}
    sw.record_prompt(st, "A", "fix the GitHub rate limit", T)
    sw.record_edit(st, "A", ("r", "lib/health_checks.py"), T)
    sw.record_prompt(st, "B", "add a gate for gh", T + 60)
    found = sw.overlaps(st, "B", ("r", "lib/health_checks.py"), T + 120)
    assert [o["session"] for o in found] == ["A"] and found[0]["request"] == "fix the GitHub rate limit"
    assert sw.overlaps(st, "B", ("r", "lib/other.py"), T + 120) == []
    assert sw.overlaps(st, "A", ("r", "lib/health_checks.py"), T + 120) == []  # your own edits are not an overlap


def test_a_session_quiet_for_45_minutes_no_longer_counts():
    st = {}
    sw.record_edit(st, "A", ("r", "x.py"), T)
    assert sw.overlaps(st, "B", ("r", "x.py"), T + 44 * 60)
    assert sw.overlaps(st, "B", ("r", "x.py"), T + 46 * 60) == []


def test_asked_once_per_file_per_pair_of_sessions():
    st = {}
    sw.record_edit(st, "A", ("r", "x.py"), T)
    first = sw.pre_edit(st, "B", ("r", "x.py"), T + 10)
    assert first and "x.py" in first and "A"[:1]
    assert sw.pre_edit(st, "B", ("r", "x.py"), T + 20) is None
    sw.record_edit(st, "C", ("r", "x.py"), T + 30)
    assert sw.pre_edit(st, "B", ("r", "x.py"), T + 40)  # a new session touching it asks again


def test_stale_sessions_are_pruned_so_the_file_stays_small():
    st = {}
    sw.record_edit(st, "old", ("r", "x.py"), T)
    sw.record_edit(st, "new", ("r", "y.py"), T + 5 * 3600)
    sw.prune(st, T + 5 * 3600)
    assert set(st["sessions"]) == {"new"}


def test_the_ticket_a_session_is_building_is_the_one_its_request_names():
    assert sw.ticket_in("yes build #318 now") == 318
    assert sw.ticket_in("build it") is None
    assert sw.ticket_in("compare #312 and #313") is None  # two tickets: not sure which, so no claim
    assert sw.ticket_in("PR 257 has a conflict") is None


def test_claim_is_offered_once_per_session_and_repo():
    st = {}
    sw.record_prompt(st, "A", "build #326", T)
    assert sw.claim_wanted(st, "A", "/repo") == 326
    assert sw.claim_wanted(st, "A", "/repo") is None


def test_hook_handlers_round_trip_through_the_state_file(tmp_path, monkeypatch):
    monkeypatch.setattr(sw, "STATE_PATH", tmp_path / "s.json")
    monkeypatch.setattr(sw, "_start_claim", lambda *a: None)
    sw.handle("prompt", {"session_id": "A", "prompt": "fix health checks", "cwd": str(tmp_path)}, now=T)
    sw.handle("post", {"session_id": "A", "tool_input": {"file_path": str(tmp_path / "h.py")}, "cwd": str(tmp_path)}, now=T + 1)
    out = sw.handle("pre", {"session_id": "B", "tool_input": {"file_path": str(tmp_path / "h.py")}, "cwd": str(tmp_path)}, now=T + 2)
    d = json.loads(out)["hookSpecificOutput"]
    assert d["hookEventName"] == "PreToolUse" and d["permissionDecision"] == "ask"
    assert "fix health checks" in d["permissionDecisionReason"]
    assert sw.handle("pre", {"session_id": "A", "tool_input": {"file_path": str(tmp_path / "h.py")}}, now=T + 3) is None


def test_a_broken_state_file_never_blocks_an_edit(tmp_path, monkeypatch):
    p = tmp_path / "s.json"
    p.write_text("{not json")
    monkeypatch.setattr(sw, "STATE_PATH", p)
    assert sw.handle("pre", {"session_id": "B", "tool_input": {"file_path": "/x"}}, now=T) is None
