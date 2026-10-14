"""Tests for seal_beta_tickets.py (marvin#409). Uses tmp_path and fake `gh` executables on PATH.

Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_seal_beta_tickets.py -v
"""
from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import seal_beta_tickets as sbt  # noqa: E402

NOW = datetime(2026, 10, 13, 18, 0, tzinfo=timezone.utc)

# Minimal by_device entry matching summarize()'s shape.
DEVICE_TEMPLATE = {
    "device": "iPhone 15",
    "model_ids": ["iPhone15,4"],
    "conversations": 100,
    "reports": 5,
    "rated": 80,
    "skipped": 10,
    "unrated": 10,
    "median_rating": 8.0,
    "lag_p50": 0.1,
    "lag_p95": 0.5,
    "rewrite_rate": 0.05,
    "relabels_per_min": 0.2,
    "battery_drop_per_30min": 5.0,
    "max_thermal": "fair",
    "endings": {"userStop": 95, "appCrash": 3, "stuck": 0, "unknown": 2},
    "minutes_total": 1000.0,
    "low_sample": 0,
    "notes": [],
    "builds": [
        {"build": "3", "conversations": 50, "median_rating": 8.0, "lag_p95": 0.4, "endings": {"userStop": 48, "stuck": 0}},
    ],
}


def summary(by_device):
    """Wrap by_device list into a summary.json shape."""
    return {
        "generated_at": NOW.isoformat(),
        "totals": {"conversations": 100, "reports": 5, "devices": len(by_device)},
        "by_device": by_device,
        "by_build": [],
    }


@pytest.fixture
def paths(tmp_path):
    store = tmp_path / "seal-beta"
    store.mkdir()
    return store


@pytest.fixture
def fake_gh_ok(tmp_path, monkeypatch):
    """Fake `gh` executable that records calls and can be configured with responses."""
    calls = {"list": [], "create": [], "edit": [], "reopen": []}
    create_next_number = [100]  # mutable to increment
    created_issues = {}  # slug -> {"number": N, "body": "...", "state": "OPEN"} mapping

    original_run = subprocess.run

    def fake_run(cmd, *args, **kwargs):
        if cmd and cmd[0] == "gh":
            subcommand = cmd[1] if len(cmd) > 1 else None
            if subcommand == "issue" and len(cmd) > 2:
                action = cmd[2]
                if action == "list":
                    calls["list"].append(cmd)
                    # Parse the search term to find if we created this marker before
                    search_idx = next((i for i, v in enumerate(cmd) if v == "--search"), None)
                    if search_idx is not None and search_idx + 1 < len(cmd):
                        search_term = cmd[search_idx + 1]
                        # Search term is now the bare slug, not prefixed with "marvin:seal-beta:"
                        # Match created issues by constructing the full marker and searching body
                        for slug, issue in created_issues.items():
                            if slug == search_term:
                                return subprocess.CompletedProcess(cmd, 0, json.dumps([{
                                    "number": issue["number"],
                                    "body": issue["body"],
                                    "state": issue["state"]
                                }]), "")
                    return subprocess.CompletedProcess(cmd, 0, "[]", "")
                elif action == "create":
                    calls["create"].append(cmd)
                    number = create_next_number[0]
                    create_next_number[0] += 1
                    # Extract slug from body marker: "<!-- marvin:seal-beta:iphone-15-lag -->"
                    body_idx = next((i for i, v in enumerate(cmd) if v == "--body"), None)
                    if body_idx is not None and body_idx + 1 < len(cmd):
                        body = cmd[body_idx + 1]
                        match = re.search(r"<!-- marvin:seal-beta:([^:]+) -->", body)
                        if match:
                            slug = match.group(1)
                            created_issues[slug] = {"number": number, "body": body, "state": "OPEN"}
                    return subprocess.CompletedProcess(cmd, 0, f"https://github.com/test/repo/issues/{number}", "")
                elif action == "edit":
                    calls["edit"].append(cmd)
                    # Update body in the tracked issue
                    body_idx = next((i for i, v in enumerate(cmd) if v == "--body"), None)
                    if body_idx is not None and body_idx + 1 < len(cmd):
                        body = cmd[body_idx + 1]
                        match = re.search(r"<!-- marvin:seal-beta:([^:]+) -->", body)
                        if match:
                            slug = match.group(1)
                            if slug in created_issues:
                                created_issues[slug]["body"] = body
                    return subprocess.CompletedProcess(cmd, 0, "", "")
                elif action == "reopen":
                    calls["reopen"].append(cmd)
                    # Mark as open in the tracked issue
                    issue_num_idx = next((i for i, v in enumerate(cmd) if v.isdigit() and i > 2), None)
                    if issue_num_idx is not None:
                        for slug, issue in created_issues.items():
                            if issue["number"] == int(cmd[issue_num_idx]):
                                issue["state"] = "OPEN"
                                break
                    return subprocess.CompletedProcess(cmd, 0, "", "")
        return original_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", fake_run)
    return fake_run, calls


@pytest.fixture
def fake_gh_gate_fail(tmp_path, monkeypatch):
    """Fake `gh` that returns rc 75 (EX_TEMPFAIL) on search."""
    calls = {"list": [], "create": []}
    original_run = subprocess.run

    def fake_run(cmd, *args, **kwargs):
        if cmd and cmd[0] == "gh" and len(cmd) > 2 and cmd[1] == "issue":
            action = cmd[2]
            if action == "list":
                calls["list"].append(cmd)
                return subprocess.CompletedProcess(cmd, 75, "", "gh: rate limited or temporarily unavailable")
            elif action == "create":
                calls["create"].append(cmd)
                return subprocess.CompletedProcess(cmd, 0, "https://github.com/test/repo/issues/200", "")
        return original_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", fake_run)
    return fake_run, calls


# ── Tests ───────────────────────────────────────────────────────────────────

def test_detect_breaches_lag_p95_threshold(paths):
    dev = copy.deepcopy(DEVICE_TEMPLATE)
    dev["device"] = "iPhone 16"
    dev["lag_p95"] = 2.5  # > 2.0
    breaches = sbt.detect_breaches([dev])
    assert len(breaches) == 1
    assert breaches[0]["problem"] == "lag"
    assert breaches[0]["measurements"]["lag_p95"] == 2.5


def test_detect_breaches_stuck_ending(paths):
    dev = copy.deepcopy(DEVICE_TEMPLATE)
    dev["device"] = "iPhone 15 Pro"
    dev["endings"]["stuck"] = 5
    breaches = sbt.detect_breaches([dev])
    assert len(breaches) == 1
    assert breaches[0]["problem"] == "stuck"
    assert breaches[0]["measurements"]["stuck_count"] == 5


def test_detect_breaches_median_rating_threshold(paths):
    dev = copy.deepcopy(DEVICE_TEMPLATE)
    dev["device"] = "iPhone 14"
    dev["reports"] = 3  # >= 2
    dev["median_rating"] = 3.5  # <= 4
    breaches = sbt.detect_breaches([dev])
    assert len(breaches) == 1
    assert breaches[0]["problem"] == "rating"
    assert breaches[0]["measurements"]["median_rating"] == 3.5


def test_same_breach_on_a_later_run_updates_the_existing_ticket_not_a_duplicate(paths, fake_gh_ok):
    fake_run, calls = fake_gh_ok

    dev = copy.deepcopy(DEVICE_TEMPLATE)
    dev["device"] = "iPhone 15"
    dev["lag_p95"] = 3.0
    dev["builds"] = [{"build": "3", "lag_p95": 3.0}]

    # First run: files a new ticket.
    (paths / "summary.json").write_text(json.dumps(summary([dev])))
    st1 = sbt.run(store_dir=paths, run=fake_run)
    assert st1["tickets_filed"] == 1
    creates_1 = len(calls["create"])
    assert creates_1 == 1

    # Second run: same breach. Should find and update, not create.
    st2 = sbt.run(store_dir=paths, run=fake_run)
    assert st2["tickets_unchanged"] == 1
    creates_2 = len(calls["create"])
    assert creates_2 == 1, "should not have created a second ticket"


def test_a_note_with_a_name_or_phone_number_never_appears_in_the_rendered_ticket(paths):
    dev = copy.deepcopy(DEVICE_TEMPLATE)
    dev["device"] = "iPhone 17"
    dev["lag_p95"] = 3.0
    dev["notes"] = [{"build": "3", "note": "Alice called to say 555-1234"}]

    breaches = sbt.detect_breaches([dev])
    assert len(breaches) == 1
    body = sbt.render_body(breaches[0])

    assert "Alice" not in body
    assert "555-1234" not in body
    assert "notes" not in body.lower()


def test_gh_gate_refusal_stops_processing_at_first_deferred_error(paths, fake_gh_gate_fail):
    fake_run, calls = fake_gh_gate_fail

    dev = copy.deepcopy(DEVICE_TEMPLATE)
    dev["device"] = "iPhone 15"
    dev["lag_p95"] = 3.0

    (paths / "summary.json").write_text(json.dumps(summary([dev])))
    st1 = sbt.run(store_dir=paths, run=fake_run)

    # Should defer on first search failure.
    assert st1["tickets_deferred"] == 1
    assert len(calls["create"]) == 0


def test_empty_or_missing_summary_json_is_a_noop(paths, fake_gh_ok):
    fake_run, calls = fake_gh_ok

    # No summary.json yet.
    st = sbt.run(store_dir=paths, run=fake_run)
    assert st["ok"] and st["breaches_detected"] == 0
    assert len(calls["create"]) == 0

    # Corrupt summary.json.
    (paths / "summary.json").write_text("not valid json")
    st = sbt.run(store_dir=paths, run=fake_run)
    assert st["ok"] and st["breaches_detected"] == 0
    assert len(calls["create"]) == 0


def test_malformed_by_device_entries_are_skipped_not_crashed(paths):
    entries = [
        {"device": None},  # missing device
        {"device": "iPhone", "lag_p95": "not a number"},  # wrong type
        {"device": "iPhone", "endings": "not a dict"},  # endings not dict
        {"device": "iPhone", "reports": 3, "median_rating": float('nan')},  # NaN
        {"device": "iPhone"},  # missing reports
    ]
    breaches = sbt.detect_breaches(entries)
    assert len(breaches) == 0  # All skipped without crashing.


def test_a_huge_by_device_list_is_handled_and_capped(paths, fake_gh_ok):
    fake_run, calls = fake_gh_ok

    # 500 devices, 400 breaching (lag > 2).
    devices = []
    for i in range(500):
        dev = copy.deepcopy(DEVICE_TEMPLATE)
        dev["device"] = f"iPhone {i:03d}"
        if i < 400:
            dev["lag_p95"] = 3.0
        devices.append(dev)

    (paths / "summary.json").write_text(json.dumps(summary(devices)))
    st = sbt.run(store_dir=paths, run=fake_run)

    # Should be capped at MAX_BREACHES_PER_RUN.
    assert st["tickets_filed"] + st["tickets_updated"] + st["tickets_unchanged"] == sbt.MAX_BREACHES_PER_RUN
    # Remaining deferred for next run.
    assert st["cursor_next"] != 0 or st["breaches_detected"] == sbt.MAX_BREACHES_PER_RUN


def test_gh_create_failing_after_a_successful_search_is_not_fatal(paths, monkeypatch):
    original_run = subprocess.run
    calls = {"list": 0, "create": 0}

    def fake_run(cmd, *args, **kwargs):
        if cmd and cmd[0] == "gh" and len(cmd) > 2 and cmd[1] == "issue":
            action = cmd[2]
            if action == "list":
                calls["list"] += 1
                return subprocess.CompletedProcess(cmd, 0, "[]", "")
            elif action == "create":
                calls["create"] += 1
                return subprocess.CompletedProcess(cmd, 1, "", "error creating issue")
        return original_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", fake_run)

    dev = copy.deepcopy(DEVICE_TEMPLATE)
    dev["device"] = "iPhone 15"
    dev["lag_p95"] = 3.0

    (paths / "summary.json").write_text(json.dumps(summary([dev])))
    st = sbt.run(store_dir=paths, run=fake_run)

    assert st["tickets_failed"] == 1
    assert len(st["failed"]) == 1


def test_gh_edit_failing_on_an_existing_match_is_not_fatal(paths, monkeypatch):
    original_run = subprocess.run
    calls = {"list": 0, "edit": 0}

    def fake_run(cmd, *args, **kwargs):
        if cmd and cmd[0] == "gh" and len(cmd) > 2 and cmd[1] == "issue":
            action = cmd[2]
            if action == "list":
                calls["list"] += 1
                body = '<!-- marvin:seal-beta:iphone-15-lag -->'
                return subprocess.CompletedProcess(cmd, 0, json.dumps([{"number": 100, "body": body, "state": "OPEN"}]), "")
            elif action == "edit":
                calls["edit"] += 1
                return subprocess.CompletedProcess(cmd, 1, "", "error editing issue")
        return original_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", fake_run)

    dev = copy.deepcopy(DEVICE_TEMPLATE)
    dev["device"] = "iPhone 15"
    dev["lag_p95"] = 3.0

    (paths / "summary.json").write_text(json.dumps(summary([dev])))
    st = sbt.run(store_dir=paths, run=fake_run)

    assert st["tickets_failed"] == 1


def test_store_dir_entirely_absent_is_handled(tmp_path, fake_gh_ok):
    fake_run, calls = fake_gh_ok

    missing_store = tmp_path / "nonexistent"
    st = sbt.run(store_dir=missing_store, run=fake_run)

    assert st["ok"]
    assert st["breaches_detected"] == 0
    assert len(calls["create"]) == 0


def test_concurrent_runs_never_double_file_the_same_breach(paths, monkeypatch):
    """Mirrors test_seal_beta_ingest.py's concurrency pattern."""
    original_run = subprocess.run
    call_lock = threading.Lock()
    created_issues = {}  # slug -> {"number": N, "body": "...", "state": "OPEN"}

    def fake_run(cmd, *args, **kwargs):
        if cmd and cmd[0] == "gh" and len(cmd) > 2 and cmd[1] == "issue":
            action = cmd[2]
            if action == "list":
                search_idx = next((i for i, v in enumerate(cmd) if v == "--search"), None)
                if search_idx is not None and search_idx + 1 < len(cmd):
                    search_term = cmd[search_idx + 1]
                    if search_term in created_issues:
                        issue = created_issues[search_term]
                        return subprocess.CompletedProcess(cmd, 0, json.dumps([{
                            "number": issue["number"],
                            "body": issue["body"],
                            "state": issue["state"]
                        }]), "")
                return subprocess.CompletedProcess(cmd, 0, "[]", "")
            elif action == "create":
                with call_lock:
                    body_idx = next((i for i, v in enumerate(cmd) if v == "--body"), None)
                    number = 100
                    if body_idx is not None and body_idx + 1 < len(cmd):
                        body = cmd[body_idx + 1]
                        match = re.search(r"<!-- marvin:seal-beta:([^:]+) -->", body)
                        if match:
                            slug = match.group(1)
                            if slug not in created_issues:
                                number = 100 + len(created_issues)
                                created_issues[slug] = {"number": number, "body": body, "state": "OPEN"}
                            else:
                                number = created_issues[slug]["number"]
                    return subprocess.CompletedProcess(cmd, 0, f"https://github.com/test/repo/issues/{number}", "")
        return original_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", fake_run)

    dev = copy.deepcopy(DEVICE_TEMPLATE)
    dev["device"] = "iPhone 15"
    dev["lag_p95"] = 3.0

    (paths / "summary.json").write_text(json.dumps(summary([dev])))

    # 6 threads all calling run() concurrently.
    def thread_func():
        sbt.run(store_dir=paths, run=fake_run)

    threads = [threading.Thread(target=thread_func) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Should only create once across all threads.
    assert len(created_issues) == 1


def test_an_exact_device_name_that_is_a_prefix_of_another_never_cross_matches(paths, fake_gh_ok):
    fake_run, calls = fake_gh_ok

    devices = [
        copy.deepcopy(DEVICE_TEMPLATE) | {"device": "iPhone 15", "lag_p95": 3.0},
        copy.deepcopy(DEVICE_TEMPLATE) | {"device": "iPhone 15 Pro", "lag_p95": 3.0},
        copy.deepcopy(DEVICE_TEMPLATE) | {"device": "iPhone 15 Pro Max", "lag_p95": 3.0},
    ]

    (paths / "summary.json").write_text(json.dumps(summary(devices)))
    st = sbt.run(store_dir=paths, run=fake_run)

    assert st["tickets_filed"] == 3  # Three separate tickets.


def test_gil_renaming_the_ticket_title_does_not_break_the_marker_match(paths, monkeypatch):
    original_run = subprocess.run
    calls = {"list": 0, "edit": 0}

    def fake_run(cmd, *args, **kwargs):
        if cmd and cmd[0] == "gh" and len(cmd) > 2 and cmd[1] == "issue":
            action = cmd[2]
            if action == "list":
                calls["list"] += 1
                body = '<!-- marvin:seal-beta:iphone-15-lag -->'
                return subprocess.CompletedProcess(cmd, 0, json.dumps([{"number": 100, "body": body, "state": "OPEN"}]), "")
            elif action == "edit":
                calls["edit"] += 1
                return subprocess.CompletedProcess(cmd, 0, "", "")
        return original_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", fake_run)

    dev = copy.deepcopy(DEVICE_TEMPLATE)
    dev["device"] = "iPhone 15"
    dev["lag_p95"] = 3.0

    (paths / "summary.json").write_text(json.dumps(summary([dev])))
    st = sbt.run(store_dir=paths, run=fake_run)

    assert st["tickets_updated"] == 1
    assert calls["edit"] == 1


def test_a_ticket_closed_by_gil_and_the_breach_recurring_follows_the_shipped_default(paths, monkeypatch):
    """Exercises reopening a closed ticket."""
    original_run = subprocess.run
    calls = {"reopen": 0}

    def fake_run(cmd, *args, **kwargs):
        if cmd and cmd[0] == "gh" and len(cmd) > 2 and cmd[1] == "issue":
            action = cmd[2]
            if action == "list":
                body = '<!-- marvin:seal-beta:iphone-15-lag -->'
                return subprocess.CompletedProcess(cmd, 0, json.dumps([{"number": 100, "body": body, "state": "CLOSED"}]), "")
            elif action == "edit":
                return subprocess.CompletedProcess(cmd, 0, "", "")
            elif action == "reopen":
                calls["reopen"] += 1
                return subprocess.CompletedProcess(cmd, 0, "", "")
        return original_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", fake_run)

    dev = copy.deepcopy(DEVICE_TEMPLATE)
    dev["device"] = "iPhone 15"
    dev["lag_p95"] = 3.0

    (paths / "summary.json").write_text(json.dumps(summary([dev])))
    st = sbt.run(store_dir=paths, run=fake_run)

    assert st["tickets_updated"] == 1
    assert calls["reopen"] == 1  # Should have reopened the closed ticket.


def test_gh_not_authenticated_is_treated_as_an_ordinary_dependency_failure(paths, monkeypatch):
    original_run = subprocess.run

    def fake_run(cmd, *args, **kwargs):
        if cmd and cmd[0] == "gh":
            return subprocess.CompletedProcess(cmd, 1, "", "gh: To use GitHub CLI, please run `gh auth login`")
        return original_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", fake_run)

    dev = copy.deepcopy(DEVICE_TEMPLATE)
    dev["device"] = "iPhone 15"
    dev["lag_p95"] = 3.0

    (paths / "summary.json").write_text(json.dumps(summary([dev])))
    st = sbt.run(store_dir=paths, run=fake_run)

    assert st["tickets_failed"] == 1


def test_a_breach_that_stops_breaching_is_left_alone(paths, fake_gh_ok):
    """A device that was breaching before now has clean numbers; no gh calls."""
    fake_run, calls = fake_gh_ok

    dev = copy.deepcopy(DEVICE_TEMPLATE)
    dev["device"] = "iPhone 15"
    dev["lag_p95"] = 0.5  # Below threshold, clean.

    (paths / "summary.json").write_text(json.dumps(summary([dev])))
    st = sbt.run(store_dir=paths, run=fake_run)

    assert st["breaches_detected"] == 0
    assert len(calls["create"]) == 0
    assert len(calls["list"]) == 0


def test_safe_text_strips_control_chars_and_neutralizes_markers(paths):
    """_safe_text() should remove control chars, neutralize HTML comment markers, and strip backticks."""
    assert sbt._safe_text("hello\x00world") == "helloworld"
    assert sbt._safe_text("test-->comment") == "test--comment"
    assert sbt._safe_text("<!--comment") == "comment"
    assert sbt._safe_text("hello`world`test") == "helloworldtest"
    assert sbt._safe_text("x" * 300, max_len=100) == "x" * 100


def test_round_robin_cursor_advances_across_multiple_runs(paths, fake_gh_ok):
    """cursor_next should allow fair distribution across large breach lists."""
    fake_run, calls = fake_gh_ok

    # Create 50 breaching devices.
    devices = []
    for i in range(50):
        dev = copy.deepcopy(DEVICE_TEMPLATE)
        dev["device"] = f"Device {i:02d}"
        dev["lag_p95"] = 3.0
        devices.append(dev)

    (paths / "summary.json").write_text(json.dumps(summary(devices)))

    # First run should process up to MAX_BREACHES_PER_RUN.
    st1 = sbt.run(store_dir=paths, run=fake_run)
    assert st1["tickets_filed"] == sbt.MAX_BREACHES_PER_RUN
    cursor1 = st1.get("cursor_next", 0)
    creates_after_1 = len(calls["create"])

    # Second run should start from cursor1 and process another batch.
    calls["create"].clear()
    st2 = sbt.run(store_dir=paths, run=fake_run)
    assert st2["tickets_filed"] + st2["tickets_updated"] + st2["tickets_unchanged"] == sbt.MAX_BREACHES_PER_RUN
    assert len(calls["create"]) == sbt.MAX_BREACHES_PER_RUN  # All new, no existing yet.
    assert st2["cursor_next"] != cursor1  # Cursor should have advanced.


def test_identical_ticket_body_skips_update(paths, monkeypatch):
    """When body is identical and state is OPEN, should mark unchanged."""
    original_run = subprocess.run
    calls = {"edit": 0}

    # First, generate the exact body that will be created
    dev = copy.deepcopy(DEVICE_TEMPLATE)
    dev["device"] = "iPhone 15"
    dev["lag_p95"] = 3.0
    dev["reports"] = 5
    breaches = sbt.detect_breaches([dev])
    expected_body = sbt.render_body(breaches[0])

    def fake_run(cmd, *args, **kwargs):
        if cmd and cmd[0] == "gh" and len(cmd) > 2 and cmd[1] == "issue":
            action = cmd[2]
            if action == "list":
                return subprocess.CompletedProcess(cmd, 0, json.dumps([{"number": 100, "body": expected_body, "state": "OPEN"}]), "")
            elif action == "edit":
                calls["edit"] += 1
                return subprocess.CompletedProcess(cmd, 0, "", "")
        return original_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", fake_run)

    (paths / "summary.json").write_text(json.dumps(summary([dev])))
    st = sbt.run(store_dir=paths, run=fake_run)

    assert st["tickets_unchanged"] == 1
    assert calls["edit"] == 0  # Should not have called edit.


def test_dry_run_defers_all_breaches(paths, fake_gh_ok):
    """With dry_run=True, all breaches should be deferred without gh calls."""
    fake_run, calls = fake_gh_ok

    dev = copy.deepcopy(DEVICE_TEMPLATE)
    dev["device"] = "iPhone 15"
    dev["lag_p95"] = 3.0

    (paths / "summary.json").write_text(json.dumps(summary([dev])))
    st = sbt.run(store_dir=paths, run=fake_run, dry_run=True)

    assert st["tickets_deferred"] == 1
    assert st["tickets_filed"] == 0
    assert len(calls["create"]) == 0
    assert len(calls["list"]) == 0


def test_non_dict_summary_json_is_a_noop(paths, fake_gh_ok):
    """Non-dict top-level JSON should be treated as missing/corrupt."""
    fake_run, calls = fake_gh_ok

    (paths / "summary.json").write_text(json.dumps([]))  # Array, not dict
    st = sbt.run(store_dir=paths, run=fake_run)

    assert st["ok"]
    assert st["breaches_detected"] == 0
    assert len(calls["create"]) == 0


def test_non_list_by_device_is_a_noop(paths, fake_gh_ok):
    """Non-list by_device in summary should be treated as missing/corrupt."""
    fake_run, calls = fake_gh_ok

    (paths / "summary.json").write_text(json.dumps({"by_device": {}}))  # dict, not list
    st = sbt.run(store_dir=paths, run=fake_run)

    assert st["ok"]
    assert st["breaches_detected"] == 0
    assert len(calls["create"]) == 0


def test_control_chars_in_device_name_are_sanitized(paths, fake_gh_ok):
    """Device names with control chars should be sanitized in ticket."""
    fake_run, calls = fake_gh_ok

    dev = copy.deepcopy(DEVICE_TEMPLATE)
    dev["device"] = "iPhone\x00Pwned"
    dev["lag_p95"] = 3.0

    (paths / "summary.json").write_text(json.dumps(summary([dev])))
    st = sbt.run(store_dir=paths, run=fake_run)

    assert st["tickets_filed"] == 1
    # Check that the body was sanitized
    created_body = None
    for call in calls["create"]:
        body_idx = next((i for i, v in enumerate(call) if v == "--body"), None)
        if body_idx is not None and body_idx + 1 < len(call):
            created_body = call[body_idx + 1]
    assert created_body and "\x00" not in created_body


def test_body_with_different_line_endings_normalizes_correctly(paths, monkeypatch):
    """Windows-style line endings should be normalized before comparison."""
    original_run = subprocess.run
    calls = {"edit": 0}

    # Create body with Unix line endings
    dev = copy.deepcopy(DEVICE_TEMPLATE)
    dev["device"] = "iPhone 15"
    dev["lag_p95"] = 3.0
    dev["reports"] = 5
    breaches = sbt.detect_breaches([dev])
    unix_body = sbt.render_body(breaches[0])

    # Return a version with Windows line endings
    windows_body = unix_body.replace("\n", "\r\n")

    def fake_run(cmd, *args, **kwargs):
        if cmd and cmd[0] == "gh" and len(cmd) > 2 and cmd[1] == "issue":
            action = cmd[2]
            if action == "list":
                return subprocess.CompletedProcess(cmd, 0, json.dumps([{"number": 100, "body": windows_body, "state": "OPEN"}]), "")
            elif action == "edit":
                calls["edit"] += 1
                return subprocess.CompletedProcess(cmd, 0, "", "")
        return original_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", fake_run)

    (paths / "summary.json").write_text(json.dumps(summary([dev])))
    st = sbt.run(store_dir=paths, run=fake_run)

    assert st["tickets_unchanged"] == 1
    assert calls["edit"] == 0  # Should not have called edit due to normalization.


def test_backticks_in_device_name_are_removed(paths, fake_gh_ok):
    """Device names with backticks should have them stripped."""
    fake_run, calls = fake_gh_ok

    dev = copy.deepcopy(DEVICE_TEMPLATE)
    dev["device"] = "iPhone `15` Pro"
    dev["lag_p95"] = 3.0

    (paths / "summary.json").write_text(json.dumps(summary([dev])))
    st = sbt.run(store_dir=paths, run=fake_run)

    assert st["tickets_filed"] == 1
    # Check that backticks were removed
    created_body = None
    for call in calls["create"]:
        body_idx = next((i for i, v in enumerate(call) if v == "--body"), None)
        if body_idx is not None and body_idx + 1 < len(call):
            created_body = call[body_idx + 1]
    # Should not contain backticks in the device name
    assert created_body and "`" not in created_body
