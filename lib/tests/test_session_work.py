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


def test_load_state_reads_a_valid_state_file(tmp_path, monkeypatch):
    """load_state() correctly reads a valid state file."""
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"sessions": {"A": {"request": "test", "last": T, "files": {}}}}))
    monkeypatch.setattr(sw, "STATE_PATH", p)
    st = sw.load_state()
    assert st["sessions"]["A"]["request"] == "test"


def test_load_state_fails_open_on_missing_file(tmp_path, monkeypatch):
    """load_state() returns empty dict when state file is missing."""
    p = tmp_path / "s.json"
    monkeypatch.setattr(sw, "STATE_PATH", p)
    assert sw.load_state() == {}


def test_load_state_fails_open_on_corrupt_file(tmp_path, monkeypatch):
    """load_state() returns empty dict when state file is not valid JSON."""
    p = tmp_path / "s.json"
    p.write_text("{not json")
    monkeypatch.setattr(sw, "STATE_PATH", p)
    assert sw.load_state() == {}


def test_load_state_rejects_non_dict_json(tmp_path, monkeypatch):
    """load_state() returns empty dict when state file is valid JSON but not a dict."""
    p = tmp_path / "s.json"
    p.write_text(json.dumps([1, 2, 3]))
    monkeypatch.setattr(sw, "STATE_PATH", p)
    assert sw.load_state() == {}


def test_live_edits_for_returns_matching_edits_when_both_session_and_file_are_fresh(tmp_path, monkeypatch):
    """live_edits_for() returns edits when both session last and file timestamp are within LIVE_S."""
    p = tmp_path / "s.json"
    p.write_text(json.dumps({
        "sessions": {
            "A": {
                "request": "fix something",
                "last": T + 30,
                "files": {sw._k(("repo-id", "file.md")): T + 20}
            }
        }
    }))
    monkeypatch.setattr(sw, "STATE_PATH", p)
    result = sw.live_edits_for("repo-id", ["file.md"], now=T + 100)
    assert len(result) == 1
    assert result[0]["session"] == "A"
    assert result[0]["path"] == "file.md"
    assert result[0]["request"] == "fix something"


def test_live_edits_for_session_fresh_but_file_edit_stale_does_not_match(tmp_path, monkeypatch):
    """live_edits_for() must-fix #1: session is still live (last within LIVE_S) but the file's
    own edit is stale (older than LIVE_S) — the file should not hold the lease."""
    p = tmp_path / "s.json"
    stale_edit = T  # Very old edit
    fresh_session = T + (sw.LIVE_S - 60)  # Session was active recently
    p.write_text(json.dumps({
        "sessions": {
            "A": {
                "request": "working on something else",
                "last": fresh_session,
                "files": {sw._k(("repo-id", "file.md")): stale_edit}
            }
        }
    }))
    monkeypatch.setattr(sw, "STATE_PATH", p)
    result = sw.live_edits_for("repo-id", ["file.md"], now=T + (sw.LIVE_S + 60))
    assert result == []


def test_live_edits_for_malformed_session_value_is_skipped_not_raised(tmp_path, monkeypatch):
    """live_edits_for() must-fix #2: a session value that isn't a dict is skipped.
    A well-formed sibling session's real lease still comes through."""
    p = tmp_path / "s.json"
    p.write_text(json.dumps({
        "sessions": {
            "broken": "not a dict",
            "good": {
                "request": "working",
                "last": T + 30,
                "files": {sw._k(("repo-id", "file.md")): T + 20}
            }
        }
    }))
    monkeypatch.setattr(sw, "STATE_PATH", p)
    result = sw.live_edits_for("repo-id", ["file.md"], now=T + 100)
    assert len(result) == 1
    assert result[0]["session"] == "good"


def test_live_edits_for_null_request_is_skipped_not_raised(tmp_path, monkeypatch):
    """live_edits_for() must-fix #2: a session with null request is skipped.
    A well-formed sibling session's real lease still comes through."""
    p = tmp_path / "s.json"
    p.write_text(json.dumps({
        "sessions": {
            "broken": {
                "request": None,
                "last": T + 30,
                "files": {sw._k(("repo-id", "file.md")): T + 20}
            },
            "good": {
                "request": "working",
                "last": T + 30,
                "files": {sw._k(("repo-id", "file.md")): T + 20}
            }
        }
    }))
    monkeypatch.setattr(sw, "STATE_PATH", p)
    result = sw.live_edits_for("repo-id", ["file.md"], now=T + 100)
    assert len(result) == 1
    assert result[0]["session"] == "good"


def test_live_edits_for_non_numeric_last_is_skipped_not_raised(tmp_path, monkeypatch):
    """live_edits_for() must-fix #2: a session with non-numeric last is skipped.
    A well-formed sibling session's real lease still comes through."""
    p = tmp_path / "s.json"
    p.write_text(json.dumps({
        "sessions": {
            "broken": {
                "request": "working",
                "last": "not a number",
                "files": {sw._k(("repo-id", "file.md")): T + 20}
            },
            "good": {
                "request": "working",
                "last": T + 30,
                "files": {sw._k(("repo-id", "file.md")): T + 20}
            }
        }
    }))
    monkeypatch.setattr(sw, "STATE_PATH", p)
    result = sw.live_edits_for("repo-id", ["file.md"], now=T + 100)
    assert len(result) == 1
    assert result[0]["session"] == "good"


def test_live_edits_for_non_numeric_file_timestamp_is_skipped_not_raised(tmp_path, monkeypatch):
    """live_edits_for() must-fix #2: a file with non-numeric timestamp is skipped.
    A well-formed sibling session's real lease still comes through."""
    p = tmp_path / "s.json"
    p.write_text(json.dumps({
        "sessions": {
            "broken": {
                "request": "working",
                "last": T + 30,
                "files": {sw._k(("repo-id", "file.md")): "not a number"}
            },
            "good": {
                "request": "working",
                "last": T + 30,
                "files": {sw._k(("repo-id", "file.md")): T + 20}
            }
        }
    }))
    monkeypatch.setattr(sw, "STATE_PATH", p)
    result = sw.live_edits_for("repo-id", ["file.md"], now=T + 100)
    assert len(result) == 1
    assert result[0]["session"] == "good"


def test_live_edits_for_two_live_sessions_both_hold_the_lease(tmp_path, monkeypatch):
    """live_edits_for() returns all matching sessions when two or more are live."""
    p = tmp_path / "s.json"
    p.write_text(json.dumps({
        "sessions": {
            "A": {
                "request": "work A",
                "last": T + 30,
                "files": {sw._k(("repo-id", "file.md")): T + 20}
            },
            "B": {
                "request": "work B",
                "last": T + 25,
                "files": {sw._k(("repo-id", "file.md")): T + 15}
            }
        }
    }))
    monkeypatch.setattr(sw, "STATE_PATH", p)
    result = sw.live_edits_for("repo-id", ["file.md"], now=T + 100)
    assert len(result) == 2
    sessions = {r["session"] for r in result}
    assert sessions == {"A", "B"}
