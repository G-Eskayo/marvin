"""Tests for daily_digest.py's file handling and parsing. Run via:
    ~/.agents/venv/bin/python -m pytest skills/improve/scripts/tests/test_daily_digest.py -v
"""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import daily_digest as dd  # noqa: E402


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
