"""The code-sync launchd job's schedule, as a repo-tracked template.

Found 2026-10-01: the sync plists were not in the repo and had drifted between
machines (the laptop's pushed only ~/.agents, the mini's pushed both), and ADR 0021's
design had NO scheduled pull at all -- pulls happened only at Claude session start,
pushes once a day at 22:00 -- so "autonomous parity" meant up to a day of drift and a
laptop that never pulled unless a session started on it. One tracked template,
installed identically on both machines, makes the schedule reproducible.
"""
from __future__ import annotations
import plistlib
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[1] / "launchd" / "com.marvin.code-sync-push.plist"


def _plist():
    raw = TEMPLATE.read_text().replace("__HOME__", "/Users/test")
    return plistlib.loads(raw.encode())


def _command():
    args = _plist()["ProgramArguments"]
    assert args[:2] == ["/bin/bash", "-c"]
    return args[2]


def test_label_is_unchanged_so_health_coverage_and_log_paths_keep_working():
    p = _plist()
    assert p["Label"] == "com.marvin.code-sync-push"
    assert p["StandardOutPath"].endswith("/.claude/logs/code-sync-push.log")


def test_runs_every_30_minutes_and_at_load_not_once_a_day():
    p = _plist()
    assert p["StartInterval"] == 1800
    assert p["RunAtLoad"] is True
    assert "StartCalendarInterval" not in p


def test_pulls_then_pushes_both_synced_repos_in_a_fixed_order():
    cmd = _command()
    steps = [s.strip() for s in cmd.split(";")]
    expected = [
        ("pull", "/Users/test/.agents"), ("push", "/Users/test/.agents"),
        ("pull", "/Users/test/.claude"), ("push", "/Users/test/.claude"),
    ]
    assert len(steps) == 4
    for step, (action, repo) in zip(steps, expected):
        assert f"code_sync.py {action} {repo}" in step


def test_steps_are_independent_so_one_failure_cannot_skip_the_others():
    assert "&&" not in _command()


def test_environment_has_git_and_the_venv_on_path():
    env = _plist()["EnvironmentVariables"]
    assert env["HOME"] == "/Users/test"
    assert "/usr/bin" in env["PATH"] and "/Users/test/.agents/venv/bin" in env["PATH"]
