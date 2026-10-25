"""Tests for brief_fallback.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_brief_fallback.py -v
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import brief_fallback as bf  # noqa: E402
import scanner_role  # noqa: E402


# ── Tests 1–5: _infer_remote_path ───────────────────────────────────────────────

def test_infer_remote_path_absolute_home_path():
    home = Path.home()
    path = home / ".claude" / "briefs" / "2026-10-24.md"
    rel, under_home = bf._infer_remote_path(path)
    assert under_home is True
    assert rel == ".claude/briefs/2026-10-24.md"
    assert "$HOME" not in rel  # unquoted


def test_infer_remote_path_relative_filename_fallback(tmp_path):
    filename = tmp_path / "brief.md"
    rel, under_home = bf._infer_remote_path(filename)
    assert under_home is False
    assert rel == "brief.md"


def test_infer_remote_path_handles_special_characters():
    home = Path.home()
    path = home / ".claude" / "file with spaces.md"
    rel, under_home = bf._infer_remote_path(path)
    assert under_home is True
    assert rel == ".claude/file with spaces.md"  # unquoted
    assert "$HOME" not in rel


def test_infer_remote_path_returns_tuple():
    home = Path.home()
    path = home / ".claude" / "briefs" / "2026-10-24.md"
    result = bf._infer_remote_path(path)
    assert isinstance(result, tuple)
    assert len(result) == 2
    assert isinstance(result[0], str)
    assert isinstance(result[1], bool)


def test_infer_remote_path_as_string_input():
    home = Path.home()
    path_str = str(home / ".claude" / "briefs" / "2026-10-24.md")
    rel, under_home = bf._infer_remote_path(path_str)
    assert under_home is True
    assert rel == ".claude/briefs/2026-10-24.md"


# ── Tests 6–10: _is_valid_content() and produced() ───────────────────────────

def test_is_valid_content_returns_true_for_nonempty():
    assert bf._is_valid_content("# Brief\n\nSome content") is True


def test_is_valid_content_returns_false_for_none():
    assert bf._is_valid_content(None) is False


def test_is_valid_content_returns_false_for_empty():
    assert bf._is_valid_content("") is False


def test_is_valid_content_returns_false_for_whitespace_only():
    assert bf._is_valid_content("   \n\n  ") is False


def test_is_valid_content_returns_false_for_failure_placeholder():
    assert bf._is_valid_content("some content (claude call failed: timeout) more") is False


# ── Tests 11–14: produced() ──────────────────────────────────────────────────────

def test_produced_returns_true_for_nonempty_file(tmp_path):
    path = tmp_path / "brief.md"
    path.write_text("# Brief\n\nSome content")
    assert bf.produced(path) is True


def test_produced_returns_false_for_empty_file(tmp_path):
    path = tmp_path / "brief.md"
    path.write_text("")
    assert bf.produced(path) is False


def test_produced_returns_false_for_failure_placeholder_file(tmp_path):
    path = tmp_path / "brief.md"
    path.write_text("(claude call failed: timeout)")
    assert bf.produced(path) is False


def test_produced_returns_false_for_missing_file(tmp_path):
    path = tmp_path / "brief.md"
    assert bf.produced(path) is False


# ── Tests 15–17: past_deadline() ─────────────────────────────────────────────────

def test_past_deadline_returns_true_when_past(tmp_path):
    now = datetime(2026, 10, 24, 10, 30)  # 10:30 AM
    assert bf.past_deadline(10, 0, now) is True


def test_past_deadline_returns_false_when_before(tmp_path):
    now = datetime(2026, 10, 24, 9, 30)  # 9:30 AM
    assert bf.past_deadline(10, 0, now) is False


def test_past_deadline_returns_true_at_exact_deadline():
    now = datetime(2026, 10, 24, 10, 0)  # 10:00 AM
    assert bf.past_deadline(10, 0, now) is True


# ── Tests 18–20: Decision ────────────────────────────────────────────────────────

def test_decision_namedtuple_has_required_fields():
    dec = bf.Decision(True, "test reason")
    assert dec.should_proceed is True
    assert dec.reason == "test reason"


def test_decision_unpacks():
    dec = bf.Decision(False, "not running")
    should, why = dec
    assert should is False
    assert why == "not running"


def test_decision_readable_repr():
    dec = bf.Decision(True, "primary: always runs")
    assert "Decision" in repr(dec)
    assert "should_proceed=True" in repr(dec)


# ── Tests 21–24: should_run() ────────────────────────────────────────────────────

def test_should_run_primary_always_returns_true(monkeypatch):
    monkeypatch.setattr(bf.machine_profile, "registry_id", lambda: "mac-mini-1")
    monkeypatch.setattr(bf.scanner_role, "is_primary", lambda x: True)

    result = bf.should_run("~/.claude/briefs/today.md")
    assert result.should_proceed is True
    assert "primary" in result.reason


def test_should_run_standby_waits_before_deadline(monkeypatch):
    monkeypatch.setattr(bf.machine_profile, "registry_id", lambda: "macbook-pro-1")
    monkeypatch.setattr(bf.scanner_role, "is_primary", lambda x: x.startswith("mac-mini"))

    # 9:00 AM, before 10:15 deadline — should return False before checking primary
    now = datetime(2026, 10, 24, 9, 0)  # naive datetime = local time
    result = bf.should_run("~/.claude/briefs/today.md", usual_hour=10, usual_minute=15, now=now)
    assert result.should_proceed is False
    assert "waiting" in result.reason


def test_should_run_standby_runs_after_deadline_if_primary_silent(monkeypatch):
    monkeypatch.setattr(bf.machine_profile, "registry_id", lambda: "macbook-pro-1")
    monkeypatch.setattr(bf.scanner_role, "is_primary", lambda x: x.startswith("mac-mini"))

    primary_info = {"tailscale_hostname": "mac-mini-main"}
    monkeypatch.setattr(bf.scanner_role, "_primary_device", lambda: ("mac-mini-1", primary_info))
    monkeypatch.setattr(bf.task_dispatch, "_tailscale_online_hosts", lambda: {"mac-mini-main"})
    monkeypatch.setattr(bf, "read_remote", lambda dev, path: None)

    # 10:30 AM, after 10:15 deadline, primary has not produced
    now = datetime(2026, 10, 24, 10, 30)  # naive datetime = local time
    result = bf.should_run("~/.claude/briefs/today.md", usual_hour=10, usual_minute=15, now=now)
    assert result.should_proceed is True
    assert "past" in result.reason


def test_should_run_standby_skips_if_primary_produced(monkeypatch):
    monkeypatch.setattr(bf.machine_profile, "registry_id", lambda: "macbook-pro-1")
    monkeypatch.setattr(bf.scanner_role, "is_primary", lambda x: x.startswith("mac-mini"))

    primary_info = {"tailscale_hostname": "mac-mini-main"}
    monkeypatch.setattr(bf.scanner_role, "_primary_device", lambda: ("mac-mini-1", primary_info))
    monkeypatch.setattr(bf.task_dispatch, "_tailscale_online_hosts", lambda: {"mac-mini-main"})
    # Primary has produced valid content
    monkeypatch.setattr(bf, "read_remote", lambda dev, path: "# Brief\n\nValid content")

    # 10:30 AM, after deadline, primary has produced
    now = datetime(2026, 10, 24, 10, 30)  # naive datetime = local time
    result = bf.should_run("~/.claude/briefs/today.md", usual_hour=10, usual_minute=15, now=now)
    assert result.should_proceed is False
    assert "primary has produced" in result.reason
