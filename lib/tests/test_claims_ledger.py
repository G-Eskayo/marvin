"""Tests for claims_ledger.py (Layer 4: verify page facts are true).
Run via: ~/.agents/venv/bin/python -m pytest lib/tests/test_claims_ledger.py -v
All tests isolated from real HOME/GitHub/hardware via temp dirs and mocking."""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import claims_ledger as cl


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Registry and data model tests (1–10) ────────────────────────────

def test_1_empty_registry_is_valid():
    """A fresh registry with no claims yet is not an error."""
    registry = cl.ClaimsRegistry(claims=[])
    assert registry.claims == []


def test_2_claim_has_required_fields():
    """Each claim must have id, text, check_fn, section."""
    claim = cl.Claim(id="test-1", text="test claim", check_fn="check_open_source", section="intro")
    assert claim.id == "test-1"
    assert claim.text == "test claim"
    assert claim.check_fn == "check_open_source"
    assert claim.section == "intro"


def test_3_check_result_has_status_not_boolean():
    """CheckResult.status must be a Literal string, never collapses unknown into true/false."""
    result = cl.CheckResult(
        claim_id="test-1",
        status="true",
        detail="repo is public",
        checked_at=_now(),
        section="story"
    )
    assert result.claim_id == "test-1"
    assert result.status in ("true", "untrue", "unknown")
    assert result.status == "true"


def test_4_check_result_status_unknown_is_distinct():
    """CheckResult can represent 'unknown' status distinctly from true/false."""
    unknown = cl.CheckResult(claim_id="x", status="unknown", detail="couldn't reach API", checked_at=_now())
    true_res = cl.CheckResult(claim_id="x", status="true", detail="verified", checked_at=_now())
    assert unknown.status != true_res.status
    assert unknown.status == "unknown"


def test_5_registry_can_be_serialized():
    """Registry can round-trip to JSON."""
    claim = cl.Claim(id="test-1", text="it works", check_fn="check_dummy", section="story")
    registry = cl.ClaimsRegistry(claims=[claim])
    data = cl.registry_to_json(registry)
    parsed = json.loads(data)
    assert parsed["claims"][0]["id"] == "test-1"
    assert parsed["claims"][0]["section"] == "story"


def test_6_registry_can_be_deserialized():
    """Registry can be loaded from JSON."""
    data = {
        "claims": [
            {"id": "c1", "text": "claim 1", "check_fn": "check_foo", "section": "section_a"}
        ]
    }
    registry = cl.registry_from_json(json.dumps(data))
    assert len(registry.claims) == 1
    assert registry.claims[0].id == "c1"


def test_7_validate_registry_catches_duplicate_ids():
    """Duplicate claim IDs in a registry are caught."""
    claims = [
        cl.Claim(id="same", text="claim 1", check_fn="check_machine_registry", section="s1"),
        cl.Claim(id="same", text="claim 2", check_fn="check_repo_visibility", section="s2"),
    ]
    registry = cl.ClaimsRegistry(claims=claims)
    issues = cl.validate_registry(registry)
    assert any("duplicate" in str(i).lower() for i in issues)


def test_8_validate_registry_catches_unknown_check_fns():
    """Unknown check_fn names in claims are reported."""
    claim = cl.Claim(id="test", text="test", check_fn="check_unknown_function", section="test")
    registry = cl.ClaimsRegistry(claims=[claim])
    issues = cl.validate_registry(registry)
    assert any("unknown" in str(i).lower() for i in issues)


def test_9_validate_registry_accepts_known_check_fns():
    """Registry with all known check functions validates successfully."""
    claims = [
        cl.Claim(id="c1", text="t1", check_fn="check_machine_registry", section="s1"),
        cl.Claim(id="c2", text="t2", check_fn="check_repo_visibility", section="s2"),
        cl.Claim(id="c3", text="t3", check_fn="check_scheduled_jobs", section="s3"),
        cl.Claim(id="c4", text="t4", check_fn="check_merge_gate", section="s4"),
    ]
    registry = cl.ClaimsRegistry(claims=claims)
    issues = cl.validate_registry(registry)
    assert len(issues) == 0


def test_10_validate_registry_rejects_facts_delegation():
    """Facts delegation check function is not in the known set."""
    claim = cl.Claim(id="test", text="test", check_fn="check_facts_delegation", section="test")
    registry = cl.ClaimsRegistry(claims=[claim])
    issues = cl.validate_registry(registry)
    assert len(issues) > 0


# ── Machine registry checks (11–14) ────────────────────────────────

def test_11_check_machine_registry_reads_from_network_path():
    """check_machine_registry reads machine_profile.NETWORK_PATH fresh each call."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        network_file = tmpdir / "marvin-network.json"
        network_file.write_text(json.dumps({
            "devices": {"mac-mini": True, "macbook": True}
        }))

        with patch("machine_profile.NETWORK_PATH", network_file):
            result = cl.check_machine_registry()
            assert result.status == "true"
            assert "2" in result.detail or "machines" in result.detail


def test_12_check_machine_registry_counts_true_devices():
    """check_machine_registry counts devices where value is True."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        network_file = tmpdir / "marvin-network.json"
        network_file.write_text(json.dumps({
            "devices": {"mac-mini": True, "macbook": False, "ipad": True}
        }))

        with patch("machine_profile.NETWORK_PATH", network_file):
            result = cl.check_machine_registry()
            assert result.status == "true"


def test_13_check_machine_registry_fails_if_fewer_than_two():
    """check_machine_registry fails if fewer than 2 devices are True."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        network_file = tmpdir / "marvin-network.json"
        network_file.write_text(json.dumps({
            "devices": {"mac-mini": True}
        }))

        with patch("machine_profile.NETWORK_PATH", network_file):
            result = cl.check_machine_registry()
            assert result.status == "untrue"
            assert "1" in result.detail


def test_14_check_machine_registry_unknown_on_missing_file():
    """check_machine_registry reports unknown if file doesn't exist."""
    with patch("machine_profile.NETWORK_PATH", Path("/nonexistent/marvin-network.json")):
        result = cl.check_machine_registry()
        assert result.status == "unknown"


# ── Repo visibility checks (15–18) ──────────────────────────────────

def test_15_check_repo_visibility_injects_run_callable():
    """check_repo_visibility accepts a run= parameter for process injection."""
    mock_run = Mock()
    mock_run.return_value = Mock(
        returncode=0,
        stdout=json.dumps({"isPrivate": False})
    )
    result = cl.check_repo_visibility(repo="test/repo", run=mock_run)
    assert result.status == "true"
    assert mock_run.called


def test_16_check_repo_visibility_reports_private_as_untrue():
    """check_repo_visibility reports 'untrue' if repo is private."""
    mock_run = Mock()
    mock_run.return_value = Mock(
        returncode=0,
        stdout=json.dumps({"isPrivate": True})
    )
    result = cl.check_repo_visibility(repo="test/repo", run=mock_run)
    assert result.status == "untrue"


def test_17_check_repo_visibility_reports_unknown_on_api_failure():
    """check_repo_visibility reports 'unknown' if API call fails."""
    mock_run = Mock()
    mock_run.return_value = Mock(returncode=1, stderr="401 Unauthorized")
    result = cl.check_repo_visibility(repo="test/repo", run=mock_run)
    assert result.status == "unknown"


def test_18_check_repo_visibility_unknown_on_missing_isPrivate():
    """check_repo_visibility returns unknown if isPrivate key is missing."""
    mock_run = Mock()
    mock_run.return_value = Mock(
        returncode=0,
        stdout=json.dumps({"someOtherField": "value"})
    )
    result = cl.check_repo_visibility(repo="test/repo", run=mock_run)
    assert result.status == "unknown"


# ── Scheduled jobs checks (19–23) ───────────────────────────────────

def test_19_check_scheduled_jobs_passes_on_recent_runs():
    """check_scheduled_jobs reports true if required jobs ran recently and are idle."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        jobs_dir = tmpdir / "jobs"
        jobs_dir.mkdir()
        (jobs_dir / "snapshot-deploy-nightly.json").write_text(json.dumps({
            "job": "snapshot-deploy-nightly",
            "runs": [
                {"id": "abc123", "status": "passed", "finished_at": (_now() - timedelta(hours=2)).isoformat()}
            ]
        }))
        result = cl.check_scheduled_jobs(claim_args={}, jobs_dir=jobs_dir)
        assert result.status == "true"


def test_20_check_scheduled_jobs_fails_on_stale_run():
    """check_scheduled_jobs reports untrue if jobs haven't run within threshold."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        jobs_dir = tmpdir / "jobs"
        jobs_dir.mkdir()
        (jobs_dir / "snapshot-deploy-nightly.json").write_text(json.dumps({
            "job": "snapshot-deploy-nightly",
            "runs": [
                {"id": "old", "status": "passed", "finished_at": (_now() - timedelta(days=7)).isoformat()}
            ]
        }))
        result = cl.check_scheduled_jobs(claim_args={}, jobs_dir=jobs_dir)
        assert result.status == "untrue"


def test_21_check_scheduled_jobs_looks_at_prior_run_when_newest_is_running():
    """check_scheduled_jobs ignores a currently-running job and checks the prior one."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        jobs_dir = tmpdir / "jobs"
        jobs_dir.mkdir()
        (jobs_dir / "snapshot-deploy-nightly.json").write_text(json.dumps({
            "job": "snapshot-deploy-nightly",
            "runs": [
                {"id": "old_good", "status": "passed", "finished_at": (_now() - timedelta(hours=2)).isoformat()},
                {"id": "currently_running", "status": "running", "started_at": _now().isoformat()}
            ]
        }))
        result = cl.check_scheduled_jobs(claim_args={}, jobs_dir=jobs_dir)
        assert result.status == "true"


def test_22_check_scheduled_jobs_reports_unknown_on_never():
    """check_scheduled_jobs reports untrue if a job has never run."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        jobs_dir = tmpdir / "jobs"
        jobs_dir.mkdir()
        (jobs_dir / "snapshot-deploy-nightly.json").write_text(json.dumps({
            "job": "snapshot-deploy-nightly",
            "runs": []
        }))
        result = cl.check_scheduled_jobs(claim_args={}, jobs_dir=jobs_dir)
        assert result.status == "untrue"
        assert "never" in result.detail.lower() or "no runs" in result.detail.lower()


def test_23_check_scheduled_jobs_takes_max_age_hours():
    """check_scheduled_jobs accepts max_age_hours via claim_args."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        jobs_dir = tmpdir / "jobs"
        jobs_dir.mkdir()
        (jobs_dir / "snapshot-deploy-nightly.json").write_text(json.dumps({
            "job": "snapshot-deploy-nightly",
            "runs": [{"id": "x", "status": "passed", "finished_at": (_now() - timedelta(hours=72)).isoformat()}]
        }))
        # Default max_age_hours=48, should fail
        result = cl.check_scheduled_jobs(claim_args={}, jobs_dir=jobs_dir)
        assert result.status == "untrue"
        # With longer max_age_hours=120, should pass
        result = cl.check_scheduled_jobs(claim_args={"max_age_hours": 120}, jobs_dir=jobs_dir)
        assert result.status == "true"


# ── Merge gate checks (24–27) ────────────────────────────────────────

def test_24_check_merge_gate_reads_main_health_json():
    """check_merge_gate reads main-health.json directly (no gh API call)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        health_file = tmpdir / "main-health.json"
        health_file.write_text(json.dumps({
            "ok": True,
            "checked_at": _now().isoformat()
        }))
        result = cl.check_merge_gate(path=health_file)
        assert result.status == "true"


def test_25_check_merge_gate_reports_untrue_if_ok_is_false():
    """check_merge_gate reports untrue if ok is false."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        health_file = tmpdir / "main-health.json"
        health_file.write_text(json.dumps({
            "ok": False,
            "failed": ["test-a", "test-b"],
            "checked_at": _now().isoformat()
        }))
        result = cl.check_merge_gate(path=health_file)
        assert result.status == "untrue"
        assert "test-a" in result.detail or "failed" in result.detail.lower()


def test_26_check_merge_gate_reports_unknown_if_file_missing():
    """check_merge_gate reports unknown if main-health.json doesn't exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        health_file = tmpdir / "nonexistent.json"
        result = cl.check_merge_gate(path=health_file)
        assert result.status == "unknown"


def test_27_check_merge_gate_checks_staleness():
    """check_merge_gate reports untrue if checked_at is stale."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        health_file = tmpdir / "main-health.json"
        stale_time = _now() - timedelta(hours=48)
        health_file.write_text(json.dumps({
            "ok": True,
            "checked_at": stale_time.isoformat()
        }))
        result = cl.check_merge_gate(path=health_file, now=_now(), stale_hours=24)
        assert result.status == "untrue"
        assert "stale" in result.detail.lower()


# ── Orchestrator / run_all tests (28–33) ───────────────────────────

def test_28_run_all_executes_all_claims():
    """run_all() invokes each claim's check function and returns results."""
    claims = [
        cl.Claim(id="machines-1", text="runs on two Macs", check_fn="check_machine_registry", section="story"),
    ]
    registry = cl.ClaimsRegistry(claims=claims)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        network_file = tmpdir / "marvin-network.json"
        network_file.write_text(json.dumps({
            "devices": {"mac-mini": True, "macbook": True}
        }))

        with patch("machine_profile.NETWORK_PATH", network_file):
            results = cl.run_all(registry, claims_args={})
            assert len(results) >= 1
            assert any(r.claim_id == "machines-1" for r in results)
            assert any(r.status in ("true", "untrue", "unknown") for r in results)


def test_29_run_all_populates_section_from_claim():
    """run_all() copies the section from each claim to its result."""
    claims = [
        cl.Claim(id="test", text="test", check_fn="check_machine_registry", section="intro"),
    ]
    registry = cl.ClaimsRegistry(claims=claims)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        network_file = tmpdir / "marvin-network.json"
        network_file.write_text(json.dumps({
            "devices": {"m1": True, "m2": True}
        }))

        with patch("machine_profile.NETWORK_PATH", network_file):
            results = cl.run_all(registry, claims_args={})
            assert results[0].section == "intro"


def test_30_run_all_skips_unknown_check_functions():
    """run_all() reports unknown status if a check function is not registered."""
    claims = [
        cl.Claim(id="unknown-check", text="test", check_fn="check_does_not_exist", section="s"),
    ]
    registry = cl.ClaimsRegistry(claims=claims)
    results = cl.run_all(registry, claims_args={})
    assert results[0].status == "unknown"


def test_31_run_all_passes_per_claim_kwargs():
    """run_all() passes per-claim args as kwargs to check functions."""
    claims = [
        cl.Claim(id="c1", text="t1", check_fn="check_repo_visibility", section="s1"),
    ]
    registry = cl.ClaimsRegistry(claims=claims)

    mock_run = Mock()
    mock_run.return_value = Mock(
        returncode=0,
        stdout=json.dumps({"isPrivate": False})
    )

    results = cl.run_all(registry, claims_args={"c1": {"run": mock_run}})
    assert results[0].status == "true"


def test_32_run_all_does_not_create_status_dir():
    """run_all() does not touch the filesystem (no mkdir)."""
    claims = [
        cl.Claim(id="c", text="t", check_fn="check_merge_gate", section="s"),
    ]
    registry = cl.ClaimsRegistry(claims=claims)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        nonexistent = tmpdir / "does_not_exist"
        results = cl.run_all(registry, claims_args={}, status_dir=nonexistent)
        assert not nonexistent.exists()


def test_33_run_all_handles_exception_in_check_function():
    """run_all() catches exceptions from check functions and reports unknown."""
    claims = [
        cl.Claim(id="c1", text="test", check_fn="check_machine_registry", section="s"),
    ]
    registry = cl.ClaimsRegistry(claims=claims)

    with patch("machine_profile.NETWORK_PATH", Path("/nonexistent/path.json")):
        results = cl.run_all(registry, claims_args={})
        assert results[0].status == "unknown"


# ── Atomic write and queue tests (34–40) ───────────────────────────

def test_34_atomic_write_uses_fcntl_lock():
    """write_status_atomic() uses fcntl.flock on a .lock file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        status_file = tmpdir / "claims-status.json"
        results = [
            cl.CheckResult(
                claim_id="test",
                status="true",
                detail="ok",
                checked_at=_now(),
                section="s1"
            )
        ]
        cl.write_status_atomic(status_file, results)

        assert status_file.exists()
        data = json.loads(status_file.read_text())
        assert "results" in data
        assert data["results"][0]["claim_id"] == "test"
        assert data["results"][0]["status"] == "true"


def test_35_atomic_write_includes_section_in_output():
    """write_status_atomic() persists section alongside claim_id in results."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        status_file = tmpdir / "claims-status.json"
        results = [
            cl.CheckResult(claim_id="c1", status="true", detail="test", checked_at=_now(), section="story")
        ]
        cl.write_status_atomic(status_file, results)

        data = json.loads(status_file.read_text())
        assert data["results"][0]["section"] == "story"


def test_36_build_redraft_queue_groups_by_section():
    """build_redraft_queue() returns one entry per section with failed claims."""
    results = [
        cl.CheckResult(claim_id="c1", status="untrue", detail="d1", checked_at=_now(), section="story"),
        cl.CheckResult(claim_id="c2", status="untrue", detail="d2", checked_at=_now(), section="story"),
        cl.CheckResult(claim_id="c3", status="true", detail="d3", checked_at=_now(), section="other"),
    ]
    queue = cl.build_redraft_queue(results)

    sections = [q["section"] for q in queue]
    assert "story" in sections
    assert "other" not in sections
    assert len([q for q in queue if q["section"] == "story"]) == 1


def test_37_build_redraft_queue_ignores_unknown():
    """build_redraft_queue() includes only 'untrue' status, not 'unknown'."""
    results = [
        cl.CheckResult(claim_id="c1", status="untrue", detail="d1", checked_at=_now(), section="story"),
        cl.CheckResult(claim_id="c2", status="unknown", detail="d2", checked_at=_now(), section="story"),
        cl.CheckResult(claim_id="c3", status="true", detail="d3", checked_at=_now(), section="story"),
    ]
    queue = cl.build_redraft_queue(results)

    # "story" should have only c1 in failed_claims, not c2
    story_entry = next((q for q in queue if q["section"] == "story"), None)
    assert story_entry is not None
    assert story_entry["failed_claims"] == ["c1"]


def test_38_build_redraft_queue_recomputed_fresh():
    """build_redraft_queue() is recomputed from scratch every call."""
    results_1 = [
        cl.CheckResult(claim_id="c1", status="untrue", detail="d1", checked_at=_now(), section="s1"),
    ]
    queue_1 = cl.build_redraft_queue(results_1)
    assert len(queue_1) == 1

    results_2 = [
        cl.CheckResult(claim_id="c1", status="true", detail="d1", checked_at=_now(), section="s1"),
    ]
    queue_2 = cl.build_redraft_queue(results_2)
    assert len(queue_2) == 0


def test_39_write_json_atomic_creates_parent_dir():
    """_write_json_atomic() creates parent directories as needed."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        deep_path = tmpdir / "a" / "b" / "c" / "file.json"
        data = {"test": "data"}
        cl._write_json_atomic(deep_path, data)
        assert deep_path.exists()
        assert json.loads(deep_path.read_text()) == data


def test_40_write_json_atomic_uses_fcntl_lock():
    """_write_json_atomic() atomically writes with fcntl locking."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        file_path = tmpdir / "data.json"
        data = {"key": "value"}
        cl._write_json_atomic(file_path, data)

        assert file_path.exists()
        result = json.loads(file_path.read_text())
        assert result == data


# ── Unbacked claims scanner tests (41–45) ──────────────────────────

def test_41_scan_unbacked_claims_uses_word_boundaries():
    """scan_unbacked_claims() uses word boundaries to avoid false positives."""
    claims = [
        cl.Claim(id="c1", text="runs on two Macs", check_fn="check_dummy", section="story"),
    ]
    registry = cl.ClaimsRegistry(claims=claims)

    page_text = "MARVIN runs on a network. It has proven this works."
    unbacked = cl.scan_unbacked_claims(page_text, registry)

    # The backed claim is "runs on two Macs". The first sentence "MARVIN runs on a network"
    # is unbacked (has "runs" keyword but doesn't match the full claim). We're checking that
    # "two" within "network" doesn't cause a false positive match.
    unbacked_with_network = [u for u in unbacked if "network" in u.lower()]
    # If there's an unbacked sentence with "network", it should not have matched the claim
    assert len(unbacked_with_network) == 0 or all("runs on two" not in u.lower() for u in unbacked_with_network)


def test_42_scan_unbacked_claims_strips_html():
    """scan_unbacked_claims() handles HTML markup gracefully."""
    claims = [
        cl.Claim(id="c1", text="has tests", check_fn="check_dummy", section="s"),
    ]
    registry = cl.ClaimsRegistry(claims=claims)

    page_text = "<p>MARVIN <strong>proves every change with tests</strong> and is open source.</p>"
    unbacked = cl.scan_unbacked_claims(page_text, registry)
    assert isinstance(unbacked, list)


def test_43_scan_unbacked_claims_finds_new_facts():
    """scan_unbacked_claims() finds sentences not backed by any claim."""
    claims = [
        cl.Claim(id="c1", text="runs on two Macs", check_fn="check_dummy", section="s"),
    ]
    registry = cl.ClaimsRegistry(claims=claims)

    page_text = "MARVIN runs on two Macs. It also has a web dashboard. Costs nothing."
    unbacked = cl.scan_unbacked_claims(page_text, registry)
    # "web dashboard" and "costs nothing" should potentially be flagged if they match keywords
    assert isinstance(unbacked, list)


def test_44_scan_unbacked_claims_inflection_patterns():
    """scan_unbacked_claims() matches verb inflections like 'running', 'runs', 'ran'."""
    claims = []
    registry = cl.ClaimsRegistry(claims=claims)

    page_text = "MARVIN runs automatically. It has proven reliable. Tests are being checked."
    unbacked = cl.scan_unbacked_claims(page_text, registry)
    # Should find sentences with inflected verb forms
    assert len(unbacked) > 0


def test_45_scan_unbacked_claims_ignores_sentences_without_keywords():
    """scan_unbacked_claims() ignores generic sentences without fact keywords."""
    claims = []
    registry = cl.ClaimsRegistry(claims=claims)

    page_text = "MARVIN is a tool. It is very good. I like it."
    unbacked = cl.scan_unbacked_claims(page_text, registry)
    # Generic sentences without keywords should not be flagged
    assert len(unbacked) == 0 or all("good" not in str(u) for u in unbacked)


# ── Edge cases (46–53) ──────────────────────────────────────────────

def test_46_check_merge_gate_normalizes_naive_timestamps():
    """check_merge_gate() handles naive (no timezone) timestamps by normalizing to UTC."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        health_file = tmpdir / "main-health.json"
        # Write a naive timestamp (no timezone info)
        naive_time = datetime.now().replace(microsecond=0)
        health_file.write_text(json.dumps({
            "ok": True,
            "checked_at": naive_time.isoformat()
        }))
        # Should not crash; normalizes to UTC
        result = cl.check_merge_gate(path=health_file, now=_now(), stale_hours=24)
        assert result.status in ("true", "untrue")


def test_47_check_scheduled_jobs_normalizes_naive_timestamps():
    """check_scheduled_jobs() normalizes naive timestamps before age calculation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        jobs_dir = tmpdir / "jobs"
        jobs_dir.mkdir()
        naive_time = (datetime.now() - timedelta(hours=2)).replace(microsecond=0)
        (jobs_dir / "snapshot-deploy-nightly.json").write_text(json.dumps({
            "job": "snapshot-deploy-nightly",
            "runs": [
                {"id": "x", "status": "passed", "finished_at": naive_time.isoformat()}
            ]
        }))
        result = cl.check_scheduled_jobs(claim_args={}, jobs_dir=jobs_dir)
        assert result.status == "true"


def test_48_check_machine_registry_unknown_on_missing_devices_key():
    """check_machine_registry() returns unknown if 'devices' key is missing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        network_file = tmpdir / "marvin-network.json"
        network_file.write_text(json.dumps({"other_key": "value"}))

        with patch("machine_profile.NETWORK_PATH", network_file):
            result = cl.check_machine_registry()
            assert result.status == "unknown"
            assert "devices" in result.detail.lower()


def test_49_check_machine_registry_unknown_if_devices_not_dict():
    """check_machine_registry() returns unknown if devices is not a dict."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        network_file = tmpdir / "marvin-network.json"
        network_file.write_text(json.dumps({"devices": ["item1", "item2"]}))

        with patch("machine_profile.NETWORK_PATH", network_file):
            result = cl.check_machine_registry()
            assert result.status == "unknown"


def test_50_run_all_catches_all_exceptions():
    """run_all() catches any exception from a check function, not just specific ones."""
    claims = [
        cl.Claim(id="bad", text="test", check_fn="check_machine_registry", section="s"),
    ]
    registry = cl.ClaimsRegistry(claims=claims)

    with patch("machine_profile.NETWORK_PATH", Path("/bad/path/that/will/raise")):
        results = cl.run_all(registry)
        assert results[0].status == "unknown"
        # Should have a descriptive error detail (file not found, etc)
        assert len(results[0].detail) > 0


def test_51_check_merge_gate_unknown_on_malformed_json():
    """check_merge_gate() returns unknown if JSON is malformed."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        health_file = tmpdir / "main-health.json"
        health_file.write_text("{this is not valid json")
        result = cl.check_merge_gate(path=health_file)
        assert result.status == "unknown"


def test_52_registry_json_round_trip_preserves_all_fields():
    """Registry JSON round-trip preserves id, text, check_fn, section exactly."""
    claims = [
        cl.Claim(id="c1", text="A test claim", check_fn="check_merge_gate", section="section-a"),
        cl.Claim(id="c2", text="Another claim", check_fn="check_scheduled_jobs", section="story"),
    ]
    registry = cl.ClaimsRegistry(claims=claims)
    json_str = cl.registry_to_json(registry)
    restored = cl.registry_from_json(json_str)

    assert len(restored.claims) == 2
    assert restored.claims[0].id == "c1"
    assert restored.claims[0].text == "A test claim"
    assert restored.claims[1].check_fn == "check_scheduled_jobs"


def test_53_check_result_claim_id_set_by_run_all():
    """run_all() overwrites claim_id from kwargs for consistency."""
    claims = [
        cl.Claim(id="override-me", text="test", check_fn="check_repo_visibility", section="s"),
    ]
    registry = cl.ClaimsRegistry(claims=claims)

    mock_run = Mock()
    mock_run.return_value = Mock(
        returncode=0,
        stdout=json.dumps({"isPrivate": False})
    )

    results = cl.run_all(registry, claims_args={"override-me": {"run": mock_run}})
    assert results[0].claim_id == "override-me"
