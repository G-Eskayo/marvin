"""Tests for bin/gh (the GitHub gate). Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_gh_gate.py -v
"""
from __future__ import annotations
import importlib.machinery
import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "bin" / "gh"

loader = importlib.machinery.SourceFileLoader("gh_gate", str(GATE))
spec = importlib.util.spec_from_loader("gh_gate", loader)
gg = importlib.util.module_from_spec(spec)
loader.exec_module(gg)

NOW = 1_800_000_000.0


# ── what kind of refusal ────────────────────────────────────────────────────

def test_recognises_the_two_kinds_of_github_refusal():
    assert gg.classify_refusal("GraphQL: API rate limit already exceeded for user ID 1.") == "hourly"
    assert gg.classify_refusal("HTTP 403: API rate limit exceeded for user ID 1.") == "hourly"
    assert gg.classify_refusal("You have exceeded a secondary rate limit. Please wait a few minutes") == "burst"
    assert gg.classify_refusal("HTTP 429: Too Many Requests") == "burst"
    assert gg.classify_refusal("abuse detection mechanism") == "burst"
    assert gg.classify_refusal("Unknown JSON field: stateReason") is None
    assert gg.classify_refusal("") is None


# ── who is calling ──────────────────────────────────────────────────────────

def test_launchd_jobs_are_background_except_the_webhook_that_serves_clicks():
    assert gg.priority_of({"XPC_SERVICE_NAME": "com.marvin.ticket-pipeline"}) == "background"
    assert gg.priority_of({"XPC_SERVICE_NAME": "com.marvin.dashboard-webhook"}) == "interactive"
    assert gg.priority_of({"XPC_SERVICE_NAME": "application.com.marvin.metrics.123"}) == "interactive"
    assert gg.priority_of({}) == "interactive"
    assert gg.priority_of({"XPC_SERVICE_NAME": "com.marvin.ticket-pipeline", "MARVIN_GH_PRIORITY": "interactive"}) == "interactive"


# ── the decision ────────────────────────────────────────────────────────────

def test_nothing_wrong_means_go():
    assert gg.decide("background", {}, {"core": 0.9, "graphql": 0.9}, NOW) == ("go", 0)


def test_a_cooldown_defers_background_and_makes_interactive_wait_briefly_or_fail_clearly():
    st = {"cooldown_until": NOW + 10, "reason": "burst"}
    assert gg.decide("background", st, None, NOW)[0] == "defer"
    assert gg.decide("interactive", st, None, NOW) == ("wait", 10)
    long = {"cooldown_until": NOW + 600, "reason": "hourly"}
    assert gg.decide("interactive", long, None, NOW)[0] == "refuse"


def test_a_low_budget_holds_background_work_back_for_people():
    assert gg.decide("background", {}, {"core": 0.9, "graphql": 0.15}, NOW)[0] == "defer"
    assert gg.decide("interactive", {}, {"core": 0.9, "graphql": 0.15}, NOW) == ("go", 0)
    assert gg.decide("background", {}, None, NOW) == ("go", 0)  # unknown budget never blocks


def test_cooldown_grows_with_repeated_burst_refusals_and_is_capped():
    st = {}
    first = gg.after_refusal(st, "burst", NOW, reset_at=None)
    assert first["cooldown_until"] == NOW + 60 and first["strikes"] == 1
    second = gg.after_refusal(first, "burst", NOW, reset_at=None)
    assert second["cooldown_until"] == NOW + 120
    many = {"strikes": 10}
    assert gg.after_refusal(many, "burst", NOW, reset_at=None)["cooldown_until"] == NOW + gg.MAX_COOLDOWN


def test_an_hourly_refusal_waits_for_githubs_reset_time():
    st = gg.after_refusal({}, "hourly", NOW, reset_at=NOW + 1500)
    assert st["cooldown_until"] == NOW + 1500 and st["reason"] == "hourly"


def test_success_clears_strikes():
    assert gg.after_success({"strikes": 3, "cooldown_until": NOW - 5}) == {"strikes": 0, "cooldown_until": NOW - 5}


# ── the real thing, against a fake gh ───────────────────────────────────────

def _fake_gh(tmp_path, stderr="", rc=0, stdout="ok"):
    d = tmp_path / "realbin"
    d.mkdir(exist_ok=True)
    f = d / "gh"
    f.write_text(f"#!/bin/sh\necho '{stdout}'\necho '{stderr}' >&2\nexit {rc}\n")
    f.chmod(f.stat().st_mode | stat.S_IEXEC)
    return d


def _run(tmp_path, realbin, *args, env_extra=None):
    env = {"PATH": f"{GATE.parent}:{realbin}:/usr/bin:/bin", "HOME": str(tmp_path), "GH_GATE_NO_BUDGET": "1", **(env_extra or {})}
    return subprocess.run([str(GATE), *args], capture_output=True, text=True, env=env, timeout=30)


def test_it_passes_calls_through_and_logs_them(tmp_path):
    p = _run(tmp_path, _fake_gh(tmp_path), "issue", "list")
    assert p.returncode == 0 and p.stdout.strip() == "ok"
    log = [json.loads(l) for l in (tmp_path / ".claude" / "logs" / "gh-calls.jsonl").read_text().splitlines()]
    assert log[-1]["cmd"] == "issue list" and log[-1]["rc"] == 0 and log[-1]["priority"] == "interactive"


def test_a_refusal_starts_a_cooldown_that_the_next_background_call_respects(tmp_path):
    real = _fake_gh(tmp_path, stderr="You have exceeded a secondary rate limit", rc=1)
    first = _run(tmp_path, real, "api", "x")
    assert first.returncode == 1 and "secondary rate limit" in first.stderr
    state = json.loads((tmp_path / ".claude" / "logs" / "gh-gate.json").read_text())
    assert state["reason"] == "burst" and state["strikes"] == 1
    second = _run(tmp_path, _fake_gh(tmp_path), "issue", "list", env_extra={"XPC_SERVICE_NAME": "com.marvin.ticket-pipeline"})
    assert second.returncode == gg.DEFERRED_RC and "gh-gate" in second.stderr and second.stdout == ""


def test_it_never_calls_itself(tmp_path):
    assert gg.find_real_gh(f"{GATE.parent}:{GATE.parent}:/nonexistent") in (None, "/opt/homebrew/bin/gh", "/usr/local/bin/gh")
