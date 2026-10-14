"""Tests for error_log.py (marvin#422: errors are never silent). Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_error_log.py -v
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

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import error_log as el  # noqa: E402

NOW = datetime(2026, 10, 14, 15, 0, tzinfo=timezone.utc)


def lines(p):
    return [json.loads(l) for l in Path(p).read_text().splitlines() if l.strip()]


# ── recording ───────────────────────────────────────────────────────────────

def test_record_writes_one_json_line_with_source_message_and_raw(tmp_path):
    p = tmp_path / "errors.jsonl"
    el.record("sync:pull", "pull failed", raw="fatal: Unable to create '/x/.git/index.lock': File exists.", path=p, now=NOW, machine="mac-mini")
    (e,) = lines(p)
    assert e == {"t": NOW.isoformat(), "machine": "mac-mini", "source": "sync:pull", "message": "pull failed",
                 "raw": "fatal: Unable to create '/x/.git/index.lock': File exists."}


def test_record_never_raises_even_when_the_log_cannot_be_written(tmp_path):
    el.record("x", "y", path=Path("/dev/null/nope/errors.jsonl"), now=NOW)  # no exception


def test_long_messages_and_raw_are_capped(tmp_path):
    p = tmp_path / "e.jsonl"
    el.record("x", "m" * 5000, raw="r" * 50000, path=p, now=NOW)
    (e,) = lines(p)
    assert len(e["message"]) <= el.MAX_MESSAGE and len(e["raw"]) <= el.MAX_RAW


def test_log_stays_bounded_under_an_error_storm(tmp_path, monkeypatch):
    p = tmp_path / "e.jsonl"
    monkeypatch.setattr(el, "MAX_LINES", 50)
    for i in range(400):
        el.record("storm", f"boom {i}", path=p, now=NOW)
    kept = lines(p)
    assert len(kept) <= 50 * 1.25
    assert kept[-1]["message"] == "boom 399"  # newest kept


def test_entries_older_than_30_days_are_dropped_when_trimming(tmp_path, monkeypatch):
    p = tmp_path / "e.jsonl"
    monkeypatch.setattr(el, "MAX_LINES", 5)
    el.record("old", "ancient", path=p, now=NOW - timedelta(days=40))
    for i in range(10):
        el.record("new", f"n{i}", path=p, now=NOW)
    assert all(e["source"] == "new" for e in lines(p))


def test_concurrent_writers_never_corrupt_lines(tmp_path):
    p = tmp_path / "e.jsonl"
    ts = [threading.Thread(target=lambda i=i: [el.record("t", f"{i}-{k}", path=p, now=NOW) for k in range(50)]) for i in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(lines(p)) == 300


# ── plain causes ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw, cause", [
    ("fatal: Unable to create '/Users/g/.agents/.git/index.lock': File exists.", "git is locked by a crashed command"),
    ("error connecting to api.github.com\ncheck your internet connection", "no network, or GitHub unreachable"),
    ("dial tcp: lookup api.github.com: no such host", "no network, or GitHub unreachable"),
    ("rebuild_and_install.sh: line 23: npm: command not found", "a job can't find a tool (its PATH is missing Homebrew)"),
    ("PermissionError: [Errno 1] Operation not permitted: '/Users/g/Library/Messages'", "macOS privacy blocked it (Full Disk Access)"),
    ("GraphQL: API rate limit exceeded for user", "GitHub rate limit"),
    ("OSError: [Errno 28] No space left on device", "the disk is full"),
    ("CONFLICT (content): Merge conflict in lib/x.py", "a merge conflict needs a person"),
])
def test_known_failures_get_a_plain_cause(raw, cause):
    assert el.classify(raw)["cause"] == cause


def test_unknown_failures_fall_back_to_their_first_line():
    c = el.classify("Something odd happened\nTraceback ...")
    assert c["cause"] == "Something odd happened" and c["known"] is False


# ── reading recent errors ───────────────────────────────────────────────────

def test_recent_folds_repeats_by_source_and_cause_newest_first(tmp_path):
    p = tmp_path / "e.jsonl"
    lock = "fatal: Unable to create '/x/.git/index.lock': File exists."
    for m in range(0, 120, 30):
        el.record("sync:pull", "pull failed", raw=lock, path=p, now=NOW - timedelta(minutes=m), machine="mini")
    el.record("dashboard:mr:list", "gh failed", raw="error connecting to api.github.com", path=p, now=NOW - timedelta(minutes=5), machine="book")
    groups = el.recent(path=p, now=NOW, hours=24)
    assert [g["source"] for g in groups] == ["sync:pull", "dashboard:mr:list"]
    g = groups[0]
    assert g["count"] == 4 and g["cause"] == "git is locked by a crashed command" and g["machine"] == "mini"
    assert g["last_t"] == NOW.isoformat() and g["first_t"] == (NOW - timedelta(minutes=90)).isoformat()


def test_recent_ignores_entries_outside_the_window_and_bad_lines(tmp_path):
    p = tmp_path / "e.jsonl"
    el.record("a", "old", path=p, now=NOW - timedelta(days=3))
    with open(p, "a") as f:
        f.write("{not json\n\n[]\n")
    el.record("b", "new", path=p, now=NOW)
    assert [g["source"] for g in el.recent(path=p, now=NOW, hours=24)] == ["b"]


def test_recent_on_a_missing_log_is_empty():
    assert el.recent(path=Path("/nope/e.jsonl"), now=NOW) == []


def test_severity_red_when_repeating_in_the_last_hour_amber_within_a_day():
    g = lambda count, mins: {"count": count, "last_t": (NOW - timedelta(minutes=mins)).isoformat()}
    assert el.severity(g(3, 10), NOW) == "red"
    assert el.severity(g(1, 10), NOW) == "amber"
    assert el.severity(g(5, 300), NOW) == "amber"


# ── fixes are logged as fixes ───────────────────────────────────────────────

def test_record_fix_is_marked_and_never_counts_as_an_error(tmp_path):
    p = tmp_path / "e.jsonl"
    el.record_fix("sync:pull", "removed a stale git lock", path=p, now=NOW)
    (e,) = lines(p)
    assert e["fix"] is True
    assert el.recent(path=p, now=NOW) == []
    assert el.recent(path=p, now=NOW, include_fixes=True)[0]["fix"] is True


# ── CLI (what bash scripts and other machines call) ─────────────────────────

def test_cli_record_and_recent_json(tmp_path, capsys, monkeypatch):
    p = tmp_path / "e.jsonl"
    monkeypatch.setattr(el, "PATH", p)
    assert el.main(["record", "--source", "rebuild", "--message", "build failed", "--raw", "npm: command not found"]) == 0
    assert el.main(["recent", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out[0]["source"] == "rebuild" and "PATH" in out[0]["cause"]


def test_a_failed_job_run_reaches_the_error_log(tmp_path, monkeypatch):
    import job_events
    monkeypatch.setattr(job_events, "JOBS_DIR", tmp_path / "jobs")
    with pytest.raises(RuntimeError):
        with job_events.job_run("nightly-thing", "Nightly thing"):
            raise RuntimeError("disk full")
    (g,) = el.recent(now=datetime.now(timezone.utc))
    assert g["source"] == "job:nightly-thing"
    assert ("failed" in g["message"]) or ("crashed" in g["message"])
    assert "disk full" in g["raw"]


def test_a_hook_error_reaches_the_error_log():
    import hook_errors
    hook_errors.log_hook_error("brain-map", "refresh", ValueError("bad json"))
    (g,) = el.recent(now=datetime.now(timezone.utc))
    assert g["source"] == "hook:brain-map" and "bad json" in g["raw"]


def test_the_rebuild_script_records_its_failure(tmp_path):
    # Run only the trap machinery from rebuild_and_install.sh, with a fake python that captures the call.
    src = (Path(__file__).resolve().parents[2] / "dashboard" / "scripts" / "rebuild_and_install.sh").read_text()
    head = src.split("cd \"$(dirname")[0]
    fake = tmp_path / ".agents" / "venv" / "bin"
    fake.mkdir(parents=True)
    (fake / "python").write_text('#!/bin/sh\necho "$@" > "$HOME/called"\n')
    (fake / "python").chmod(0o755)
    script = tmp_path / "s.sh"
    script.write_text(head + "\nfalse\n")
    r = subprocess.run(["bash", str(script)], env={**os.environ, "HOME": str(tmp_path)}, capture_output=True, text=True)
    assert r.returncode != 0
    called = (tmp_path / "called").read_text()
    assert "record --source rebuild" in called and "dashboard rebuild failed" in called
