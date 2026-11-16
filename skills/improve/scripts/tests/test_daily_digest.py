"""Tests for daily_digest.py's file handling and parsing. Run via:
    ~/.agents/venv/bin/python -m pytest skills/improve/scripts/tests/test_daily_digest.py -v
"""
from __future__ import annotations
import sys
import os
import time
import importlib
import zoneinfo
from pathlib import Path
from datetime import datetime, timezone, timedelta, date
from unittest.mock import patch, MagicMock

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import daily_digest as dd  # noqa: E402

import pytest  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "lib"))
import brief_fallback  # noqa: E402  (main() imports it by name; the same module object, so the pin below holds)


@pytest.fixture(autouse=True)
def _pinned_machine_role(monkeypatch):
    """No test here reads which Mac is primary (#826): test_main_short_circuits_when_out_file_exists passed on the
    primary and failed on the standby MacBook, because main() asked the real role. Every test runs as the primary;
    a test about the gate pins its own answer over this one, and asking the real role fails the test."""
    monkeypatch.setattr(brief_fallback, "should_run", lambda *a, **k: brief_fallback.Decision(True, "primary (pinned by the test)"))

    def _real_role(*_a, **_k):
        raise AssertionError("a test asked this machine's real role (scanner_role.is_primary): pin it instead")
    monkeypatch.setattr(brief_fallback, "is_primary", _real_role)


@pytest.fixture
def frozen_time_tz(monkeypatch):
    """Fixture that freezes time and allows simulating different timezones.

    Usage:
        frozen_time_tz(epoch_timestamp, tz_name)

    where:
        epoch_timestamp: seconds since epoch (e.g., 1731450600 for 2026-11-12 23:30 UTC-8)
        tz_name: POSIX timezone name (e.g., "Etc/GMT+8" for UTC-8)

    The fixture:
    1. Sets TZ environment variable to the given timezone
    2. Calls time.tzset() to apply it
    3. Patches dd.date.today() to return a fixed date computed from the epoch
    4. Reloads dd module so TODAY and OUT_FILE recompute
    5. Restores TZ and reloads dd in cleanup

    Note: date.today() is in the C _datetime module and reads the system clock directly,
    not through time.time(). This fixture patches dd.date directly.
    """
    original_tz = os.environ.get("TZ")

    def _set_time_and_tz(epoch_timestamp, tz_name):
        # Set timezone
        monkeypatch.setenv("TZ", tz_name)
        time.tzset()

        # Compute the frozen datetimes BEFORE patching (using the real datetime class)
        # Use fromtimestamp with UTC to get the correct datetime, then convert to target timezone
        tz_info = zoneinfo.ZoneInfo(tz_name)
        frozen_utc_dt = datetime.fromtimestamp(epoch_timestamp, tz=timezone.utc)
        frozen_local_dt = frozen_utc_dt.astimezone(tz_info)
        frozen_date = frozen_local_dt.date()

        # Create a custom date class that returns the frozen date
        class FrozenDate(date):
            @classmethod
            def today(cls):
                return frozen_date

        # Create a custom datetime class that returns the frozen datetime for now()
        # Store the frozen datetimes in the class to avoid closure issues
        class FrozenDatetime(datetime):
            _frozen_utc = frozen_utc_dt
            _frozen_local = frozen_local_dt

            @classmethod
            def now(cls, tz=None):
                if tz is None:
                    return cls._frozen_local.replace(tzinfo=None)
                elif tz == timezone.utc:
                    return cls._frozen_utc
                else:
                    return cls._frozen_utc.astimezone(tz)

        # Patch the date and datetime classes in the datetime module BEFORE reload
        # This way, when dd is reloaded and does "from datetime import date", it gets our patched classes
        import datetime as dt_module
        monkeypatch.setattr(dt_module, "date", FrozenDate)
        monkeypatch.setattr(dt_module, "datetime", FrozenDatetime)

        # Also patch time.time() to return the frozen epoch for any code that uses it
        monkeypatch.setattr("time.time", lambda: epoch_timestamp)

        # Reload module so TODAY and OUT_FILE recompute under new TZ/date
        importlib.reload(dd)

    yield _set_time_and_tz

    # Cleanup: restore TZ and reload module
    if original_tz is None:
        monkeypatch.delenv("TZ", raising=False)
    else:
        monkeypatch.setenv("TZ", original_tz)
    time.tzset()
    importlib.reload(dd)


def test_no_test_here_reads_the_real_machine_role():
    assert brief_fallback.should_run().should_build is True
    with pytest.raises(AssertionError, match="real role"):
        brief_fallback.is_primary("mac-mini-1")


# ── bench_summary tests ────────────────────────────────────────────────────────

def test_bench_summary_file_absent(tmp_path, monkeypatch):
    """bench_summary returns loud missing message when RESULTS_MD doesn't exist."""
    monkeypatch.setattr(dd, "RESULTS_MD", tmp_path / "RESULTS.md")
    result = dd.bench_summary()
    assert "❌ **Missing input:**" in result
    assert str(tmp_path / "RESULTS.md") in result


def test_bench_summary_file_empty(tmp_path, monkeypatch):
    """bench_summary returns loud missing message when file is empty."""
    results_file = tmp_path / "RESULTS.md"
    results_file.write_text("")
    monkeypatch.setattr(dd, "RESULTS_MD", results_file)
    result = dd.bench_summary()
    assert "❌ **Missing input:**" in result
    assert "empty" in result.lower()


def test_bench_summary_file_read_error(tmp_path, monkeypatch):
    """bench_summary returns loud missing message on OSError."""
    results_file = tmp_path / "RESULTS.md"
    results_file.write_text("some content")
    monkeypatch.setattr(dd, "RESULTS_MD", results_file)
    with patch.object(Path, "read_text", side_effect=OSError("Permission denied")):
        result = dd.bench_summary()
        assert "❌ **Missing input:**" in result
        assert "Permission denied" in result


def test_bench_summary_file_with_content(tmp_path, monkeypatch):
    """bench_summary returns last 40 lines when file has content."""
    results_file = tmp_path / "RESULTS.md"
    lines = [f"line {i}" for i in range(100)]
    results_file.write_text("\n".join(lines))
    monkeypatch.setattr(dd, "RESULTS_MD", results_file)

    result = dd.bench_summary()

    # Should have last 40 lines
    assert "line 99" in result
    assert "line 60" in result
    assert "line 59" not in result


# ── reviewer_health_summary tests ──────────────────────────────────────────────

def test_reviewer_health_log_absent(tmp_path, monkeypatch):
    """reviewer_health_summary returns loud missing message when log doesn't exist."""
    monkeypatch.setattr(dd, "REVIEWER_LOG", tmp_path / "background_review.log")
    result = dd.reviewer_health_summary()
    assert "❌ **Missing input:**" in result
    assert str(tmp_path / "background_review.log") in result


def test_reviewer_health_log_empty(tmp_path, monkeypatch):
    """reviewer_health_summary returns loud missing message when log is empty."""
    log_file = tmp_path / "background_review.log"
    log_file.write_text("")
    monkeypatch.setattr(dd, "REVIEWER_LOG", log_file)
    result = dd.reviewer_health_summary()
    assert "❌ **Missing input:**" in result
    assert "empty" in result.lower()


def test_reviewer_health_log_read_error(tmp_path, monkeypatch):
    """reviewer_health_summary returns loud missing message on OSError."""
    log_file = tmp_path / "background_review.log"
    log_file.write_text("=== run 2026-10-22T12:00:00 ===")

    monkeypatch.setattr(dd, "REVIEWER_LOG", log_file)
    with patch.object(Path, "read_text", side_effect=OSError("Permission denied")):
        result = dd.reviewer_health_summary()
        assert "❌ **Missing input:**" in result
        assert "Permission denied" in result


def test_reviewer_health_log_with_no_markers(tmp_path, monkeypatch):
    """reviewer_health_summary returns loud missing message when log has no recognizable run markers."""
    log_file = tmp_path / "background_review.log"
    log_file.write_text("Some random content\nBut no markers here\n")
    monkeypatch.setattr(dd, "REVIEWER_LOG", log_file)
    result = dd.reviewer_health_summary()
    # A log file with content but no recognizable markers is malformed and should
    # trigger the loud _missing() guard rather than silently appearing as "no runs".
    assert "❌ **Missing input:**" in result
    assert str(log_file) in result
    assert "run markers" in result


def test_reviewer_health_log_all_runs_outside_window(tmp_path, monkeypatch):
    """reviewer_health_summary returns well-formed message when all runs are outside window."""
    log_file = tmp_path / "background_review.log"
    old_ts = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    log_file.write_text(f"=== run {old_ts} ===\n=== end (exit 0) ===\n")
    monkeypatch.setattr(dd, "REVIEWER_LOG", log_file)
    result = dd.reviewer_health_summary()
    assert "No background-reviewer runs in the last 7 days" in result


def test_reviewer_health_single_run_success(tmp_path, monkeypatch):
    """reviewer_health_summary reports success for a single successful run."""
    log_file = tmp_path / "background_review.log"
    now_ts = datetime.now(timezone.utc).isoformat()
    log_file.write_text(f"=== run {now_ts} ===\nDoing something\n=== end (exit 0) ===\n")
    monkeypatch.setattr(dd, "REVIEWER_LOG", log_file)
    result = dd.reviewer_health_summary()
    assert "1 run(s) in the last 7 days" in result
    assert "1 succeeded" in result
    assert "0 failed" in result


def test_reviewer_health_single_run_failed_no_end_marker(tmp_path, monkeypatch):
    """reviewer_health_summary reports failure when run has no end marker."""
    log_file = tmp_path / "background_review.log"
    now_ts = datetime.now(timezone.utc).isoformat()
    log_file.write_text(f"=== run {now_ts} ===\nDoing something but crashed\n")
    monkeypatch.setattr(dd, "REVIEWER_LOG", log_file)
    result = dd.reviewer_health_summary()
    assert "1 run(s) in the last 7 days" in result
    assert "1 failed" in result
    assert "never completed" in result


def test_reviewer_health_single_run_failed_nonzero_exit(tmp_path, monkeypatch):
    """reviewer_health_summary reports failure for non-zero exit code."""
    log_file = tmp_path / "background_review.log"
    now_ts = datetime.now(timezone.utc).isoformat()
    log_file.write_text(f"=== run {now_ts} ===\nDoing something\n=== end (exit 1) ===\n")
    monkeypatch.setattr(dd, "REVIEWER_LOG", log_file)
    result = dd.reviewer_health_summary()
    assert "1 run(s) in the last 7 days" in result
    assert "1 failed" in result
    assert "exit code 1" in result


def test_reviewer_health_single_run_failed_signature_match(tmp_path, monkeypatch):
    """reviewer_health_summary reports failure when failure signature is matched."""
    log_file = tmp_path / "background_review.log"
    now_ts = datetime.now(timezone.utc).isoformat()
    log_file.write_text(
        f"=== run {now_ts} ===\nDoing something\nTraceback (most recent call last):\n=== end (exit 0) ===\n"
    )
    monkeypatch.setattr(dd, "REVIEWER_LOG", log_file)
    result = dd.reviewer_health_summary()
    assert "1 run(s) in the last 7 days" in result
    assert "1 failed" in result
    assert "Traceback (most recent call last)" in result


def test_reviewer_health_multiple_runs_mixed(tmp_path, monkeypatch):
    """reviewer_health_summary correctly counts mixed success/failure across multiple runs."""
    log_file = tmp_path / "background_review.log"
    now = datetime.now(timezone.utc)
    ts1 = (now - timedelta(hours=1)).isoformat()
    ts2 = (now - timedelta(hours=2)).isoformat()
    ts3 = (now - timedelta(hours=3)).isoformat()

    log_content = (
        f"=== run {ts1} ===\nSuccess\n=== end (exit 0) ===\n"
        f"\n=== run {ts2} ===\nFailed\n=== end (exit 1) ===\n"
        f"\n=== run {ts3} ===\nSuccess\n=== end (exit 0) ===\n"
    )
    log_file.write_text(log_content)
    monkeypatch.setattr(dd, "REVIEWER_LOG", log_file)
    result = dd.reviewer_health_summary()
    assert "3 run(s) in the last 7 days" in result
    assert "2 succeeded" in result
    assert "1 failed" in result


def test_reviewer_health_multiple_runs_all_success(tmp_path, monkeypatch):
    """reviewer_health_summary correctly counts all successful runs."""
    log_file = tmp_path / "background_review.log"
    now = datetime.now(timezone.utc)
    ts1 = (now - timedelta(hours=1)).isoformat()
    ts2 = (now - timedelta(hours=2)).isoformat()

    log_content = (
        f"=== run {ts1} ===\nSuccess\n=== end (exit 0) ===\n"
        f"\n=== run {ts2} ===\nSuccess\n=== end (exit 0) ===\n"
    )
    log_file.write_text(log_content)
    monkeypatch.setattr(dd, "REVIEWER_LOG", log_file)
    result = dd.reviewer_health_summary()
    assert "2 run(s) in the last 7 days" in result
    assert "2 succeeded" in result
    assert "0 failed" in result
    assert "Failures:" not in result


def test_reviewer_health_multiple_runs_all_failed(tmp_path, monkeypatch):
    """reviewer_health_summary correctly counts all failed runs."""
    log_file = tmp_path / "background_review.log"
    now = datetime.now(timezone.utc)
    ts1 = (now - timedelta(hours=1)).isoformat()
    ts2 = (now - timedelta(hours=2)).isoformat()

    log_content = (
        f"=== run {ts1} ===\nFailed\n=== end (exit 1) ===\n"
        f"\n=== run {ts2} ===\nFailed\n=== end (exit 127) ===\n"
    )
    log_file.write_text(log_content)
    monkeypatch.setattr(dd, "REVIEWER_LOG", log_file)
    result = dd.reviewer_health_summary()
    assert "2 run(s) in the last 7 days" in result
    assert "0 succeeded" in result
    assert "2 failed" in result
    assert "Failures:" in result


def test_reviewer_health_many_failures_truncated_to_5(tmp_path, monkeypatch):
    """reviewer_health_summary shows at most 5 failure details."""
    log_file = tmp_path / "background_review.log"
    now = datetime.now(timezone.utc)

    log_content = ""
    # Start from 1 to ensure all are failures (exit code 0 = success)
    for i in range(1, 11):
        ts = (now - timedelta(hours=i)).isoformat()
        log_content += f"=== run {ts} ===\nFailed {i}\n=== end (exit {i}) ===\n\n"

    log_file.write_text(log_content)
    monkeypatch.setattr(dd, "REVIEWER_LOG", log_file)
    result = dd.reviewer_health_summary()
    assert "10 run(s) in the last 7 days" in result
    assert "0 succeeded" in result
    assert "10 failed" in result
    # Count the dashes to ensure exactly 5 are shown
    failure_lines = [line for line in result.split("\n") if line.strip().startswith("- ")]
    assert len(failure_lines) == 5


def test_results_md_points_at_real_bench_path():
    """RESULTS_MD constant points at the real bench path (regression guard)."""
    # This ensures that the fixed constant actually resolves to the expected location
    # in ~/.agents/bench/, not somewhere else entirely.
    expected = Path.home() / ".agents" / "bench" / "RESULTS.md"
    assert dd.RESULTS_MD == expected


def test_reviewer_health_log_last_run_no_trailing_newline(tmp_path, monkeypatch):
    """reviewer_health_summary handles runs without trailing newlines."""
    log_file = tmp_path / "background_review.log"
    now_ts = datetime.now(timezone.utc).isoformat()
    # Write without trailing newline after end marker
    log_file.write_text(f"=== run {now_ts} ===\nSuccess\n=== end (exit 0) ===")
    monkeypatch.setattr(dd, "REVIEWER_LOG", log_file)
    result = dd.reviewer_health_summary()
    assert "1 run(s) in the last 7 days" in result
    assert "1 succeeded" in result


def test_reviewer_health_log_invalid_timestamp_skipped(tmp_path, monkeypatch):
    """reviewer_health_summary skips runs with unparseable timestamps."""
    log_file = tmp_path / "background_review.log"
    now_ts = datetime.now(timezone.utc).isoformat()
    # Mix a valid run with an invalid-timestamp run
    log_content = (
        f"=== run {now_ts} ===\nValid run\n=== end (exit 0) ===\n"
        f"\n=== run not-a-timestamp ===\nBad timestamp\n=== end (exit 0) ===\n"
    )
    log_file.write_text(log_content)
    monkeypatch.setattr(dd, "REVIEWER_LOG", log_file)
    result = dd.reviewer_health_summary()
    # Should only count the valid run, skipping the one with bad timestamp
    assert "1 run(s) in the last 7 days" in result
    assert "1 succeeded" in result


def test_main_short_circuits_when_out_file_exists(tmp_path, monkeypatch):
    """main() returns early if today's digest already exists."""
    out_file = tmp_path / "2026-10-22.md"
    original_content = "# Already exists"
    out_file.write_text(original_content)

    # Mock OUT_FILE and DIGEST_DIR
    digest_dir = tmp_path
    monkeypatch.setattr(dd, "OUT_FILE", out_file)
    monkeypatch.setattr(dd, "DIGEST_DIR", digest_dir)

    # Patch functions with raise-on-call sentinels: if any of these are called,
    # it means the short-circuit didn't work
    def raise_roadmap():
        raise AssertionError("roadmap_summary should not be called when out_file exists")
    def raise_bench():
        raise AssertionError("bench_summary should not be called when out_file exists")
    def raise_reviewer_health():
        raise AssertionError("reviewer_health_summary should not be called when out_file exists")
    def raise_call_claude(prompt: str):
        raise AssertionError("call_claude should not be called when out_file exists")

    monkeypatch.setattr(dd, "roadmap_summary", raise_roadmap)
    monkeypatch.setattr(dd, "bench_summary", raise_bench)
    monkeypatch.setattr(dd, "reviewer_health_summary", raise_reviewer_health)
    monkeypatch.setattr(dd, "call_claude", raise_call_claude)

    # Capture stdout to verify the short-circuit message is printed
    import io
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()

    try:
        # Run main — should return immediately without calling any of the above
        dd.main()
        output = sys.stdout.getvalue()
    finally:
        sys.stdout = old_stdout

    # Verify the short-circuit message was printed
    assert "Today's digest already exists" in output

    # Verify content is unchanged
    assert out_file.read_text() == original_content


# ── missing helper test ────────────────────────────────────────────────────────

def test_missing_helper_format():
    """_missing() returns a consistent loud format."""
    result = dd._missing("test message")
    assert "❌ **Missing input:**" in result
    assert "test message" in result


"""Tests for daily_digest.py — gate and TOCTOU handling."""
from datetime import datetime, timezone
from pathlib import Path
import sys
import pytest

# Add paths for imports
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

import brief_fallback


class TestDailyDigestGate:
    """Test that the fallback gate skips the digest build when appropriate."""

    def test_gate_off_skips_without_writing(self, tmp_path, monkeypatch):
        """If should_run() returns False, main() should not call claude or write."""
        # Import after monkeypatching to get the mocked module
        import daily_digest

        # Mock the output file path
        digest_dir = tmp_path / "daily-digest"
        out_file = digest_dir / "2026-10-22.md"
        monkeypatch.setattr("daily_digest.DIGEST_DIR", digest_dir)
        monkeypatch.setattr("daily_digest.OUT_FILE", out_file)

        # Mock should_run to return False
        def mock_should_run(*args, **kwargs):
            return brief_fallback.Decision(False, "fallback: skipping")
        monkeypatch.setattr("brief_fallback.should_run", mock_should_run)

        # Mock call_claude so it fails if called
        def mock_call_claude(*args, **kwargs):
            raise AssertionError("call_claude should not be invoked")
        monkeypatch.setattr("daily_digest.call_claude", mock_call_claude)

        # Run main
        daily_digest.main()

        # Assert OUT_FILE was not created
        assert not out_file.exists()

    def test_toctou_recheck_uses_produced_not_exists(self, tmp_path, monkeypatch):
        """If OUT_FILE has valid content (even after gate check), don't rebuild."""
        import daily_digest

        digest_dir = tmp_path / "daily-digest"
        out_file = digest_dir / "2026-10-22.md"
        monkeypatch.setattr("daily_digest.DIGEST_DIR", digest_dir)
        monkeypatch.setattr("daily_digest.OUT_FILE", out_file)

        # Mock should_run to return True
        def mock_should_run(*args, **kwargs):
            return brief_fallback.Decision(True, "primary")
        monkeypatch.setattr("brief_fallback.should_run", mock_should_run)

        # Pre-create the file with valid content to simulate a race condition
        digest_dir.mkdir(parents=True)
        existing_content = "# Existing digest from another process\n\nRace condition test."
        out_file.write_text(existing_content)

        # Mock call_claude to return some content
        def mock_call_claude(*args, **kwargs):
            return "# New digest\n\nThis should not overwrite existing content."
        monkeypatch.setattr("daily_digest.call_claude", mock_call_claude)

        # Run main
        daily_digest.main()

        # Assert the original content was NOT overwritten
        assert out_file.read_text() == existing_content

    def test_should_run_called_with_explicit_parameters(self, tmp_path, monkeypatch):
        """should_run() is called with usual_hour=8, usual_minute=30."""
        import daily_digest

        digest_dir = tmp_path / "daily-digest"
        out_file = digest_dir / "2026-10-22.md"
        monkeypatch.setattr("daily_digest.DIGEST_DIR", digest_dir)
        monkeypatch.setattr("daily_digest.OUT_FILE", out_file)

        # Track calls to should_run
        calls = []

        def mock_should_run(*args, **kwargs):
            calls.append(kwargs)
            return brief_fallback.Decision(False, "test: skipping")
        monkeypatch.setattr("brief_fallback.should_run", mock_should_run)

        # Run main
        daily_digest.main()

        # Verify should_run was called with the right parameters
        assert len(calls) == 1
        assert calls[0].get("usual_hour") == 8
        assert calls[0].get("usual_minute") == 30


# ── the improvement queue in the inbox (ADR 0083) ────────────────────────────────────────────────────────────

def test_queue_summary_reads_the_inbox_once_the_pile_exists(tmp_path, monkeypatch):
    import inbox
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "improvement-queue.md").write_text(
        "## 2026-07-01 — marvin\n- **[NAMING]** a (`x.py`)\n- **[KISS]** b (`y.py`) — auto-fix: done, PR #1 merged\n")
    monkeypatch.setattr(dd, "CLAUDE_DIR", claude)
    assert "**[NAMING]** a" in dd.improvement_queue_summary()  # the old file, before the import
    inbox.import_legacy("improvement-queue", claude / "inbox")
    (claude / "improvement-queue.md").write_text("STALE")
    out = dd.improvement_queue_summary()
    assert "STALE" not in out and out.startswith("1 of 2 item(s) still open")
    assert "[NAMING] a" in out and "[done, PR #1 merged]" in out


def test_queue_summary_of_an_empty_pile(tmp_path, monkeypatch):
    (tmp_path / "inbox" / "improvement-queue").mkdir(parents=True)
    monkeypatch.setattr(dd, "CLAUDE_DIR", tmp_path)
    assert dd.improvement_queue_summary() == "(improvement queue is empty)"


# ── timezone tests ────────────────────────────────────────────────────────────

def _epoch_for_local_time(year, month, day, hour, minute, tz_name):
    """Calculate epoch timestamp for a given local time in a given timezone."""
    # Create a naive datetime in the target timezone, then get its epoch
    tz_info = zoneinfo.ZoneInfo(tz_name)
    local_dt = datetime(year, month, day, hour, minute, 0, tzinfo=tz_info)
    return int(local_dt.timestamp())


def test_daily_digest_local_date_ac1(tmp_path, monkeypatch, frozen_time_tz):
    """AC1: 2026-11-12 23:30 local UTC-8 → TODAY='2026-11-12'"""
    # Set DIGEST_DIR to temp path so we test in isolation
    monkeypatch.setattr(dd, "DIGEST_DIR", tmp_path)

    # Calculate epoch for 2026-11-12 23:30 UTC-8
    epoch = _epoch_for_local_time(2026, 11, 12, 23, 30, "Etc/GMT+8")

    # Freeze time at this instant in this timezone
    frozen_time_tz(epoch, "Etc/GMT+8")

    # TODAY should be 2026-11-12, not 2026-11-13 (which would be UTC)
    assert dd.TODAY == "2026-11-12"
    assert dd.OUT_FILE.name == "2026-11-12.md"


def test_daily_digest_writer_reader_agreement(tmp_path, monkeypatch):
    """AC2: writer (TODAY) and reader (session_start_report._check_digest) agree on local date."""
    monkeypatch.setattr(dd, "DIGEST_DIR", tmp_path)

    sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "lib"))
    import session_start_report  # noqa: E402

    # Store original TZ
    original_tz = os.environ.get("TZ")

    try:
        # Test both UTC-8 (west) and UTC+9 (east) with real system time
        # The key is that .astimezone() respects TZ, and so does date.today()
        for tz_name in ["Etc/GMT+8", "Etc/GMT-9"]:
            monkeypatch.setenv("TZ", tz_name)
            time.tzset()

            # Reload dd so TODAY recomputes with new TZ
            importlib.reload(dd)

            # Get date as computed by dd
            writer_date = dd.TODAY

            # Get date as computed by session_start_report (should match)
            # This calls datetime.now(timezone.utc).astimezone() which respects TZ
            reader_date = session_start_report._now().astimezone().strftime("%Y-%m-%d")

            assert writer_date == reader_date, f"Mismatch in {tz_name}: writer={writer_date}, reader={reader_date}"
    finally:
        # Restore original TZ
        if original_tz is None:
            monkeypatch.delenv("TZ", raising=False)
        else:
            monkeypatch.setenv("TZ", original_tz)
        time.tzset()
        importlib.reload(dd)


@pytest.mark.parametrize("hour,minute,tz_name", [
    (23, 59, "Etc/GMT+8"),   # 23:59 UTC-8
    (0, 1, "Etc/GMT+8"),      # 00:01 UTC-8
    (23, 59, "Etc/GMT-9"),    # 23:59 UTC+9
    (0, 1, "Etc/GMT-9"),      # 00:01 UTC+9
])
def test_daily_digest_midnight_boundary(tmp_path, monkeypatch, frozen_time_tz, hour, minute, tz_name):
    """Test 4: midnight-boundary ×2-zones — test writer/reader agreement at midnight boundaries."""
    monkeypatch.setattr(dd, "DIGEST_DIR", tmp_path)

    # Use 2026-11-12 as a reference date, then set the time
    epoch = _epoch_for_local_time(2026, 11, 12, hour, minute, tz_name)
    frozen_time_tz(epoch, tz_name)

    # Import session_start_report and patch its _now() to return the frozen UTC datetime
    sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "lib"))
    import session_start_report  # noqa: E402

    # Compute the frozen UTC datetime that matches what frozen_time_tz set up
    tz_info = zoneinfo.ZoneInfo(tz_name)
    frozen_utc_dt = datetime.fromtimestamp(epoch, tz=timezone.utc)

    # Patch _now to return the frozen UTC datetime
    monkeypatch.setattr(session_start_report, "_now", lambda: frozen_utc_dt)

    writer_date = dd.TODAY
    reader_date = session_start_report._now().astimezone().strftime("%Y-%m-%d")

    assert writer_date == reader_date, f"Mismatch at {hour:02d}:{minute:02d} in {tz_name}: writer={writer_date}, reader={reader_date}"


def test_daily_digest_stale_old_utc_file(tmp_path, monkeypatch):
    """Test 5: stale old-UTC-named leftover file present → no crash, new file written."""
    # Create a fake ~/.claude directory for the test to avoid reading real user state
    fake_claude_dir = tmp_path / "claude"
    fake_claude_dir.mkdir()

    monkeypatch.setattr(dd, "CLAUDE_DIR", fake_claude_dir)
    monkeypatch.setattr(dd, "DIGEST_DIR", fake_claude_dir / "daily-digest")
    monkeypatch.setattr(dd, "ROADMAP", fake_claude_dir / "marvin-roadmap.md")
    monkeypatch.setattr(dd, "HANDOFFS_DIR", fake_claude_dir / "handoffs")

    # Create the DIGEST_DIR
    (fake_claude_dir / "daily-digest").mkdir()

    # Explicitly compute today's date to avoid issues with frozen_time_tz from previous tests
    from datetime import date as real_date
    today_str = real_date.today().isoformat()

    # Also monkeypatch OUT_FILE to use the new DIGEST_DIR with the computed date
    expected_out_file = (fake_claude_dir / "daily-digest") / f"{today_str}.md"
    monkeypatch.setattr(dd, "OUT_FILE", expected_out_file)

    # Create a stale file with a different date to simulate a leftover from before the fix
    # Use yesterday's date as the old file
    stale_date = (real_date.today() - timedelta(days=1)).isoformat()
    old_file = (fake_claude_dir / "daily-digest") / f"{stale_date}.md"
    old_file.write_text("old content from yesterday")

    # Mock should_run and call_claude
    monkeypatch.setattr(brief_fallback, "should_run",
                       lambda *a, **k: brief_fallback.Decision(True, "primary (pinned)"))
    monkeypatch.setattr(dd, "call_claude", lambda p: "# New digest\n\nContent")

    # Run main
    dd.main()

    # Verify new file was created with today's date
    assert expected_out_file.exists(), f"New file should be created at {expected_out_file}"
    content = expected_out_file.read_text()
    assert "New digest" in content, f"New file should contain digest content, got: {content[:100]}"

    # Old file should still exist (we didn't delete it)
    assert old_file.exists(), f"Old file should still exist at {old_file}"


def test_daily_digest_tz_unset_uses_system_zone(tmp_path, monkeypatch):
    """Test 6: TZ unset → falls back to system zone, writer/reader still agree."""
    monkeypatch.setattr(dd, "DIGEST_DIR", tmp_path)

    sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "lib"))
    import session_start_report  # noqa: E402

    original_tz = os.environ.get("TZ")
    try:
        # Unset TZ — both should fall back to system zone
        monkeypatch.delenv("TZ", raising=False)
        time.tzset()
        importlib.reload(dd)

        writer_date = dd.TODAY
        reader_date = session_start_report._now().astimezone().strftime("%Y-%m-%d")

        assert writer_date == reader_date, "Should agree even when TZ is unset"
    finally:
        # Restore original TZ
        if original_tz is None:
            monkeypatch.delenv("TZ", raising=False)
        else:
            monkeypatch.setenv("TZ", original_tz)
        time.tzset()
        importlib.reload(dd)
