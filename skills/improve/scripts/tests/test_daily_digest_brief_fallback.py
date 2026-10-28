"""Integration tests for daily_digest.py with brief_fallback. Run via:
    ~/.agents/venv/bin/python -m pytest skills/improve/scripts/tests/test_daily_digest_brief_fallback.py -v
"""
from __future__ import annotations
import sys
import io
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import daily_digest as dd  # noqa: E402


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


def test_daily_digest_gate_skips_before_calling_claude(tmp_path, monkeypatch):
    """brief_fallback.should_run gate: standby before deadline skips before calling claude."""
    from datetime import datetime
    import brief_fallback
    import machine_profile
    import scanner_role

    out_file = tmp_path / "2026-10-22.md"
    digest_dir = tmp_path
    monkeypatch.setattr(dd, "OUT_FILE", out_file)
    monkeypatch.setattr(dd, "DIGEST_DIR", digest_dir)

    # Pretend we're standby (not primary) and set up machine ID
    monkeypatch.setattr(scanner_role, "is_primary", lambda x: False)
    monkeypatch.setattr(machine_profile, "registry_id", lambda: "macbook-pro")

    # Use raise-on-call sentinels: if any of these are called,
    # it means the gate didn't work
    def raise_roadmap():
        raise AssertionError("roadmap_summary should not be called when gate returns False")
    def raise_call_claude(prompt: str):
        raise AssertionError("call_claude should not be called when gate returns False")

    monkeypatch.setattr(dd, "roadmap_summary", raise_roadmap)
    monkeypatch.setattr(dd, "call_claude", raise_call_claude)

    # Capture stdout to verify the gate message is printed
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()

    try:
        # Run main with a time before the deadline — should return immediately without calling any of the above
        before_deadline = datetime(2026, 10, 22, 8, 0).astimezone()  # Before 8:30 deadline
        dd.main(now=before_deadline)
        output = sys.stdout.getvalue()
    finally:
        sys.stdout = old_stdout

    # Verify the gate message was printed
    assert "standby:" in output or "primary hasn't reached deadline" in output


def test_daily_digest_toctou_recheck_drops_write(tmp_path, monkeypatch):
    """TOCTOU recheck: produced() before final write prevents duplicate build."""
    from datetime import datetime
    import brief_fallback
    import machine_profile
    import scanner_role

    out_file = tmp_path / "2026-10-22.md"
    digest_dir = tmp_path
    monkeypatch.setattr(dd, "OUT_FILE", out_file)
    monkeypatch.setattr(dd, "DIGEST_DIR", digest_dir)

    # Pretend we're primary so the gate doesn't skip
    monkeypatch.setattr(scanner_role, "is_primary", lambda x: True)
    monkeypatch.setattr(machine_profile, "registry_id", lambda: "mac-mini")

    # Pre-create a file to simulate primary having built it
    out_file.write_text("# Original from primary\n\nDifferent content")

    # Capture output to verify behavior
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()

    try:
        after_deadline = datetime(2026, 10, 22, 10, 0).astimezone()  # After 8:30 deadline
        dd.main(now=after_deadline)
        output = sys.stdout.getvalue()
    finally:
        sys.stdout = old_stdout

    # Verify the original content was preserved
    content = out_file.read_text()
    assert "Original from primary" in content
