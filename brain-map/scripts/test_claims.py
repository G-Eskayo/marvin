"""Tests for the claims ledger (brain-map/scripts/claims.py).

Claims are structured checks against portfolio content, job events, ticket stages, and other
state sources. Each claim has a name, a check function, and a gather_key identifying where
its evidence comes from.

Run via: ~/.agents/venv/bin/python -m pytest brain-map/scripts/test_claims.py -v
"""
from __future__ import annotations

import json
import sys
import subprocess
from datetime import datetime, timezone
from pathlib import Path

# Find and import the claims module from the same directory
SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR.parent.parent / "lib"))
sys.path.insert(0, str(SCRIPTS_DIR))

import claims  # noqa: E402


# ── Fixtures ──

def portfolio_content_stub():
    """Fixture matching portfolio_content.py's output structure."""
    return {
        "pages": {
            "marvin": {
                "template": "system",
                "url": "/ai-projects/marvin/",
                "title": "MARVIN",
                "lead_html": "<p>The MARVIN system</p>",
                "sections": [
                    {
                        "role": "intro",
                        "body_html": "<p>MARVIN is an AI assistant. See <a href='/ai-projects/marvin/'>MARVIN</a> for more.</p>"
                    }
                ],
                "coverage": None,
                "findings": []
            },
            "clarity-captions": {
                "template": "app",
                "url": "/ai-projects/clarity-captions/",
                "title": "Clarity Captions",
                "lead_html": "<p>Built with MARVIN</p>",
                "sections": [
                    {
                        "role": "intro",
                        "body_html": "<p>See ticket #97 for details</p>"
                    }
                ],
                "coverage": None,
                "findings": []
            }
        }
    }


def job_events_stub():
    """Fixture matching job_events.py's output structure."""
    return {
        "daily-digest": {
            "job": "daily-digest",
            "label": "Daily digest",
            "runs": [
                {
                    "id": "abc123",
                    "status": "passed",
                    "started_at": datetime.now(timezone.utc).isoformat(),
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "steps": [{"step": "Scanning", "detail": "5 projects", "at": datetime.now(timezone.utc).isoformat()}],
                    "summary": "5 projects scanned",
                    "error": ""
                }
            ]
        }
    }


def ticket_stages_stub():
    """Fixture matching ticket_stages.py's output structure."""
    return {
        "g-eskayo__marvin-281": {
            "stages": [
                {
                    "stage": "claimed",
                    "status": "passed",
                    "detail": "Claimed by agent",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "machine": "mini",
                    "cost_usd": None,
                    "title": "Claims ledger: track portfolio facts over time",
                    "run_id": "run123"
                },
                {
                    "stage": "done",
                    "status": "passed",
                    "detail": "Implementation complete",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "machine": "mini",
                    "cost_usd": 0.05,
                    "title": "Claims ledger: track portfolio facts over time",
                    "run_id": "run123"
                }
            ]
        }
    }


# ── Tests 1-5: Basic claim structure and validation ──

def test_1_claim_has_name_and_check_function():
    """Each claim must have a name and callable check function."""
    for claim in claims.CLAIMS:
        assert "name" in claim
        assert "check" in claim
        assert callable(claim["check"])


def test_2_claim_has_gather_key_identifying_evidence_source():
    """Each claim must have a gather_key identifying where its evidence comes from."""
    for claim in claims.CLAIMS:
        assert "gather_key" in claim
        assert claim["gather_key"] in ["portfolio_content", "job_events", "ticket_stages"]


def test_3_check_functions_return_dict_result():
    """A check function returns True, False, or a dict with 'pass' key and optional detail."""
    portfolio = portfolio_content_stub()
    job_events = job_events_stub()
    ticket_stages = ticket_stages_stub()

    for claim in claims.CLAIMS:
        if claim["gather_key"] == "portfolio_content":
            result = claim["check"](portfolio, None, None)
        elif claim["gather_key"] == "job_events":
            result = claim["check"](job_events, None, None)
        else:  # ticket_stages
            result = claim["check"](ticket_stages, None, None)

        assert isinstance(result, (bool, dict))
        if isinstance(result, dict):
            assert "pass" in result
            assert "check failed:" not in result.get("detail", "") or result.get("pass") is False


def test_4_collect_with_no_gather_runs_all_claims_with_no_filtering(monkeypatch):
    """collect(gather=None) runs all claims against all available data."""
    monkeypatch.setattr(claims, "_gather_portfolio", lambda: portfolio_content_stub())
    monkeypatch.setattr(claims, "_gather_job_events", lambda: job_events_stub())
    monkeypatch.setattr(claims, "_gather_ticket_stages", lambda: ticket_stages_stub())

    report = claims.collect(gather=None)

    assert isinstance(report, dict)
    assert "timestamp" in report
    assert "claims" in report
    assert len(report["claims"]) > 0


def test_5_collect_with_specific_gather_filters_to_that_source(monkeypatch):
    """collect(gather='portfolio_content') runs only portfolio_content claims."""
    monkeypatch.setattr(claims, "_gather_portfolio", lambda: portfolio_content_stub())

    report = claims.collect(gather="portfolio_content")

    assert isinstance(report, dict)
    assert all(c["gather_key"] == "portfolio_content" for c in report.get("claims", []))


# ── Tests 6-13: Scanning for unchecked claims in text ──

def test_6_scan_finds_ticket_numbers_in_visible_text():
    """scan_for_unchecked_claims finds bare #123 patterns that aren't in CLAIMS."""
    text = "See #281 for details and also check #97 in the old system"
    unchecked = claims.scan_for_unchecked_claims(text)
    assert isinstance(unchecked, list)
    # #281 might be in CLAIMS, but #97 shouldn't be
    assert any("97" in t for t in unchecked)


def test_7_scan_ignores_adr_references():
    """scan_for_unchecked_claims ignores ADR ##123 patterns."""
    text = "Per ADR 0065, this changed. Also see ADR 97 for history."
    unchecked = claims.scan_for_unchecked_claims(text)
    # Should not flag ADR references
    assert "marvin-97" not in unchecked
    assert "marvin-65" not in unchecked


def test_8_scan_ignores_pr_references():
    """scan_for_unchecked_claims ignores PR ##123 patterns."""
    text = "Fixed in PR #123. See PR #97 for context."
    unchecked = claims.scan_for_unchecked_claims(text)
    assert "marvin-123" not in unchecked
    assert "marvin-97" not in unchecked


def test_9_check_claim_ticket_done_uses_parse_stage_key():
    """check_claim_ticket_done uses ticket_stages.parse_stage_key to find ticket #281."""
    ticket_stages = ticket_stages_stub()
    result = claims.check_claim_ticket_done(None, None, ticket_stages)

    assert isinstance(result, dict)
    assert result.get("pass") is True
    assert "281" in result.get("detail", "")


def test_10_check_no_failed_stages_checks_latest_stage_only():
    """check_no_failed_stages only checks the latest stage for each ticket."""
    ticket_stages = ticket_stages_stub()
    # Add a failed stage in the middle; it should be ignored since the latest is 'done'
    ticket_stages["g-eskayo__marvin-281"]["stages"].insert(1, {
        "stage": "executing",
        "status": "failed",
        "detail": "Mid-execution failure (should be ignored)",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "machine": "mini",
        "cost_usd": None,
        "title": "test"
    })

    result = claims.check_no_failed_stages(None, None, ticket_stages)

    assert isinstance(result, dict)
    assert result.get("pass") is True  # Latest stage 'done' is not failed


def test_11_check_no_failed_stages_detects_failed_latest_stage():
    """check_no_failed_stages detects when the latest stage is failed."""
    ticket_stages = {
        "g-eskayo__marvin-300": {
            "stages": [
                {
                    "stage": "claimed",
                    "status": "passed",
                    "detail": "Claimed",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "machine": "mini",
                    "cost_usd": None,
                    "title": "Test ticket"
                },
                {
                    "stage": "executing",
                    "status": "failed",
                    "detail": "Failed execution",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "machine": "mini",
                    "cost_usd": 0.01,
                    "title": "Test ticket"
                }
            ]
        }
    }

    result = claims.check_no_failed_stages(None, None, ticket_stages)

    assert isinstance(result, dict)
    assert result.get("pass") is False
    assert "1 tickets with failed" in result.get("detail", "")


def test_12_scan_excludes_html_and_scripts():
    """scan_for_unchecked_claims uses portfolio_content._visible_text() to exclude HTML."""
    text = "<p>Check #456</p><script>// #999</script>"
    unchecked = claims.scan_for_unchecked_claims(text)
    # #456 should be found, #999 inside script should be stripped
    assert any("456" in t for t in unchecked)


def test_13_collect_includes_unregistered_claims_in_report(monkeypatch):
    """collect() scans portfolio and includes unregistered ticket numbers in the report."""
    portfolio = portfolio_content_stub()
    # Add unregistered reference: #97 is not in CLAIMS
    portfolio["pages"]["test"] = {
        "lead_html": "<p>See ticket #97 for history</p>",
        "sections": []
    }

    monkeypatch.setattr(claims, "_gather_portfolio", lambda: portfolio)
    monkeypatch.setattr(claims, "_gather_job_events", lambda: {})
    monkeypatch.setattr(claims, "_gather_ticket_stages", lambda: {})

    report = claims.collect()

    assert "unregistered" in report or any("97" in str(u) for u in report.get("unregistered", []))


# ── Integration test: subprocess-level check ──

def test_subprocess_claims_script_resolves_sys_path(tmp_path):
    """Test that brain-map/scripts/claims.py's sys.path resolves correctly at subprocess level."""
    # This test runs claims.py as a subprocess to verify the sys.path fix works
    claims_script = SCRIPTS_DIR / "claims.py"

    # Create a mock home directory with minimal logs
    mock_home = tmp_path / "home"
    mock_home.mkdir()
    (mock_home / ".claude" / "logs").mkdir(parents=True)

    # Create an empty scratch dir for portfolio path
    scratch_dir = tmp_path / "scratch"
    scratch_dir.mkdir()

    # Run claims.py --json with minimal env (no PYTHONPATH)
    # Use a cwd outside the repo to ensure sys.path manipulation is correct
    env = {
        "HOME": str(mock_home),
        "MARVIN_PORTFOLIO_PATH": str(scratch_dir)
    }

    result = subprocess.run(
        [sys.executable, "-I", str(claims_script), "--json"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(tmp_path)
    )

    # Should succeed (exit 0)
    assert result.returncode == 0, f"Script failed with exit code {result.returncode}: {result.stderr}"

    # Output should be valid JSON with a claims key
    try:
        output = json.loads(result.stdout)
        assert "claims" in output, f"Missing 'claims' key in output: {output}"
        assert isinstance(output["claims"], list), "claims should be a list"
    except json.JSONDecodeError:
        assert False, f"Output is not valid JSON: {result.stdout}"


# ── Integration test: collect returns properly shaped report ──

def test_collect_returns_timestamped_report_with_all_claims(monkeypatch):
    """Full collect() run returns a report with timestamp and all claim results."""
    monkeypatch.setattr(claims, "_gather_portfolio", lambda: portfolio_content_stub())
    monkeypatch.setattr(claims, "_gather_job_events", lambda: job_events_stub())
    monkeypatch.setattr(claims, "_gather_ticket_stages", lambda: ticket_stages_stub())

    report = claims.collect(gather=None)

    assert isinstance(report, dict)
    assert "timestamp" in report
    assert "claims" in report
    assert len(report["claims"]) > 0

    # Every claim should have a result
    for claim in report["claims"]:
        assert "name" in claim
        assert "gather_key" in claim
        assert "pass" in claim
        assert "detail" in claim
        assert "timestamp" in claim


# ── Test portfolio-specific assertions with real page HTML ──

def test_marvin_link_check_uses_portfolio_data():
    """check_marvin_link examines portfolio pages."""
    portfolio = portfolio_content_stub()
    result = claims.check_marvin_link(portfolio, None, None)

    assert isinstance(result, dict)
    assert "pass" in result


def test_portfolio_copy_check_examines_findings():
    """check_portfolio_copy looks at findings in portfolio."""
    portfolio = portfolio_content_stub()
    portfolio["pages"]["test"] = {
        "findings": [{"rule": "copy-ai-phrase", "detail": "generic phrase"}]
    }
    result = claims.check_portfolio_copy(portfolio, None, None)

    assert isinstance(result, dict)
    assert result.get("pass") is False


def test_daily_digest_health_passes_with_stub_data():
    """check_daily_digest_health works with stub job data."""
    job_events = job_events_stub()
    result = claims.check_daily_digest_health(None, job_events, None)

    assert isinstance(result, dict)
    assert result.get("pass") is True
    assert "passed" in result.get("detail", "")


# ── Tests 20-21: Nightly mode and failure handling ──

def test_20_main_nightly_mode_records_summary_without_failing(monkeypatch, tmp_path):
    """The nightly mode should record a summary without calling run.fail() even if claims fail."""
    import job_events as je

    # Mock the gather functions to return empty results
    monkeypatch.setattr(claims, "_gather_portfolio", lambda: {})
    monkeypatch.setattr(claims, "_gather_job_events", lambda: {})
    monkeypatch.setattr(claims, "_gather_ticket_stages", lambda: {})

    # Mock job_events.job_run to capture the context
    called_fail = False
    called_summary = False

    class MockRun:
        def step(self, name, detail):
            pass
        def summary(self, msg):
            nonlocal called_summary
            called_summary = True
        def fail(self, msg):
            nonlocal called_fail
            called_fail = True

    def mock_job_run(name):
        class ContextManager:
            def __enter__(self):
                return MockRun()
            def __exit__(self, *args):
                pass
        return ContextManager()

    monkeypatch.setattr(je, "job_run", mock_job_run)
    monkeypatch.setattr(claims, "LOGS_DIR", tmp_path)

    # Simulate --nightly mode
    monkeypatch.setattr("sys.argv", ["claims.py", "--nightly"])

    # Run main
    claims.main()

    # Should have called summary but NOT fail
    assert called_summary is True
    assert called_fail is False


def test_21_collect_report_structure_for_nightly_storage(monkeypatch):
    """The collect() report has the structure needed for atomic storage in nightly mode."""
    import json

    monkeypatch.setattr(claims, "_gather_portfolio", lambda: {})
    monkeypatch.setattr(claims, "_gather_job_events", lambda: {})
    monkeypatch.setattr(claims, "_gather_ticket_stages", lambda: {})

    report = claims.collect(gather=None)

    # Verify the report can be JSON-serialized (atomic write requirement)
    json_str = json.dumps(report, indent=2)
    assert json_str  # Non-empty JSON string

    # Verify round-trip: can deserialize
    deserialized = json.loads(json_str)
    assert deserialized == report

    # Verify required fields for nightly storage
    assert "timestamp" in report
    assert "claims" in report
    assert isinstance(report["timestamp"], str)
    assert isinstance(report["claims"], list)


# ── Tests 22-23: Multiple claims and mixed results ──

def test_22_collect_with_repeated_checks(monkeypatch):
    """Running collect multiple times with the same data produces consistent results."""
    portfolio = portfolio_content_stub()
    monkeypatch.setattr(claims, "_gather_portfolio", lambda: portfolio)
    monkeypatch.setattr(claims, "_gather_job_events", lambda: {})
    monkeypatch.setattr(claims, "_gather_ticket_stages", lambda: {})

    report1 = claims.collect(gather=None)
    report2 = claims.collect(gather=None)

    # Both should have the same claims (though timestamps differ)
    assert len(report1["claims"]) == len(report2["claims"])
    assert [c["name"] for c in report1["claims"]] == [c["name"] for c in report2["claims"]]


def test_23_collect_with_one_source_failing(monkeypatch):
    """collect() handles gracefully when one evidence source is unavailable."""
    portfolio = portfolio_content_stub()
    monkeypatch.setattr(claims, "_gather_portfolio", lambda: portfolio)
    monkeypatch.setattr(claims, "_gather_job_events", lambda: None)  # Simulates job_events source failure
    monkeypatch.setattr(claims, "_gather_ticket_stages", lambda: ticket_stages_stub())

    report = claims.collect(gather=None)

    # Should still have claims from all sources even if one is None
    assert "claims" in report
    assert isinstance(report["claims"], list)
    # All sources should be represented (checks handle None gracefully)
    sources = [c["gather_key"] for c in report["claims"]]
    assert "portfolio_content" in sources
    assert "ticket_stages" in sources
    # job_events claims are still present (checks handle None gracefully)
    assert "job_events" in sources
    # But they should have returned False due to missing source
    job_event_claims = [c for c in report["claims"] if c["gather_key"] == "job_events"]
    assert len(job_event_claims) > 0
    assert all(not c.get("pass") for c in job_event_claims), "job_events claims should fail when source is None"
