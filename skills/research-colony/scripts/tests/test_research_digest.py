"""Tests for research_digest.py (ADR 0067): fallback gate checking."""
from pathlib import Path
import sys
from datetime import date

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import research_digest as rd  # noqa: E402


def test_produce_recheck_uses_produced_not_exists(tmp_path, monkeypatch):
    """TOCTOU recheck before write uses produced() not exists() (test 3)."""
    import brief_fallback

    digest_dir = tmp_path
    today = date.today().isoformat()
    out_path = digest_dir / f"{today}.md"

    monkeypatch.setattr(rd, "DIGEST_DIR", digest_dir)

    # Mock load_today_cache to return some items
    monkeypatch.setattr(rd, "load_today_cache", lambda: [{"title": "Test", "url": "http://example.com"}])
    monkeypatch.setattr(rd, "load_correlated_from_chroma", lambda: [])

    # Mock produced to return True on the second call (simulating primary writing during generation)
    call_count = [0]

    def mock_produced(path, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return False  # First call: not produced yet
        return True  # Second call (before final write): now it is

    monkeypatch.setattr(brief_fallback, "produced", mock_produced)

    # Mock marvin_launcher to avoid real calls
    monkeypatch.setattr(rd, "marvin_launcher", type("ML", (), {"launch": lambda *a, **k: type("R", (), {"exit_code": 0, "text": "# Digest\n\nContent"})()})())

    # Mock pass_or_quarantine to always pass
    monkeypatch.setattr("research_digest.pass_or_quarantine", lambda *a, **k: True)

    result = rd.generate()

    # File should not have been written because produced() returned True before write
    assert not out_path.exists()
    assert result == out_path  # But it returns the path anyway since it was "produced"
