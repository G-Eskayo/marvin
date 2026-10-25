"""Job ownership helpers (ADR 0067): Mini-primary, MacBook-fallback for digests and morning-brief."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import job_ownership  # noqa: E402


# --- is_primary() ---

def test_is_primary_returns_true_when_stationary():
    with patch("job_ownership.is_stationary", return_value=True):
        assert job_ownership.is_primary() is True


def test_is_primary_returns_false_when_not_stationary():
    with patch("job_ownership.is_stationary", return_value=False):
        assert job_ownership.is_primary() is False


# --- past_deadline() ---

def test_past_deadline_false_before_deadline():
    # Normal time 08:30, now is 08:00 (before 09:30 deadline)
    import zoneinfo
    tz = zoneinfo.ZoneInfo('America/Los_Angeles')
    now_local = datetime(2026, 10, 25, 8, 0, 0, tzinfo=tz)
    now_utc = now_local.astimezone(timezone.utc)
    assert job_ownership.past_deadline(8, 30, now_utc, tz=tz) is False


def test_past_deadline_true_after_deadline():
    # Normal time 08:30, now is 10:00 (after 09:30 deadline)
    import zoneinfo
    tz = zoneinfo.ZoneInfo('America/Los_Angeles')
    now_local = datetime(2026, 10, 25, 10, 0, 0, tzinfo=tz)
    now_utc = now_local.astimezone(timezone.utc)
    assert job_ownership.past_deadline(8, 30, now_utc, tz=tz) is True


def test_past_deadline_true_at_deadline_plus_one():
    # Normal time 08:30, deadline at 09:30, now is 09:31
    import zoneinfo
    tz = zoneinfo.ZoneInfo('America/Los_Angeles')
    now_local = datetime(2026, 10, 25, 9, 31, 0, tzinfo=tz)
    now_utc = now_local.astimezone(timezone.utc)
    assert job_ownership.past_deadline(8, 30, now_utc, tz=tz) is True


def test_past_deadline_midnight_wrap_before():
    # Normal time 23:30, now is 23:00 (before 00:30 deadline next day)
    import zoneinfo
    tz = zoneinfo.ZoneInfo('America/Los_Angeles')
    now_local = datetime(2026, 10, 25, 23, 0, 0, tzinfo=tz)
    now_utc = now_local.astimezone(timezone.utc)
    assert job_ownership.past_deadline(23, 30, now_utc, tz=tz) is False


def test_past_deadline_midnight_wrap_after_usual_time():
    # Normal time 23:30, now is 23:45 (after 23:30 usual, before 00:30 next day deadline)
    import zoneinfo
    tz = zoneinfo.ZoneInfo('America/Los_Angeles')
    now_local = datetime(2026, 10, 25, 23, 45, 0, tzinfo=tz)
    now_utc = now_local.astimezone(timezone.utc)
    assert job_ownership.past_deadline(23, 30, now_utc, tz=tz) is True


def test_past_deadline_midnight_wrap_after_deadline_next_day():
    # Normal time 23:30, deadline is 00:30, now is 00:45 next day (after deadline)
    import zoneinfo
    tz = zoneinfo.ZoneInfo('America/Los_Angeles')
    now_local = datetime(2026, 10, 26, 0, 45, 0, tzinfo=tz)
    now_utc = now_local.astimezone(timezone.utc)
    assert job_ownership.past_deadline(23, 30, now_utc, tz=tz) is True


# --- mini_output() ---

def test_mini_output_returns_none_when_no_macs_available():
    with patch("job_ownership.remote_macs", return_value={}):
        assert job_ownership.mini_output("research-digest/2026-10-25.md") is None


def test_mini_output_returns_none_when_mini_unreachable():
    remote_macs_mock = {"mac-mini-1": {"kind": "desktop", "tailscale_hostname": "mac-mini-1.tailnet"}}
    with patch("job_ownership.remote_macs", return_value=remote_macs_mock):
        with patch("job_ownership.ssh_cat", return_value=None):
            assert job_ownership.mini_output("research-digest/2026-10-25.md") is None


def test_mini_output_returns_none_when_empty():
    remote_macs_mock = {"mac-mini-1": {"kind": "desktop", "tailscale_hostname": "mac-mini-1.tailnet"}}
    with patch("job_ownership.remote_macs", return_value=remote_macs_mock):
        with patch("job_ownership.ssh_cat", return_value=""):
            assert job_ownership.mini_output("research-digest/2026-10-25.md") is None


def test_mini_output_returns_content_when_quarantined():
    # Quarantine is treated as real output (Option B from Decision)
    remote_macs_mock = {"mac-mini-1": {"kind": "desktop", "tailscale_hostname": "mac-mini-1.tailnet"}}
    quarantine_content = "_Quarantined by safety-monitor before shipping — flagged as risky."
    with patch("job_ownership.remote_macs", return_value=remote_macs_mock):
        with patch("job_ownership.ssh_cat", return_value=quarantine_content):
            result = job_ownership.mini_output("research-digest/2026-10-25.md")
            assert result == quarantine_content


def test_mini_output_returns_content_when_real():
    remote_macs_mock = {"mac-mini-1": {"kind": "desktop", "tailscale_hostname": "mac-mini-1.tailnet"}}
    real_content = "# Research Digest — 2026-10-25\n\nSome real content."
    with patch("job_ownership.remote_macs", return_value=remote_macs_mock):
        with patch("job_ownership.ssh_cat", return_value=real_content):
            result = job_ownership.mini_output("research-digest/2026-10-25.md")
            assert result == real_content


def test_mini_output_skips_non_desktop_machines():
    # Should skip machines with kind != "desktop"
    remote_macs_mock = {
        "macbook-pro-1": {"kind": "laptop", "tailscale_hostname": "macbook-pro-1.tailnet"},
        "mac-mini-1": {"kind": "desktop", "tailscale_hostname": "mac-mini-1.tailnet"}
    }
    real_content = "# Real content from mini"
    with patch("job_ownership.remote_macs", return_value=remote_macs_mock):
        with patch("job_ownership.ssh_cat", return_value=real_content) as ssh_mock:
            result = job_ownership.mini_output("research-digest/2026-10-25.md")
            # Should have called ssh_cat for the desktop machine only
            assert result == real_content
            ssh_mock.assert_called_once()
            call_args = ssh_mock.call_args
            assert "mac-mini-1.tailnet" in call_args[0]


def test_mini_output_skips_missing_kind():
    # Machines without kind field should not match
    remote_macs_mock = {
        "mac-mini-1": {"tailscale_hostname": "mac-mini-1.tailnet"}  # no kind field
    }
    with patch("job_ownership.remote_macs", return_value=remote_macs_mock):
        with patch("job_ownership.ssh_cat", return_value="content") as ssh_mock:
            result = job_ownership.mini_output("research-digest/2026-10-25.md")
            # Should not call ssh_cat if kind != "desktop"
            assert result is None
            ssh_mock.assert_not_called()


def test_mini_output_passes_correct_path():
    remote_macs_mock = {"mac-mini-1": {"kind": "desktop", "tailscale_hostname": "mac-mini-1.tailnet"}}
    with patch("job_ownership.remote_macs", return_value=remote_macs_mock):
        with patch("job_ownership.ssh_cat", return_value="content") as ssh_mock:
            job_ownership.mini_output("daily-digest/2026-10-25.md")
            call_args = ssh_mock.call_args
            # Check that the path is constructed correctly
            assert "~/.claude/daily-digest/2026-10-25.md" in call_args[0]
