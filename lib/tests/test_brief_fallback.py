#!/usr/bin/env python3
"""Tests for brief_fallback.py (21 test cases per plan item 5)."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import brief_fallback


class TestBriefFallback(unittest.TestCase):
    """Decision tests and fallback gate logic."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)

    # ── Tests 1–5: _home_relative_cat ────────────────────────────────────

    def test_1_home_relative_cat_under_home(self):
        """Test 1: _home_relative_cat() expands $HOME for paths under home."""
        home = Path.home()
        path = home / ".claude" / "briefs" / "2026-10-24.md"
        cmd = brief_fallback._home_relative_cat(path)
        self.assertIn("$HOME", cmd)
        self.assertIn(".claude/briefs/2026-10-24.md", cmd)
        self.assertTrue(cmd.startswith("cat"))

    def test_2_home_relative_cat_outside_home(self):
        """Test 2: _home_relative_cat() fully quotes paths outside home."""
        path = "/tmp/test file.txt"
        cmd = brief_fallback._home_relative_cat(path)
        self.assertNotIn("$HOME", cmd)
        self.assertIn("'/tmp/test file.txt'", cmd)

    def test_3_home_relative_cat_with_spaces(self):
        """Test 3: _home_relative_cat() properly escapes spaces in filenames."""
        home = Path.home()
        path = home / ".claude" / "file with spaces.md"
        cmd = brief_fallback._home_relative_cat(path)
        self.assertIn("$HOME", cmd)
        self.assertTrue("file with spaces.md" in cmd and "$HOME" in cmd)

    def test_4_home_relative_cat_return_type(self):
        """Test 4: _home_relative_cat() returns a string."""
        path = "/tmp/test.txt"
        result = brief_fallback._home_relative_cat(path)
        self.assertIsInstance(result, str)

    def test_5_home_relative_cat_pathlib_support(self):
        """Test 5: _home_relative_cat() accepts pathlib.Path objects."""
        path = Path("/tmp/test.txt")
        cmd = brief_fallback._home_relative_cat(path)
        self.assertIsInstance(cmd, str)

    # ── Tests 6–9: past_deadline with tz parameter ──────────────────────

    def test_6_past_deadline_before_with_tz(self):
        """Test 6: past_deadline() with tz=timezone.utc, before deadline."""
        now = datetime(2026, 10, 24, 9, 0, 0, tzinfo=timezone.utc)
        result = brief_fallback.past_deadline(10, 45, now, tz=timezone.utc)
        self.assertFalse(result)

    def test_7_past_deadline_after(self):
        """Test 7: past_deadline() returns True if current time is after the deadline."""
        now = datetime(2026, 10, 24, 22, 0, 0, tzinfo=timezone.utc)
        result = brief_fallback.past_deadline(10, 45, now)
        self.assertTrue(result)

    def test_8_past_deadline_exactly_at_with_tz(self):
        """Test 8: past_deadline() with tz=timezone.utc, exactly at deadline returns False."""
        now = datetime(2026, 10, 24, 10, 45, 0, tzinfo=timezone.utc)
        result = brief_fallback.past_deadline(10, 45, now, tz=timezone.utc)
        self.assertFalse(result)

    def test_9_past_deadline_midnight_edge_case(self):
        """Test 9: past_deadline() handles times well past the deadline."""
        now = datetime(2026, 10, 24, 18, 0, 0, tzinfo=timezone.utc)
        result = brief_fallback.past_deadline(10, 0, now)
        self.assertTrue(result)

    # ── Tests 10–14: produced ───────────────────────────────────────────

    def test_10_produced_local_exists_and_is_valid(self):
        """Test 10: produced() returns True if the local file exists and is non-empty."""
        path = Path(self.tmpdir.name) / "brief.md"
        path.write_text("# Brief for today")
        result = brief_fallback.produced(path)
        self.assertTrue(result)

    def test_11_produced_local_does_not_exist(self):
        """Test 11: produced() returns False if the local file does not exist."""
        path = Path(self.tmpdir.name) / "nonexistent.md"
        result = brief_fallback.produced(path)
        self.assertFalse(result)

    def test_12_produced_local_empty(self):
        """Test 12: produced() returns False if the local file is empty."""
        path = Path(self.tmpdir.name) / "empty.md"
        path.write_text("")
        result = brief_fallback.produced(path)
        self.assertFalse(result)

    def test_13_produced_local_failure_marker(self):
        """Test 13: produced() returns False if the local file contains the failure marker."""
        path = Path(self.tmpdir.name) / "failed.md"
        path.write_text("(claude call failed: some error\n# Brief")
        result = brief_fallback.produced(path)
        self.assertFalse(result)

    def test_14_produced_local_unreadable(self):
        """Test 14: produced() returns False if the local file is unreadable."""
        path = Path(self.tmpdir.name) / "unreadable.md"
        path.write_text("content")
        path.chmod(0o000)
        self.addCleanup(path.chmod, 0o644)
        result = brief_fallback.produced(path)
        self.assertFalse(result)

    # ── Tests 15–17: should_run primary + fallback gate logic ────────────

    def test_15_should_run_primary_always_runs(self):
        """Test 15: should_run() always runs on the primary (mac-mini) with role=primary."""
        import machine_profile
        import scanner_role
        path = Path(self.tmpdir.name) / "brief.md"
        path.write_text("existing brief")

        with mock.patch.object(machine_profile, 'registry_id', return_value="mac-mini-001"):
            with mock.patch.object(scanner_role, 'is_primary', return_value=True):
                decision = brief_fallback.should_run(path, 10, 45)
                self.assertTrue(decision.should_run)
                self.assertIn("primary", decision.reason.lower())
                self.assertEqual(decision.role, "primary")

    def test_16_should_run_fallback_deadline_not_passed(self):
        """Test 16: should_run() on standby returns False if deadline has not passed."""
        import machine_profile
        import scanner_role
        path = Path(self.tmpdir.name) / "brief.md"
        now = datetime(2026, 10, 24, 8, 0, 0, tzinfo=timezone.utc)

        with mock.patch.object(machine_profile, 'registry_id', return_value="macbook-001"):
            with mock.patch.object(scanner_role, 'is_primary', return_value=False):
                decision = brief_fallback.should_run(path, 10, 45, now=now)
                self.assertFalse(decision.should_run)
                self.assertIn("deadline", decision.reason.lower())

    def test_17_should_run_fallback_deadline_passed_and_no_output(self):
        """Test 17: should_run() on standby runs if deadline passed and primary has no output."""
        import machine_profile
        import scanner_role
        import task_dispatch
        path = Path(self.tmpdir.name) / "nonexistent.md"
        now = datetime(2026, 10, 24, 23, 0, 0, tzinfo=timezone.utc)

        with mock.patch.object(machine_profile, 'registry_id', return_value="macbook-001"):
            with mock.patch.object(scanner_role, 'is_primary', return_value=False):
                with mock.patch.object(scanner_role, '_primary_device',
                                return_value=("mac-mini-001", {"tailscale_hostname": "100.1.2.3"})):
                    with mock.patch.object(task_dispatch, '_tailscale_online_hosts',
                                    return_value={"100.1.2.3"}):
                        with mock.patch.object(brief_fallback, 'produced', return_value=False):
                            decision = brief_fallback.should_run(path, 10, 45, now=now)
                            self.assertTrue(decision.should_run)
                            self.assertIn("did not produce output", decision.reason)

    # ── Tests 18–19: should_run with different scenarios ──────────────

    def test_18_should_run_fallback_different_day(self):
        """Test 18: should_run() on fallback for tomorrow's brief (different day) still works."""
        import machine_profile
        import scanner_role
        import task_dispatch
        path = Path(self.tmpdir.name) / "2026-10-24.md"
        now = datetime(2026, 10, 25, 20, 0, 0, tzinfo=timezone.utc)

        with mock.patch.object(machine_profile, 'registry_id', return_value="macbook-001"):
            with mock.patch.object(scanner_role, 'is_primary', return_value=False):
                with mock.patch.object(scanner_role, '_primary_device',
                                return_value=("mac-mini-001", {"tailscale_hostname": "100.1.2.3"})):
                    with mock.patch.object(task_dispatch, '_tailscale_online_hosts',
                                    return_value={"100.1.2.3"}):
                        with mock.patch.object(brief_fallback, 'produced', return_value=False):
                            decision = brief_fallback.should_run(path, 10, 45, now=now)
                            self.assertTrue(decision.should_run)

    def test_19_should_run_fallback_primary_offline(self):
        """Test 19: should_run() fails open if primary device is offline."""
        import machine_profile
        import scanner_role
        import task_dispatch
        path = Path(self.tmpdir.name) / "brief.md"
        now = datetime(2026, 10, 24, 23, 0, 0, tzinfo=timezone.utc)

        with mock.patch.object(machine_profile, 'registry_id', return_value="macbook-001"):
            with mock.patch.object(scanner_role, 'is_primary', return_value=False):
                with mock.patch.object(scanner_role, '_primary_device',
                                return_value=("mac-mini-001", {"tailscale_hostname": "100.1.2.3"})):
                    with mock.patch.object(task_dispatch, '_tailscale_online_hosts', return_value=set()):
                        decision = brief_fallback.should_run(path, 10, 45, now=now)
                        self.assertTrue(decision.should_run)
                        self.assertIn("offline", decision.reason)

    # ── Test 20: Fail-open on exception ──────────────────────────────────

    def test_20_should_run_fail_open_on_exception(self):
        """Test 20: should_run() fails open (returns True with role=fallback) on any exception."""
        import machine_profile
        path = Path(self.tmpdir.name) / "brief.md"

        with mock.patch.object(machine_profile, 'registry_id', side_effect=RuntimeError("simulated error")):
            decision = brief_fallback.should_run(path, 10, 45)
            self.assertTrue(decision.should_run)
            self.assertIn("fail-open", decision.reason)
            self.assertEqual(decision.role, "fallback")

    # ── Test 21: Run parameter is forwarded to produced() calls ────────────

    def test_21_should_run_uses_run_parameter_in_produced_calls(self):
        """Test 21: should_run() forwards the run parameter to produced() calls."""
        import machine_profile
        import scanner_role
        import task_dispatch

        path = Path(self.tmpdir.name) / "brief.md"
        now = datetime(2026, 10, 24, 23, 0, 0, tzinfo=timezone.utc)

        run_calls = []
        def mock_run_that_tracks_calls(*args, **kwargs):
            run_calls.append((args, kwargs))
            # Return a process-like object that indicates file doesn't exist
            class MockProc:
                returncode = 1
                stdout = ""
            return MockProc()

        with mock.patch.object(machine_profile, 'registry_id', return_value="macbook-001"):
            with mock.patch.object(scanner_role, 'is_primary', return_value=False):
                with mock.patch.object(scanner_role, '_primary_device',
                                return_value=("mac-mini-001", {"tailscale_hostname": "100.1.2.3"})):
                    with mock.patch.object(task_dispatch, '_tailscale_online_hosts',
                                    return_value={"100.1.2.3"}):
                        # Pass the mock run parameter
                        decision = brief_fallback.should_run(path, 10, 45, now=now, run=mock_run_that_tracks_calls)
                        self.assertTrue(decision.should_run)
                        # Verify the mock_run was actually called (at least once for SSH)
                        self.assertGreater(len(run_calls), 0, "run parameter should have been called for SSH operations")

    # ── Tests 22–25: Grace window functionality ──────────────────────────

    def test_22_should_run_grace_window_has_not_passed_right_after_usual_time(self):
        """Test 22: should_run() on standby returns False immediately after usual time (within grace window)."""
        import machine_profile
        import scanner_role
        path = Path(self.tmpdir.name) / "brief.md"
        # Usual time is 10:45, now is 10:45:01 — 1 second after, still within 60-minute grace window
        now = datetime(2026, 10, 24, 10, 45, 1, tzinfo=timezone.utc)

        with mock.patch.object(machine_profile, 'registry_id', return_value="macbook-001"):
            with mock.patch.object(scanner_role, 'is_primary', return_value=False):
                decision = brief_fallback.should_run(path, 10, 45, now=now)
                self.assertFalse(decision.should_run)
                self.assertIn("grace window", decision.reason)

    def test_23_should_run_grace_window_passes_after_an_hour(self):
        """Test 23: should_run() on standby returns True after the grace window has passed (60+ minutes)."""
        import machine_profile
        import scanner_role
        import task_dispatch
        path = Path(self.tmpdir.name) / "nonexistent.md"
        # Usual time Oct 24 at 10:45, now is Oct 25 at 00:00 — definitely > 60 min after, grace window passed
        now = datetime(2026, 10, 25, 0, 0, 0, tzinfo=timezone.utc)

        with mock.patch.object(machine_profile, 'registry_id', return_value="macbook-001"):
            with mock.patch.object(scanner_role, 'is_primary', return_value=False):
                with mock.patch.object(scanner_role, '_primary_device',
                                return_value=("mac-mini-001", {"tailscale_hostname": "100.1.2.3"})):
                    with mock.patch.object(task_dispatch, '_tailscale_online_hosts',
                                    return_value={"100.1.2.3"}):
                        with mock.patch.object(brief_fallback, 'produced', return_value=False):
                            decision = brief_fallback.should_run(path, 10, 45, now=now)
                            self.assertTrue(decision.should_run)

    def test_24_past_deadline_grace_minutes_is_additive(self):
        """Test 24: past_deadline() with grace_minutes=60 correctly adds the grace window."""
        # Deadline is 10:45, now is 11:44 (59 minutes later) — should be False
        now = datetime(2026, 10, 24, 11, 44, 0, tzinfo=timezone.utc)
        result = brief_fallback.past_deadline(10, 45, now, tz=timezone.utc, grace_minutes=60)
        self.assertFalse(result)

        # Now is 11:46 (61 minutes later) — should be True
        now = datetime(2026, 10, 24, 11, 46, 0, tzinfo=timezone.utc)
        result = brief_fallback.past_deadline(10, 45, now, tz=timezone.utc, grace_minutes=60)
        self.assertTrue(result)

    def test_25_past_deadline_default_grace_minutes_is_zero_unchanged(self):
        """Test 25: past_deadline() without grace_minutes arg behaves as before (grace=0)."""
        # Deadline is 10:45, now is 10:46 (1 minute later) — should be True with grace=0
        now = datetime(2026, 10, 24, 10, 46, 0, tzinfo=timezone.utc)
        result = brief_fallback.past_deadline(10, 45, now, tz=timezone.utc)
        self.assertTrue(result)

        # Now is 10:45 exactly — should be False
        now = datetime(2026, 10, 24, 10, 45, 0, tzinfo=timezone.utc)
        result = brief_fallback.past_deadline(10, 45, now, tz=timezone.utc)
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
