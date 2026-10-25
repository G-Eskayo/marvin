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

    # Mock should_run to return True (so we pass that gate) but produced to return True.
    monkeypatch.setattr("daily_digest.brief_fallback.should_run", lambda *a, **k: True)
    monkeypatch.setattr("daily_digest.brief_fallback.produced", lambda *a, **k: True)

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
    assert "already exists" in output

    # Verify content is unchanged
    assert out_file.read_text() == original_content


# ── missing helper test ────────────────────────────────────────────────────────

def test_missing_helper_format():
    """_missing() returns a consistent loud format."""
    result = dd._missing("test message")
    assert "❌ **Missing input:**" in result
    assert "test message" in result


# ── fallback gating tests (tests 4-5, daily-digest leg) ──────────────────────

def test_daily_digest_skips_when_not_responsible(tmp_path, monkeypatch):
    """Test 4: main() skips when should_run() returns False (standby, not yet time)."""
    digest_dir = tmp_path / "daily-digest"
    digest_dir.mkdir()
    out_file = digest_dir / "2026-10-25.md"

    monkeypatch.setattr(dd, "DIGEST_DIR", digest_dir)
    monkeypatch.setattr(dd, "OUT_FILE", out_file)

    # Mock should_run to return False (e.g., we're standby and it's not yet fallback time).
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "lib"))
    import brief_fallback
    monkeypatch.setattr("daily_digest.brief_fallback.should_run", lambda *a, **k: False)

    # Ensure call_claude is not called.
    def raise_call_claude(prompt: str):
        raise AssertionError("call_claude should not be called when should_run is False")
    monkeypatch.setattr(dd, "call_claude", raise_call_claude)

    # Run main() — should skip due to should_run gate.
    dd.main()

    # File should not be created.
    assert not out_file.exists()


def test_daily_digest_skips_when_already_produced(tmp_path, monkeypatch):
    """Test 5: main() skips when produced() returns True (another machine already built it)."""
    digest_dir = tmp_path / "daily-digest"
    digest_dir.mkdir()
    out_file = digest_dir / "2026-10-25.md"

    # Create a digest that was built by another machine.
    out_file.write_text("# Digest from mac-mini")
    sidecar = digest_dir / "2026-10-25.md.built-by"
    sidecar.write_text("mac-mini")

    monkeypatch.setattr(dd, "DIGEST_DIR", digest_dir)
    monkeypatch.setattr(dd, "OUT_FILE", out_file)
    monkeypatch.setattr("daily_digest.brief_fallback.should_run", lambda *a, **k: True)
    monkeypatch.setattr("daily_digest.brief_fallback.machine_profile.registry_id", lambda: "macbook-pro")

    # Ensure call_claude is not called.
    def raise_call_claude(prompt: str):
        raise AssertionError("call_claude should not be called when produced() is True")
    monkeypatch.setattr(dd, "call_claude", raise_call_claude)

    # Run main() — should skip due to produced gate.
    dd.main()

    # File content should be unchanged.
    assert out_file.read_text() == "# Digest from mac-mini"


def test_daily_digest_skips_when_claude_call_fails(tmp_path, monkeypatch):
    """Test 3: main() skips without writing if call_claude() returns a failure string."""
    digest_dir = tmp_path / "daily-digest"
    digest_dir.mkdir()
    out_file = digest_dir / "2026-10-25.md"

    monkeypatch.setattr(dd, "DIGEST_DIR", digest_dir)
    monkeypatch.setattr(dd, "OUT_FILE", out_file)
    monkeypatch.setattr("daily_digest.brief_fallback.should_run", lambda *a, **k: True)
    monkeypatch.setattr("daily_digest.brief_fallback.produced", lambda *a, **k: False)

    # Mock call_claude to return a failure string.
    monkeypatch.setattr(dd, "call_claude", lambda prompt: "(claude call failed: timeout)")

    # Run main() — should return early without writing.
    dd.main()

    # File should not be created.
    assert not out_file.exists()
    # Sidecar should not be created either.
    sidecar = digest_dir / "2026-10-25.md.built-by"
    assert not sidecar.exists()


def test_main_digest_leg_skip_when_already_produced(tmp_path, monkeypatch):
    """Test 4 (digest leg): main() skips writing if digest already produced by another machine.
    Tests the recheck before writing (line 334 in daily_digest.py).
    """
    digest_dir = tmp_path / "daily-digest"
    digest_dir.mkdir(parents=True)
    out_file = digest_dir / "2026-10-25.md"

    # Pre-create the digest file as if produced by another machine.
    out_file.write_text("# Digest from primary")
    sidecar = digest_dir / "2026-10-25.md.built-by"
    sidecar.write_text("mac-mini")

    monkeypatch.setattr(dd, "TODAY", "2026-10-25")
    monkeypatch.setattr(dd, "DIGEST_DIR", digest_dir)
    monkeypatch.setattr(dd, "OUT_FILE", out_file)

    # Mock this machine as the standby.
    monkeypatch.setattr("daily_digest.brief_fallback.machine_profile.registry_id", lambda: "macbook-pro")
    monkeypatch.setattr("daily_digest.brief_fallback.produced", lambda path: path == out_file)
    monkeypatch.setattr("daily_digest.brief_fallback.mark_built", lambda *a, **k: None)
    monkeypatch.setattr("daily_digest.brief_fallback.should_run", lambda *a, **k: True)

    # Mock roadmap and other inputs to avoid errors.
    monkeypatch.setattr(dd, "ROADMAP", tmp_path / "roadmap.md")
    (tmp_path / "roadmap.md").write_text("# Roadmap")
    monkeypatch.setattr(dd, "HANDOFFS_DIR", tmp_path / "handoffs")
    (tmp_path / "handoffs").mkdir()
    monkeypatch.setattr(dd, "REVIEWER_LOG", tmp_path / "review.log")
    (tmp_path / "review.log").write_text("")
    monkeypatch.setattr(dd, "RESULTS_MD", tmp_path / "results.md")
    (tmp_path / "results.md").write_text("")

    # Mock call_claude to avoid actual Claude call.
    monkeypatch.setattr(dd, "call_claude", lambda prompt: "# Digest content")

    original_content = out_file.read_text()
    dd.main()

    # File should not have been modified (should still have the original content).
    assert out_file.read_text() == original_content


def test_main_digest_race_condition_resilience(tmp_path, monkeypatch):
    """Test 12 (digest leg): main() handles race condition where file is produced between checks.
    Verifies that the recheck before writing prevents duplicates even if primary runs concurrently.
    """
    digest_dir = tmp_path / "daily-digest"
    digest_dir.mkdir(parents=True)
    out_file = digest_dir / "2026-10-25.md"

    monkeypatch.setattr(dd, "TODAY", "2026-10-25")
    monkeypatch.setattr(dd, "DIGEST_DIR", digest_dir)
    monkeypatch.setattr(dd, "OUT_FILE", out_file)

    # Mock should_run to return True (should run).
    monkeypatch.setattr("daily_digest.brief_fallback.should_run", lambda *a, **k: True)

    # Mock produced: first call returns False (before render), second call returns True (after render).
    produced_calls = [False, True]
    call_count = [0]
    def mock_produced(path):
        result = produced_calls[call_count[0]]
        call_count[0] = min(call_count[0] + 1, len(produced_calls) - 1)
        return result

    monkeypatch.setattr("daily_digest.brief_fallback.produced", mock_produced)
    monkeypatch.setattr("daily_digest.brief_fallback.mark_built", lambda *a, **k: None)

    # Mock other inputs.
    monkeypatch.setattr(dd, "ROADMAP", tmp_path / "roadmap.md")
    (tmp_path / "roadmap.md").write_text("# Roadmap")
    monkeypatch.setattr(dd, "HANDOFFS_DIR", tmp_path / "handoffs")
    (tmp_path / "handoffs").mkdir()
    monkeypatch.setattr(dd, "REVIEWER_LOG", tmp_path / "review.log")
    (tmp_path / "review.log").write_text("")
    monkeypatch.setattr(dd, "RESULTS_MD", tmp_path / "results.md")
    (tmp_path / "results.md").write_text("")
    monkeypatch.setattr(dd, "call_claude", lambda prompt: "# New digest content")

    dd.main()

    # File should not have been written (recheck caught the race).
    assert not out_file.exists()
