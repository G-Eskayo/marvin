"""Tests for run_colony.py's gating and brief_fallback integration."""
import sys
import io
from pathlib import Path
from datetime import datetime, timezone

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import run_colony as rc  # noqa: E402


def test_run_colony_logs_correctly_when_no_output(tmp_path, monkeypatch, capsys):
    """Test 3: main() logs 'no digest written' when generate() returns None."""
    digest_dir = tmp_path / ".claude" / "research-digest"
    digest_dir.mkdir(parents=True, exist_ok=True)

    # Mock should_run to return True
    from lib import brief_fallback
    mock_decision = brief_fallback.Decision(should_build=True, reason="must build")
    monkeypatch.setattr(rc.brief_fallback, "should_run", lambda **kw: mock_decision)

    # Mock Path.home
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    # Mock generate to return None (no items or already exists)
    monkeypatch.setattr(rc.source_monitor, "main", lambda: None)
    monkeypatch.setattr(rc.correlate, "correlate", lambda: None)
    monkeypatch.setattr(rc.research_digest, "generate", lambda: None)

    result = rc.main()

    # Verify it succeeded
    assert result == 0
    # Check stderr log
    captured = capsys.readouterr()
    assert "no digest written" in captured.err


def test_main_skips_when_should_run_returns_false(tmp_path, monkeypatch):
    """main() returns early when brief_fallback.should_run() returns False."""
    digest_dir = tmp_path / ".claude" / "research-digest"
    digest_dir.mkdir(parents=True, exist_ok=True)

    # Mock the digest file path
    now = datetime(2026, 10, 24, 10, 0, tzinfo=timezone.utc)
    digest_file = digest_dir / "2026-10-24.md"

    # Mock should_run to return False (digest is fresh on primary)
    from lib import brief_fallback
    mock_decision = brief_fallback.Decision(
        should_build=False, reason="brief produced on mac-mini-1, still fresh"
    )

    monkeypatch.setattr(rc.brief_fallback, "should_run", lambda **kw: mock_decision)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    old_stderr = sys.stderr
    sys.stderr = io.StringIO()
    try:
        result = rc.main()
    finally:
        sys.stderr = old_stderr

    # Verify it returned 0 (no error)
    assert result == 0
    # Verify digest file was not created
    assert not digest_file.exists()


def test_run_colony_does_not_double_record_when_generate_already_recorded(tmp_path, monkeypatch):
    """Test 2: main() does not call record_built_by() — generate() already does."""
    digest_dir = tmp_path / ".claude" / "research-digest"
    digest_dir.mkdir(parents=True, exist_ok=True)

    # Mock should_run to return True
    from lib import brief_fallback
    mock_decision = brief_fallback.Decision(should_build=True, reason="must build")
    monkeypatch.setattr(rc.brief_fallback, "should_run", lambda **kw: mock_decision)

    # Mock Path.home
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    now = datetime(2026, 10, 24, 10, 0, tzinfo=timezone.utc)
    out_path = digest_dir / "2026-10-24.md"

    def mock_generate():
        # Simulate that generate() writes and records built_by
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("# Research Digest\n\n## Test")
        # generate() calls record_built_by internally
        rc.brief_fallback.record_built_by(out_path, "mac-mini-1", "normal", now=now)
        return out_path

    monkeypatch.setattr(rc.source_monitor, "main", lambda: None)
    monkeypatch.setattr(rc.correlate, "correlate", lambda: None)
    monkeypatch.setattr(rc.research_digest, "generate", mock_generate)

    # Track record_built_by calls to ensure it's NOT called from main()
    record_calls = []
    original_record = rc.brief_fallback.record_built_by
    def mock_record(path, machine, mode, now=None):
        record_calls.append((path, machine, mode))
        return original_record(path, machine, mode, now)
    monkeypatch.setattr(rc.brief_fallback, "record_built_by", mock_record)

    result = rc.main()

    # Verify it succeeded
    assert result == 0
    # Verify digest file was written
    assert out_path.exists()
    # Verify record_built_by was called only once (by generate, not by main)
    assert len(record_calls) == 1
    assert record_calls[0][0] == out_path
    assert record_calls[0][2] == "normal"

    # Verify sidecar was created
    sidecar = out_path.with_name(out_path.stem + ".built-by.json")
    assert sidecar.exists()
    import json
    data = json.loads(sidecar.read_text())
    assert data["mode"] == "normal"
