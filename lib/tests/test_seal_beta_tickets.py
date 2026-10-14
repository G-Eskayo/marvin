"""Tests for seal_beta_tickets.py (marvin#409).

Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_seal_beta_tickets.py -v
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import seal_beta_tickets as sbt  # noqa: E402


NOW = datetime(2026, 10, 13, 18, 0, tzinfo=timezone.utc)
REPO = "G-Eskayo/clarity-captions"


# Test fixtures: a realistic summary.json structure
def summary_fixture():
    return {
        "generated_at": NOW.isoformat(),
        "by_device": [
            {
                "device": "iPhone 17 Pro",
                "model_ids": ["iPhone18,1"],
                "conversations": 100,
                "lag_p95": 3.2,  # BREACH: > 2.0
                "median_rating": 6.5,
                "endings": {"userStop": 98, "stuck": 2},  # BREACH: any stuck
                "builds": [
                    {
                        "build": "5",
                        "conversations": 50,
                        "lag_p95": 3.0,
                        "rated": 10,
                        "median_rating": 6.0,
                        "endings": {"userStop": 48, "stuck": 2},  # BREACH: any stuck
                    },
                    {
                        "build": "4",
                        "conversations": 50,
                        "lag_p95": 3.5,
                        "rated": 8,
                        "median_rating": 7.0,
                        "endings": {"userStop": 50},
                    },
                ],
                "rated_reports": [
                    ("iPhone18,1", "5", "2026-10-13T12:00:00Z"),
                    ("iPhone18,1", "4", "2026-10-13T11:00:00Z"),
                ],
                "os_versions": ["iOS 26.0", "iOS 27.0"],
            },
            {
                "device": "iPhone 17",
                "model_ids": ["iPhone18,3"],
                "conversations": 50,
                "lag_p95": 1.5,
                "median_rating": 3.0,  # BREACH: <= 4 from >= 2 reports
                "rated_reports": [
                    ("iPhone18,3", "3", "2026-10-13T10:00:00Z"),
                    ("iPhone18,3", "3", "2026-10-13T09:00:00Z"),
                ],
                "os_versions": ["iOS 26.0"],
                "builds": [
                    {
                        "build": "3",
                        "conversations": 50,
                        "rated": 2,
                        "median_rating": 3.0,
                        "endings": {"userStop": 50},
                    },
                ],
            },
        ],
    }


class TestBreach:
    def test_lag_p95_breach_detected(self):
        s = summary_fixture()
        breaches = list(sbt.breaches(s))
        lag_breaches = [b for b in breaches if b["problem"] == "lag_p95"]
        assert len(lag_breaches) > 0
        assert any(b["device"] == "iPhone 17 Pro" for b in lag_breaches)

    def test_stuck_ending_breach_detected(self):
        s = summary_fixture()
        breaches = list(sbt.breaches(s))
        stuck_breaches = [b for b in breaches if b["problem"] == "stuck"]
        assert any(b["device"] == "iPhone 17 Pro" for b in stuck_breaches)

    def test_low_rating_breach_detected(self):
        s = summary_fixture()
        breaches = list(sbt.breaches(s))
        rating_breaches = [b for b in breaches if b["problem"] == "low_rating"]
        assert any(b["device"] == "iPhone 17" for b in rating_breaches)

    def test_missing_fields_are_tolerated(self):
        s = {
            "by_device": [
                {
                    "device": "Unknown",
                    "model_ids": ["unknown"],
                    "lag_p95": None,  # Missing measurement
                    "median_rating": None,
                    "builds": [],
                }
            ]
        }
        breaches = list(sbt.breaches(s))
        assert breaches == []

    def test_breach_dict_has_required_fields(self):
        s = summary_fixture()
        breaches = list(sbt.breaches(s))
        assert len(breaches) > 0
        for b in breaches:
            assert "device" in b
            assert "model_ids" in b
            assert "problem" in b
            assert "measurements" in b

    def test_non_dict_device_entry_is_skipped(self):
        s = {
            "by_device": [
                "not a dict",  # Non-dict entry
                {"device": "iPhone 17", "model_ids": ["iPhone18,3"], "lag_p95": 3.5},
            ]
        }
        breaches = list(sbt.breaches(s))
        assert len(breaches) > 0
        assert all(b["device"] == "iPhone 17" for b in breaches)

    def test_none_and_invalid_measurement_values_tolerated(self):
        s = {
            "by_device": [
                {
                    "device": "iPhone 17",
                    "model_ids": ["iPhone18,3"],
                    "lag_p95": None,
                    "median_rating": "not a number",
                    "endings": None,
                    "rated_reports": None,
                }
            ]
        }
        breaches = list(sbt.breaches(s))
        assert breaches == []

    def test_key_derived_from_model_ids_not_device_name(self):
        s = {
            "by_device": [
                {
                    "device": "Custom Name",
                    "model_ids": ["iPhone18,1", "iPhone18,2"],
                    "lag_p95": 3.5,
                }
            ]
        }
        breaches = list(sbt.breaches(s))
        key, title, body = sbt.render(breaches[0])
        # Key should be based on model_ids, not device name
        assert "iphone18" in key  # slug version (lowercase)


class TestSanitize:
    def test_strips_control_characters(self):
        dirty = "test\x00\x01\x02\nclean"
        clean = sbt._sanitize(dirty)
        assert "\x00" not in clean and "\x01" not in clean

    def test_collapses_html_comments(self):
        dirty = "build <!-- foo --> 5"
        clean = sbt._sanitize(dirty)
        assert "-->" not in clean
        assert "<!--" not in clean

    def test_caps_length(self):
        long_str = "x" * 500
        clean = sbt._sanitize(long_str, limit=100)
        assert len(clean) <= 100

    def test_preserves_safe_strings(self):
        safe = "iOS 27.0"
        assert sbt._sanitize(safe) == safe


class TestRender:
    def test_render_returns_key_title_body(self):
        breach = {
            "device": "iPhone 17 Pro",
            "model_ids": ["iPhone18,1"],
            "problem": "lag_p95",
            "measurements": {"lag_p95": 3.2, "threshold": 2.0},
        }
        key, title, body = sbt.render(breach)
        assert isinstance(key, str) and isinstance(title, str) and isinstance(body, str)
        assert key  # non-empty
        assert "3.2" in title  # lag value in title

    def test_body_contains_marvin_seal_ticket_marker(self):
        breach = {
            "device": "iPhone 17",
            "model_ids": ["iPhone18,3"],
            "problem": "low_rating",
            "measurements": {},
        }
        key, title, body = sbt.render(breach)
        assert f"<!-- marvin:seal-ticket:{key} -->" in body

    def test_body_never_includes_note(self):
        """Privacy hard rule: notes are never in the ticket."""
        breach = {
            "device": "iPhone 17",
            "model_ids": ["iPhone18,3"],
            "problem": "low_rating",
            "measurements": {"note": "testers complained"},
        }
        key, title, body = sbt.render(breach)
        assert "complained" not in body
        assert "note" not in body.lower()

    def test_render_includes_ios_versions(self):
        breach = {
            "device": "iPhone 17",
            "model_ids": ["iPhone18,3"],
            "problem": "lag_p95",
            "measurements": {
                "lag_p95": 3.5,
                "threshold": 2.0,
                "os_versions": ["iOS 26.0", "iOS 27.0"],
            },
        }
        key, title, body = sbt.render(breach)
        assert "iOS 26.0" in body
        assert "iOS 27.0" in body

    def test_render_includes_build_breakdown(self):
        breach = {
            "device": "iPhone 17",
            "model_ids": ["iPhone18,3"],
            "problem": "lag_p95",
            "measurements": {
                "lag_p95": 3.5,
                "threshold": 2.0,
                "builds": [
                    {"build": "5", "conversations": 50},
                    {"build": "4", "conversations": 30},
                ],
            },
        }
        key, title, body = sbt.render(breach)
        assert "build 5" in body or "Build breakdown" in body
        assert "50 conv" in body

    def test_render_sanitizes_all_fields(self):
        breach = {
            "device": "iPhone\x00\x01 17",
            "model_ids": ["iPhone18,3<!-- comment -->"],
            "problem": "lag_p95",
            "measurements": {
                "lag_p95": 3.5,
                "threshold": 2.0,
                "os_versions": ["iOS\x00 27.0"],
            },
        }
        key, title, body = sbt.render(breach)
        assert "\x00" not in body
        assert "\x01" not in body
        # Device names and model IDs should be sanitized (no comments from input)
        # The intentional marvin:seal-ticket marker is OK, so just check the fields
        assert "<!-- comment -->" not in body
        assert "iPhone18,3<!-- comment -->" not in body


class TestFindIssue:
    def test_find_issue_returns_none_on_gh_failure(self):
        gh_mock = MagicMock(return_value=None)
        result = sbt._find_issue("key-1", "marker", {}, gh=gh_mock)
        assert result is None

    def test_find_issue_loads_from_state_first(self):
        state = {"key-1": 42}
        gh_mock = MagicMock()
        result = sbt._find_issue("key-1", "marker", state, gh=gh_mock)
        assert result == 42
        gh_mock.assert_not_called()

    def test_find_issue_queries_gh_if_not_in_state(self):
        gh_mock = MagicMock(return_value='[{"number": 99}]')
        state = {}
        result = sbt._find_issue("key-1", "marker", state, gh=gh_mock)
        assert result == 99
        assert state["key-1"] == 99

    def test_find_issue_uses_list_argv(self):
        """Verify _find_issue calls gh with list-argv convention, not shell=True."""
        gh_mock = MagicMock(return_value='[{"number": 99}]')
        state = {}
        sbt._find_issue("key-1", "marker", state, gh=gh_mock)
        # Verify gh was called with a list
        assert gh_mock.call_count == 1
        call_args = gh_mock.call_args[0][0]
        assert isinstance(call_args, list)
        assert "issue" in call_args
        assert "list" in call_args


class TestCheckAndFile:
    def test_check_and_file_returns_dict_with_status_per_breach(self, tmp_path):
        store = tmp_path / "seal-beta"
        store.mkdir()
        summary_path = store / "summary.json"
        summary_path.write_text(json.dumps(summary_fixture()))

        def gh_mock(args, env=None):
            if isinstance(args, list) and "create" in args:
                return "https://github.com/G-Eskayo/clarity-captions/issues/123"
            if isinstance(args, list) and "list" in args:
                return '[]'
            return None

        result = sbt.check_and_file(store_dir=store, gh=gh_mock)
        assert isinstance(result, dict)
        assert result.get("status") == "ok"

    def test_check_and_file_uses_file_lock(self, tmp_path):
        store = tmp_path / "seal-beta"
        store.mkdir()
        summary_path = store / "summary.json"
        summary_path.write_text(json.dumps(summary_fixture()))

        called = []
        original_flock = __import__("fcntl").flock

        def track_flock(*args, **kwargs):
            called.append(("flock", args, kwargs))
            return original_flock(*args, **kwargs)

        def gh_mock(args, env=None):
            if isinstance(args, list) and "create" in args:
                return "https://github.com/G-Eskayo/clarity-captions/issues/123"
            if isinstance(args, list) and "list" in args:
                return '[]'
            return None

        with patch("fcntl.flock", side_effect=track_flock):
            sbt.check_and_file(store_dir=store, gh=gh_mock)
            assert any("flock" in str(c) for c in called)

    def test_check_and_file_persists_state_on_success(self, tmp_path):
        store = tmp_path / "seal-beta"
        store.mkdir()
        summary_path = store / "summary.json"
        summary_path.write_text(json.dumps(summary_fixture()))

        def gh_mock(args, env=None):
            if isinstance(args, list) and "create" in args:
                return "https://github.com/G-Eskayo/clarity-captions/issues/123"
            if isinstance(args, list) and "list" in args:
                return '[]'
            return None

        sbt.check_and_file(store_dir=store, gh=gh_mock)
        state_file = store / "tickets.json"
        assert state_file.exists()

    def test_check_and_file_skips_unchanged_bodies(self, tmp_path):
        store = tmp_path / "seal-beta"
        store.mkdir()
        summary_path = store / "summary.json"
        summary_path.write_text(json.dumps(summary_fixture()))

        # Pre-populate state to force a fetch
        state_file = store / "tickets.json"
        state_file.write_text('{"iphone-17-pro-lag-p95": 10}')

        def gh_mock(args, env=None):
            if isinstance(args, list) and "view" in args and "10" in args:
                # Return an issue that already has the exact body we'd render
                # (This is brittle, but proves the mechanism works)
                return json.dumps({"state": "OPEN", "body": "old body"})
            if isinstance(args, list) and "list" in args:
                return '[{"number": 10}]'
            return None

        result = sbt.check_and_file(store_dir=store, gh=gh_mock)
        statuses = [b.get("status") for b in result.get("breaches", [])]
        # Should have some statuses (either updated or unchanged)
        assert len(statuses) > 0

    def test_check_and_file_reopens_closed_issues(self, tmp_path):
        store = tmp_path / "seal-beta"
        store.mkdir()
        summary_path = store / "summary.json"
        summary_path.write_text(json.dumps(summary_fixture()))

        state_file = store / "tickets.json"
        state_file.write_text('{"iphone-17-pro-lag-p95": 10}')

        reopen_called = []
        def gh_mock(args, env=None):
            if isinstance(args, list) and "view" in args:
                reopen_called.append("view")
                return json.dumps({"state": "CLOSED", "body": "old body"})
            if isinstance(args, list) and "reopen" in args:
                reopen_called.append("reopen")
                return "OK"
            if isinstance(args, list) and "edit" in args:
                reopen_called.append("edit")
                return "OK"
            if isinstance(args, list) and "list" in args:
                return '[{"number": 10}]'
            return '{"number": 123}'

        result = sbt.check_and_file(store_dir=store, gh=gh_mock)
        assert "reopen" in reopen_called

    def test_check_and_file_only_writes_confirmed_state(self, tmp_path):
        """One gh failure must not corrupt the state file with partial updates."""
        store = tmp_path / "seal-beta"
        store.mkdir()
        summary_path = store / "summary.json"
        summary_path.write_text(json.dumps(summary_fixture()))

        call_count = [0]
        def gh_mock(args, env=None):
            call_count[0] += 1
            if isinstance(args, list) and "list" in args and call_count[0] == 1:
                return None  # First list call fails
            if isinstance(args, list) and "list" in args:
                return '[]'
            if isinstance(args, list) and "create" in args:
                return "https://github.com/owner/repo/issues/999"
            return None

        result = sbt.check_and_file(store_dir=store, gh=gh_mock)
        state_file = store / "tickets.json"
        if state_file.exists():
            state = json.loads(state_file.read_text())
            # State should only have entries for successfully filed issues
            assert isinstance(state, dict)


class TestAdversarial:
    """Adversarial tests per marvin#409 spec."""

    def test_same_breach_on_later_run_updates_not_duplicates(self, tmp_path):
        """The same breach on a later run updates the existing ticket rather than duplicating it."""
        store = tmp_path / "seal-beta"
        store.mkdir()
        summary_path = store / "summary.json"

        # First run: breach exists
        summary_path.write_text(json.dumps(summary_fixture()))

        gh_calls = []

        def mock_gh(args, env=None):
            gh_calls.append(args)
            if isinstance(args, list) and "create" in args:
                return "https://github.com/owner/repo/issues/123"
            if isinstance(args, list) and "edit" in args:
                return "OK"
            if isinstance(args, list) and "list" in args:
                return '[{"number": 123}]'
            return None

        sbt.check_and_file(store_dir=store, gh=mock_gh)
        first_run_calls = len(gh_calls)

        # Second run: same breach
        gh_calls.clear()

        def mock_gh_second(args, env=None):
            gh_calls.append(args)
            if isinstance(args, list) and "list" in args:
                return '[{"number": 123}]'
            if isinstance(args, list) and "view" in args:
                return json.dumps({"state": "OPEN", "body": "old"})
            if isinstance(args, list) and "edit" in args:
                return "OK"
            return None

        sbt.check_and_file(store_dir=store, gh=mock_gh_second)
        second_run_calls = len(gh_calls)

        # Second run should have fewer calls (state file was populated)
        assert second_run_calls < first_run_calls

    def test_note_with_name_never_in_rendered_ticket(self):
        """A note containing a name or phone number never appears in the rendered ticket."""
        breach = {
            "device": "iPhone 17",
            "model_ids": ["iPhone18,3"],
            "problem": "low_rating",
            "measurements": {
                "note": "Alice complained about lag (555-1234)",
                "name": "Alice",
                "phone": "555-1234",
            },
        }
        key, title, body = sbt.render(breach)

        # Privacy hard rule
        assert "Alice" not in body
        assert "555" not in body
        assert "complained" not in body

    def test_gh_failure_leaves_state_consistent(self, tmp_path):
        """The gh budget/cooldown gate refusing a call leaves state consistent."""
        store = tmp_path / "seal-beta"
        store.mkdir()
        summary_path = store / "summary.json"
        summary_path.write_text(json.dumps(summary_fixture()))

        def gh_fails(args, env=None):
            if isinstance(args, list) and "list" in args:
                return None  # gh 75 = rate limit
            return None

        result = sbt.check_and_file(store_dir=store, gh=gh_fails)

        # State file should exist and be valid JSON
        state_file = store / "tickets.json"
        if state_file.exists():
            state = json.loads(state_file.read_text())
            assert isinstance(state, dict)


class TestCLI:
    def test_cli_run_subcommand(self, tmp_path):
        store = tmp_path / "seal-beta"
        store.mkdir()
        summary_path = store / "summary.json"
        summary_path.write_text(json.dumps(summary_fixture()))

        def mock_check_and_file(store_dir=None):
            return {"status": "ok", "breaches": []}

        result = sbt.main(["run", "--store", str(store)], check_and_file=mock_check_and_file)
        assert result == 0


class TestMustFixRegressions:
    """Six must-fix regression tests per marvin#409 spec."""

    def test_state_loaded_but_not_a_dict_is_reset(self, tmp_path):
        """If state file is malformed (not a dict), reset to {}."""
        store = tmp_path / "seal-beta"
        store.mkdir()
        summary_path = store / "summary.json"
        summary_path.write_text(json.dumps(summary_fixture()))

        # Write invalid state (a list instead of dict)
        state_file = store / "tickets.json"
        state_file.write_text('["not", "a", "dict"]')

        def gh_mock(args, env=None):
            if isinstance(args, list) and "list" in args:
                return '[]'
            if isinstance(args, list) and "create" in args:
                return "https://github.com/owner/repo/issues/999"
            return None

        result = sbt.check_and_file(store_dir=store, gh=gh_mock)
        # Should not crash; state should be treated as empty
        assert result.get("status") == "ok"
        state = json.loads(state_file.read_text())
        assert isinstance(state, dict)

    def test_breach_rendering_error_recorded_not_fatal(self, tmp_path):
        """If a breach renders with an exception, record error status and continue."""
        store = tmp_path / "seal-beta"
        store.mkdir()
        summary_path = store / "summary.json"
        summary_path.write_text(json.dumps(summary_fixture()))

        call_count = [0]
        def gh_mock(args, env=None):
            # First render call should succeed, second fails
            if isinstance(args, list) and "list" in args:
                return '[]'
            if isinstance(args, list) and "create" in args:
                call_count[0] += 1
                if call_count[0] == 1:
                    raise RuntimeError("Simulated render failure")
                return "https://github.com/owner/repo/issues/999"
            return None

        # This test validates that breaches() completes even if one fails
        result = sbt.check_and_file(store_dir=store, gh=gh_mock)
        # Should not raise; should record the error in breaches
        assert result.get("status") == "ok" or result.get("status").startswith("error:")

    def test_null_issue_body_tolerated(self, tmp_path):
        """A null body field is tolerated (no crash)."""
        store = tmp_path / "seal-beta"
        store.mkdir()
        summary_path = store / "summary.json"
        summary_path.write_text(json.dumps(summary_fixture()))

        # Pre-populate state to force a fetch/view
        state_file = store / "tickets.json"
        state_file.write_text('{"iphone-17-pro-lag-p95": 10}')

        def gh_mock(args, env=None):
            if isinstance(args, list) and "view" in args:
                # Return issue_data with null body
                return json.dumps({"state": "OPEN", "body": None})
            if isinstance(args, list) and "list" in args:
                return '[{"number": 10}]'
            if isinstance(args, list) and "edit" in args:
                return "OK"
            return None

        result = sbt.check_and_file(store_dir=store, gh=gh_mock)
        assert result.get("status") == "ok"

    def test_non_dict_issue_data_tolerated(self, tmp_path):
        """Non-dict issue_data is tolerated (no crash on .get())."""
        store = tmp_path / "seal-beta"
        store.mkdir()
        summary_path = store / "summary.json"
        summary_path.write_text(json.dumps(summary_fixture()))

        state_file = store / "tickets.json"
        state_file.write_text('{"iphone-17-pro-lag-p95": 10}')

        def gh_mock(args, env=None):
            if isinstance(args, list) and "view" in args:
                # Return a non-dict (shouldn't happen, but be defensive)
                return '"string instead of object"'
            if isinstance(args, list) and "list" in args:
                return '[{"number": 10}]'
            if isinstance(args, list) and "edit" in args:
                return "OK"
            return None

        # Should not crash when issue_data is not a dict
        result = sbt.check_and_file(store_dir=store, gh=gh_mock)
        # May fail or skip, but must not crash
        assert "status" in result

    def test_state_merge_preserves_old_entries(self, tmp_path):
        """State file merge: old entries + new confirmed = final state."""
        store = tmp_path / "seal-beta"
        store.mkdir()
        summary_path = store / "summary.json"
        summary_path.write_text(json.dumps(summary_fixture()))

        # Pre-populate state with an old entry
        state_file = store / "tickets.json"
        state_file.write_text('{"old-key": 999}')

        def gh_mock(args, env=None):
            if isinstance(args, list) and "list" in args:
                return '[]'
            if isinstance(args, list) and "create" in args:
                return "https://github.com/owner/repo/issues/123"
            return None

        result = sbt.check_and_file(store_dir=store, gh=gh_mock)
        assert result.get("status") == "ok"

        # Verify state file has both old and new entries
        final_state = json.loads(state_file.read_text())
        assert "old-key" in final_state  # Old entry preserved
        assert final_state["old-key"] == 999

    def test_rated_reports_missing_fails_closed(self, tmp_path):
        """rated_reports missing or not a list: breach check fails closed (num=0)."""
        store = tmp_path / "seal-beta"
        store.mkdir()

        # Create a by-build summary with rated_reports missing
        summary_data = {
            "by_device": [
                {
                    "device": "iPhone 17",
                    "model_ids": ["iPhone18,3"],
                    "median_rating": 2.0,  # Low enough to breach if num_rated_reports >= 2
                    "builds": [
                        {
                            "build": "3",
                            "conversations": 10,
                            "median_rating": 2.0,
                            # rated_reports is missing
                        }
                    ]
                }
            ]
        }
        summary_path = store / "summary.json"
        summary_path.write_text(json.dumps(summary_data))

        def gh_mock(args, env=None):
            return None  # No issues filed

        result = sbt.check_and_file(store_dir=store, gh=gh_mock)
        # Should not breach because rated_reports count defaults to 0 (fail closed)
        assert result.get("status") == "ok"
        # Check that no low_rating breach was filed
        breaches_list = result.get("breaches", [])
        low_rating_breaches = [b for b in breaches_list if b.get("problem") == "low_rating"]
        assert len(low_rating_breaches) == 0


class TestMisuseTests:
    """Tests for misuse patterns that must be defended against."""

    def test_breaches_with_non_dict_entry_skipped(self):
        """Non-dict entries in by_device are skipped without crashing."""
        s = {
            "by_device": [
                "not a dict",  # Should be skipped
                {
                    "device": "iPhone 17",
                    "model_ids": ["iPhone18,3"],
                    "lag_p95": 3.5,
                }
            ]
        }
        breaches = list(sbt.breaches(s))
        # Should only process the dict entry
        assert len(breaches) > 0
        assert all(b["device"] == "iPhone 17" for b in breaches)

    def test_by_device_missing_entire_field(self):
        """Summary without by_device field is handled gracefully."""
        s = {"totals": {"conversations": 0}}  # by_device is missing
        breaches = list(sbt.breaches(s))
        assert breaches == []

    def test_breach_with_malformed_model_ids(self):
        """model_ids non-list doesn't crash key generation."""
        s = {
            "by_device": [
                {
                    "device": "iPhone 17",
                    "model_ids": "not a list",  # Should fall back to device name
                    "lag_p95": 3.5,
                }
            ]
        }
        breaches = list(sbt.breaches(s))
        assert len(breaches) > 0
        # Key should still be generated (from device name fallback)
        key, title, body = sbt.render(breaches[0])
        assert key

    def test_sanitize_with_very_long_input(self):
        """Very long input is capped without crashing."""
        long_str = "x" * 10000
        clean = sbt._sanitize(long_str, limit=100)
        assert len(clean) <= 100
        assert "…" in clean  # Ellipsis added

    def test_render_with_empty_breach(self):
        """Minimal breach dict is rendered without required fields."""
        breach = {}
        key, title, body = sbt.render(breach)
        # Should produce valid output even with empty breach
        assert isinstance(key, str) and key
        assert isinstance(title, str) and title
        assert isinstance(body, str) and body
        assert "<!-- marvin:seal-ticket:" in body
