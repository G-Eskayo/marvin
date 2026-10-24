"""Tests for research_digest.py's gating and skip-if-exists behavior."""
import sys
from pathlib import Path
from datetime import datetime, timezone

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import research_digest as rd


def test_generate_skips_when_out_file_already_exists(tmp_path, monkeypatch):
    """Test 1: generate() returns early if out file already exists after the gate check."""
    digest_dir = tmp_path / ".claude" / "research-digest"
    digest_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(rd, "DIGEST_DIR", digest_dir)

    # Create an existing digest file
    today = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    out_path = digest_dir / f"{today}.md"
    out_path.write_text("# Existing digest\n")

    # Mock should_run to return True (would build)
    from lib import brief_fallback
    mock_decision = brief_fallback.Decision(should_build=True, reason="must build")
    monkeypatch.setattr(rd.brief_fallback, "should_run", lambda **kw: mock_decision)

    # Call generate() — it should skip if the file exists
    result = rd.generate()

    # Verify it returned the existing path without regenerating
    assert result == out_path
    # Verify the file still has the old content (wasn't regenerated)
    assert result.read_text() == "# Existing digest\n"
