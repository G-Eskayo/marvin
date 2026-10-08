#!/usr/bin/env python3
"""test_claims.py — verifies claims ledger checkers and collection."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import claims  # noqa: E402


class TestCheckers:
    """Each checker's ok/fail cases."""

    def test_check_two_machines_passes_with_two_devices(self):
        result = claims.check_two_machines({"devices": {"mini": {}, "laptop": {}}})
        assert result["ok"] is True
        assert "two" in result["detail"].lower()

    def test_check_two_machines_fails_with_one_device(self):
        result = claims.check_two_machines({"devices": {"mini": {}}})
        assert result["ok"] is False
        assert "1" in result["detail"]

    def test_check_two_machines_fails_with_no_devices(self):
        result = claims.check_two_machines({"devices": {}})
        assert result["ok"] is False

    def test_check_two_machines_handles_missing_devices(self):
        result = claims.check_two_machines({})
        assert result["ok"] is False

    def test_check_merge_gate_passes_with_recent_verifying_pass(self):
        events = [
            {"stage": "verifying", "status": "passed", "timestamp": datetime.now(timezone.utc).isoformat()}
        ]
        result = claims.check_merge_gate(events)
        assert result["ok"] is True
        assert "recent" in result["detail"].lower() or "verifying" in result["detail"].lower()

    def test_check_merge_gate_fails_with_failed_verifying(self):
        events = [
            {"stage": "verifying", "status": "failed", "timestamp": datetime.now(timezone.utc).isoformat()}
        ]
        result = claims.check_merge_gate(events)
        assert result["ok"] is False

    def test_check_merge_gate_handles_no_events(self):
        result = claims.check_merge_gate([])
        assert result["ok"] is False

    def test_check_repo_public_passes_with_public_visibility(self):
        result = claims.check_repo_public("PUBLIC")
        assert result["ok"] is True
        assert "public" in result["detail"].lower()

    def test_check_repo_public_fails_with_private_visibility(self):
        result = claims.check_repo_public("PRIVATE")
        assert result["ok"] is False
        assert "private" in result["detail"].lower()

    def test_check_repo_public_handles_mixed_case(self):
        result = claims.check_repo_public("Public")
        assert result["ok"] is True

    def test_check_jobs_recent_passes_with_recent_runs(self):
        runs = [
            {
                "status": "success",
                "finished_at": datetime.now(timezone.utc).isoformat(),
            }
        ]
        result = claims.check_jobs_recent(runs)
        assert result["ok"] is True
        assert "recent" in result["detail"].lower() or "success" in result["detail"].lower()

    def test_check_jobs_recent_fails_with_no_runs(self):
        result = claims.check_jobs_recent([])
        assert result["ok"] is False

    def test_check_jobs_recent_fails_with_old_runs(self):
        runs = [
            {
                "status": "success",
                "finished_at": "2020-01-01T00:00:00+00:00",
            }
        ]
        result = claims.check_jobs_recent(runs)
        assert result["ok"] is False
        assert "old" in result["detail"].lower() or "stale" in result["detail"].lower()


class TestCollect:
    """collect() with injected gather for isolated testing."""

    def test_collect_with_all_checks_passing(self):
        def mock_gather():
            return {
                "network": {"devices": {"mini": {}, "laptop": {}}},
                "stages": [{"stage": "verifying", "status": "passed", "timestamp": datetime.now(timezone.utc).isoformat()}],
                "visibility": "PUBLIC",
                "jobs_recent": [{"status": "success", "finished_at": datetime.now(timezone.utc).isoformat()}],
            }

        result = claims.collect(gather=mock_gather)
        assert len(result) == 4
        for claim_id in ["two-machines", "merge-gate", "repo-public", "jobs-recent"]:
            assert claim_id in result
            assert result[claim_id]["ok"] is True

    def test_collect_includes_checked_at_timestamp(self):
        def mock_gather():
            return {
                "network": {"devices": {"mini": {}, "laptop": {}}},
                "stages": [{"stage": "verifying", "status": "passed", "timestamp": datetime.now(timezone.utc).isoformat()}],
                "visibility": "PUBLIC",
                "jobs_recent": [{"status": "success", "finished_at": datetime.now(timezone.utc).isoformat()}],
            }

        result = claims.collect(gather=mock_gather)
        for claim_data in result.values():
            assert "checked_at" in claim_data
            assert isinstance(claim_data["checked_at"], str)


class TestScanUnchecked:
    """scan_for_unchecked_claims() with various claim match patterns."""

    def test_finds_numeric_facts_not_in_claims(self):
        html = "<p>The system has 42 things happening.</p>"
        claims_list = [
            {"text": "it runs on two Macs"},
            {"text": "it proves every change with tests before I see it"},
        ]
        unchecked = claims.scan_for_unchecked_claims(html, claims_list)
        # "42 things" should be flagged as a potential unregistered claim
        assert len(unchecked) > 0

    def test_matches_registered_claim_text(self):
        html = "<p>It runs on two Macs and never stops.</p>"
        claims_list = [
            {"text": "it runs on two Macs"},
        ]
        unchecked = claims.scan_for_unchecked_claims(html, claims_list)
        # "it runs on two Macs" is registered, so only unrecognized numeric claims
        assert all("two" not in u.lower() or "macs" not in u.lower() for u in unchecked)

    def test_ignores_small_numbers(self):
        html = "<p>I use 3 tools and they work great.</p>"
        claims_list = []
        unchecked = claims.scan_for_unchecked_claims(html, claims_list)
        # Small numbers like "3" should not trigger unchecked claims
        assert len(unchecked) == 0

    def test_strips_html_before_scanning(self):
        html = "<h1>Open Source</h1><p>This is <strong>open</strong> source.</p>"
        claims_list = [
            {"text": "it's open source"},
        ]
        unchecked = claims.scan_for_unchecked_claims(html, claims_list)
        # The registered claim matches the visible text
        assert len([u for u in unchecked if "open" in u.lower()]) == 0

    def test_reads_page_html_from_content_file(self, tmp_path, monkeypatch):
        """Verifies _read_page_html() loads and parses the marvin.json content file."""
        # Setup a fake portfolio directory
        content_dir = tmp_path / "content" / "longform"
        content_dir.mkdir(parents=True)

        # Create a marvin.json with both registered and unregistered claims
        marvin_content = {
            "lead_html": "<p>This is the MARVIN page.</p>",
            "sections": [
                {
                    "role": "introduction",
                    "body_html": "<p>It runs on two Macs and never crashes.</p>"
                },
                {
                    "role": "stats",
                    "body_html": "<p>We have 156 projects tracked.</p>"
                }
            ]
        }
        (content_dir / "marvin.json").write_text(json.dumps(marvin_content))

        # Mock project_catalog.portfolio_repo_path to return our tmp_path
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "lib"))
        import project_catalog  # noqa: E402
        monkeypatch.setattr(project_catalog, "portfolio_repo_path", lambda: str(tmp_path))

        # Call _read_page_html and verify it returns the concatenated HTML
        html = claims._read_page_html()
        assert "two Macs" in html
        assert "156" in html

        # Verify scan_for_unchecked_claims finds the unregistered numeric claim
        unchecked = claims.scan_for_unchecked_claims(html)
        assert any("156" in u for u in unchecked), f"Expected to find '156' in unchecked claims, got: {unchecked}"
        # Should not flag the registered claim "it runs on two Macs"
        assert not any("two" in u.lower() and "macs" in u.lower() for u in unchecked)


class TestFlagForRedraft:
    """flag_for_redraft() integration with ready-for-human notes."""

    def test_flag_for_redraft_returns_note_reference(self):
        claim = {
            "id": "test-claim",
            "text": "test text",
            "section": "test-section",
            "ok": False,
        }
        # Today, this just returns a tuple indicating what would be flagged
        # (the actual file write is tested in integration if needed)
        note_ref = claims.flag_for_redraft(claim)
        assert note_ref is not None
        assert "269" in str(note_ref) or "redraft" in str(note_ref).lower()
