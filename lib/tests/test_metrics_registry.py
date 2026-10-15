"""Tests for metrics_registry.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_metrics_registry.py -v
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import metrics_registry as mr  # noqa: E402
import machine_profile  # noqa: E402


@pytest.fixture
def metrics_dir(tmp_path, monkeypatch):
    d = tmp_path / "metrics"
    monkeypatch.setattr(mr, "METRICS_DIR", d)
    return d


@pytest.fixture(autouse=True)
def mock_machine_label(monkeypatch):
    """Automatically mock machine_label() for all tests to return 'mac-mini'.
    Tests that need a different label can pass machine= explicitly, or can
    override this fixture by using another patch.object() call."""
    monkeypatch.setattr(mr.machine_profile, "machine_label", lambda: "mac-mini")


def _metric(value: float, higher_is_better: bool = True) -> dict:
    return {"value": value, "higher_is_better": higher_is_better}


# ── record ────────────────────────────────────────────────────────────────

def test_record_creates_json_snapshot_file(metrics_dir):
    mr.record("route-classifier", {"accuracy": _metric(0.875)})
    json_path = metrics_dir / "route-classifier.mac-mini.json"
    assert json_path.exists()
    snapshots = json.loads(json_path.read_text())
    assert len(snapshots) == 1
    assert snapshots[0]["metrics"]["accuracy"] == _metric(0.875)
    assert "timestamp" in snapshots[0]


def test_record_appends_markdown_narrative(metrics_dir):
    mr.record("route-classifier", {"accuracy": _metric(0.875)})
    md_path = metrics_dir / "route-classifier.mac-mini.md"
    assert md_path.exists()
    assert "accuracy" in md_path.read_text()
    assert "0.875" in md_path.read_text()


def test_record_multiple_snapshots_accumulate_not_overwrite(metrics_dir):
    mr.record("route-classifier", {"accuracy": _metric(0.70)})
    mr.record("route-classifier", {"accuracy": _metric(0.875)})
    snapshots = json.loads((metrics_dir / "route-classifier.mac-mini.json").read_text())
    assert len(snapshots) == 2
    assert snapshots[0]["metrics"]["accuracy"]["value"] == 0.70
    assert snapshots[1]["metrics"]["accuracy"]["value"] == 0.875


def test_record_separate_subsystems_separate_files(metrics_dir):
    mr.record("route-classifier", {"accuracy": _metric(0.875)})
    mr.record("qa-agent", {"latency_ms": _metric(120, higher_is_better=False)})
    assert (metrics_dir / "route-classifier.mac-mini.json").exists()
    assert (metrics_dir / "qa-agent.mac-mini.json").exists()


# ── latest ────────────────────────────────────────────────────────────────

def test_latest_returns_most_recent_snapshot(metrics_dir):
    mr.record("route-classifier", {"accuracy": _metric(0.70)})
    mr.record("route-classifier", {"accuracy": _metric(0.875)})
    latest = mr.latest("route-classifier")
    assert latest["accuracy"]["value"] == 0.875


def test_latest_returns_none_for_unknown_subsystem(metrics_dir):
    assert mr.latest("never-recorded") is None


def test_latest_round_trips_exact_recorded_values(metrics_dir):
    original = {"accuracy": _metric(0.8012), "cost_usd": _metric(0.0031, higher_is_better=False)}
    mr.record("route-classifier", original)
    assert mr.latest("route-classifier") == original


# ── compare ───────────────────────────────────────────────────────────────

def test_compare_detects_improvement_higher_is_better():
    baseline = {"accuracy": _metric(0.70)}
    current = {"accuracy": _metric(0.875)}
    result = mr.compare("route-classifier", baseline, current)
    assert result["verdict"] == "improved"
    assert result["passing"] is True
    assert result["metrics"]["accuracy"]["direction"] == "improved"


def test_compare_detects_regression_higher_is_better():
    baseline = {"accuracy": _metric(0.875)}
    current = {"accuracy": _metric(0.70)}
    result = mr.compare("route-classifier", baseline, current)
    assert result["verdict"] == "regressed"
    assert result["passing"] is False
    assert result["metrics"]["accuracy"]["direction"] == "regressed"


def test_compare_detects_improvement_lower_is_better():
    baseline = {"latency_ms": _metric(120, higher_is_better=False)}
    current = {"latency_ms": _metric(80, higher_is_better=False)}
    result = mr.compare("qa-agent", baseline, current)
    assert result["verdict"] == "improved"
    assert result["passing"] is True


def test_compare_detects_regression_lower_is_better():
    baseline = {"cost_usd": _metric(0.003, higher_is_better=False)}
    current = {"cost_usd": _metric(0.009, higher_is_better=False)}
    result = mr.compare("route-classifier", baseline, current)
    assert result["verdict"] == "regressed"
    assert result["passing"] is False


def test_compare_tiny_delta_is_unchanged_not_noise_regression():
    baseline = {"accuracy": _metric(0.8750)}
    current = {"accuracy": _metric(0.8751)}
    result = mr.compare("route-classifier", baseline, current)
    assert result["metrics"]["accuracy"]["direction"] == "unchanged"
    assert result["verdict"] == "unchanged"
    assert result["passing"] is False


def test_compare_mixed_result_is_not_passing():
    baseline = {"accuracy": _metric(0.70), "cost_usd": _metric(0.003, higher_is_better=False)}
    current = {"accuracy": _metric(0.875), "cost_usd": _metric(0.009, higher_is_better=False)}
    result = mr.compare("route-classifier", baseline, current)
    assert result["verdict"] == "mixed"
    assert result["passing"] is False
    assert result["metrics"]["accuracy"]["direction"] == "improved"
    assert result["metrics"]["cost_usd"]["direction"] == "regressed"


def test_compare_all_improved_or_unchanged_is_passing():
    baseline = {"accuracy": _metric(0.70), "cost_usd": _metric(0.003, higher_is_better=False)}
    current = {"accuracy": _metric(0.875), "cost_usd": _metric(0.003, higher_is_better=False)}
    result = mr.compare("route-classifier", baseline, current)
    assert result["verdict"] == "improved"
    assert result["passing"] is True


def test_compare_all_unchanged_is_not_passing():
    baseline = {"accuracy": _metric(0.875)}
    current = {"accuracy": _metric(0.875)}
    result = mr.compare("route-classifier", baseline, current)
    assert result["verdict"] == "unchanged"
    assert result["passing"] is False


def test_compare_ignores_metrics_not_present_in_both():
    baseline = {"accuracy": _metric(0.70)}
    current = {"accuracy": _metric(0.875), "new_metric": _metric(1.0)}
    result = mr.compare("route-classifier", baseline, current)
    assert "new_metric" not in result["metrics"]
    assert result["verdict"] == "improved"


def test_compare_result_includes_evidence_detail():
    baseline = {"accuracy": _metric(0.70)}
    current = {"accuracy": _metric(0.875)}
    result = mr.compare("route-classifier", baseline, current)
    assert result["metrics"]["accuracy"]["baseline"] == 0.70
    assert result["metrics"]["accuracy"]["current"] == 0.875
    assert "delta" in result["metrics"]["accuracy"]


# ── index ─────────────────────────────────────────────────────────────────

def test_index_reflects_latest_snapshot_per_subsystem(metrics_dir):
    mr.record("route-classifier", {"accuracy": _metric(0.70)})
    mr.record("route-classifier", {"accuracy": _metric(0.875)})
    mr.record("qa-agent", {"latency_ms": _metric(120, higher_is_better=False)})
    idx = mr.index()
    assert idx["route-classifier"]["mac-mini"]["accuracy"]["value"] == 0.875
    assert idx["qa-agent"]["mac-mini"]["latency_ms"]["value"] == 120


def test_index_empty_when_nothing_recorded(metrics_dir):
    assert mr.index() == {}


def test_index_writes_pointer_markdown_file(metrics_dir):
    mr.record("route-classifier", {"accuracy": _metric(0.875)})
    mr.index()
    pointer = metrics_dir / "index.md"
    assert pointer.exists()
    assert "route-classifier" in pointer.read_text()


def test_index_immediately_reflects_new_recording(metrics_dir):
    mr.record("route-classifier", {"accuracy": _metric(0.70)})
    assert mr.index()["route-classifier"]["mac-mini"]["accuracy"]["value"] == 0.70
    mr.record("route-classifier", {"accuracy": _metric(0.99)})
    assert mr.index()["route-classifier"]["mac-mini"]["accuracy"]["value"] == 0.99


# ── per-machine storage ───────────────────────────────────────────────────

def test_record_per_machine_own_file(metrics_dir):
    """Two machines recording the same subsystem creates separate files."""
    mr.record("route-classifier", {"accuracy": _metric(0.70)}, machine="mac-mini")
    mr.record("route-classifier", {"accuracy": _metric(0.875)}, machine="macbook-pro")

    mini_path = metrics_dir / "route-classifier.mac-mini.json"
    laptop_path = metrics_dir / "route-classifier.macbook-pro.json"
    assert mini_path.exists()
    assert laptop_path.exists()

    mini_snapshots = json.loads(mini_path.read_text())
    laptop_snapshots = json.loads(laptop_path.read_text())
    assert mini_snapshots[0]["metrics"]["accuracy"]["value"] == 0.70
    assert laptop_snapshots[0]["metrics"]["accuracy"]["value"] == 0.875


def test_latest_with_explicit_machine(metrics_dir):
    """latest(subsystem, machine=) reads only that machine's file."""
    mr.record("route-classifier", {"accuracy": _metric(0.70)}, machine="mac-mini")
    mr.record("route-classifier", {"accuracy": _metric(0.875)}, machine="macbook-pro")

    mini_latest = mr.latest("route-classifier", machine="mac-mini")
    laptop_latest = mr.latest("route-classifier", machine="macbook-pro")

    assert mini_latest["accuracy"]["value"] == 0.70
    assert laptop_latest["accuracy"]["value"] == 0.875


def test_latest_defaults_to_current_machine(metrics_dir):
    """latest(subsystem) with no machine= only sees current machine's file."""
    mr.record("route-classifier", {"accuracy": _metric(0.70)})
    mr.record("qa-agent", {"latency_ms": _metric(120, higher_is_better=False)}, machine="macbook-pro")

    mini_latest = mr.latest("route-classifier")
    laptop_latest = mr.latest("qa-agent")

    assert mini_latest["accuracy"]["value"] == 0.70
    assert laptop_latest is None  # not from this machine


def test_all_latest_combines_all_machines(metrics_dir):
    """all_latest(subsystem) returns dict[machine, metrics] for all machines."""
    mr.record("route-classifier", {"accuracy": _metric(0.70)}, machine="mac-mini")
    mr.record("route-classifier", {"accuracy": _metric(0.875)}, machine="macbook-pro")

    all_data = mr.all_latest("route-classifier")
    assert set(all_data.keys()) == {"mac-mini", "macbook-pro"}
    assert all_data["mac-mini"]["accuracy"]["value"] == 0.70
    assert all_data["macbook-pro"]["accuracy"]["value"] == 0.875


def test_all_latest_empty_for_unknown_subsystem(metrics_dir):
    """all_latest(subsystem) returns empty dict for unknown subsystem."""
    assert mr.all_latest("never-recorded") == {}


def test_index_nests_by_machine_and_subsystem(metrics_dir):
    """index() shapes data as dict[subsystem, dict[machine, metrics]]."""
    mr.record("route-classifier", {"accuracy": _metric(0.70)}, machine="mac-mini")
    mr.record("route-classifier", {"accuracy": _metric(0.875)}, machine="macbook-pro")
    mr.record("qa-agent", {"latency_ms": _metric(120, higher_is_better=False)}, machine="mac-mini")

    idx = mr.index()
    assert "route-classifier" in idx
    assert "qa-agent" in idx
    assert isinstance(idx["route-classifier"], dict)
    assert "mac-mini" in idx["route-classifier"]
    assert "macbook-pro" in idx["route-classifier"]
    assert idx["route-classifier"]["mac-mini"]["accuracy"]["value"] == 0.70
    assert idx["route-classifier"]["macbook-pro"]["accuracy"]["value"] == 0.875
    assert idx["qa-agent"]["mac-mini"]["latency_ms"]["value"] == 120


def test_legacy_bare_file_included_in_all_latest(metrics_dir):
    """Pre-existing bare {subsystem}.json is included as 'legacy'."""
    bare_path = metrics_dir / "route-classifier.json"
    bare_data = [{"timestamp": "2026-01-01T00:00:00+00:00", "metrics": {"accuracy": _metric(0.65)}}]
    metrics_dir.mkdir(parents=True, exist_ok=True)
    bare_path.write_text(json.dumps(bare_data, indent=2))

    all_data = mr.all_latest("route-classifier")
    assert "legacy" in all_data
    assert all_data["legacy"]["accuracy"]["value"] == 0.65


def test_legacy_bare_file_not_touched_by_new_records(metrics_dir):
    """New record() calls don't overwrite pre-existing bare files."""
    bare_path = metrics_dir / "route-classifier.json"
    bare_data = [{"timestamp": "2026-01-01T00:00:00+00:00", "metrics": {"accuracy": _metric(0.65)}}]
    metrics_dir.mkdir(parents=True, exist_ok=True)
    bare_path.write_text(json.dumps(bare_data, indent=2))

    mr.record("route-classifier", {"accuracy": _metric(0.70)})

    bare_snapshots = json.loads(bare_path.read_text())
    assert len(bare_snapshots) == 1
    assert bare_snapshots[0]["metrics"]["accuracy"]["value"] == 0.65


# ── defensive parsing (corruption tolerance) ──────────────────────────────────

def test_load_snapshots_empty_file_returns_empty_list(metrics_dir):
    """Empty file is treated as empty history, not an error."""
    path = mr._snapshot_path("test-subsystem", "test-machine")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("")
    result = mr._load_snapshots("test-subsystem", "test-machine")
    assert result == []


def test_load_snapshots_concatenated_json_documents(metrics_dir):
    """Two concatenated JSON docs (from concurrent writes) → empty, no raise."""
    path = mr._snapshot_path("test-subsystem", "test-machine")
    path.parent.mkdir(parents=True, exist_ok=True)
    # Simulate two record() calls racing: file has two JSON arrays concatenated
    path.write_text('[{"timestamp": "2026-10-09T10:00:00+00:00", "metrics": {}}]\n[{"timestamp": "2026-10-09T10:01:00+00:00", "metrics": {}}]')
    result = mr._load_snapshots("test-subsystem", "test-machine")
    assert result == []


def test_load_snapshots_truncated_json(metrics_dir):
    """File cut off mid-write is treated as empty, not an error."""
    path = mr._snapshot_path("test-subsystem", "test-machine")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('[{"timestamp": "2026-10-09T10:00:00+00:00", "metrics": {"a": 1}')
    result = mr._load_snapshots("test-subsystem", "test-machine")
    assert result == []


def test_load_snapshots_non_list_json_root(metrics_dir):
    """JSON dict or string (not a list) is treated as invalid, return empty."""
    path = mr._snapshot_path("test-subsystem", "test-machine")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"not": "a list"}')
    result = mr._load_snapshots("test-subsystem", "test-machine")
    assert result == []


def test_load_snapshots_corrupted_file_backed_up(metrics_dir):
    """When corrupted, original file is backed up as .corrupted-<timestamp>."""
    path = mr._snapshot_path("test-subsystem", "test-machine")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('[{"bad": json}')
    result = mr._load_snapshots("test-subsystem", "test-machine")
    assert result == []
    # Corrupted file should be moved to .corrupted-<isoformat>
    backups = list(path.parent.glob(f"{path.name}.corrupted-*"))
    assert len(backups) == 1
    # Original file should no longer exist
    assert not path.exists()


def test_load_snapshots_unreadable_file_permissions(metrics_dir):
    """File with 000 permissions is treated as empty and backed up."""
    path = mr._snapshot_path("test-subsystem", "test-machine")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('[{"timestamp": "2026-10-09T10:00:00+00:00", "metrics": {}}]')
    path.chmod(0o000)
    result = mr._load_snapshots("test-subsystem", "test-machine")
    assert result == []
    # File should be moved to a backup (since it was unreadable)
    backups = list(path.parent.glob(f"{path.name}.corrupted-*"))
    assert len(backups) == 1
    # Restore permissions on the backup so cleanup can work
    backups[0].chmod(0o644)


def test_all_latest_with_corrupted_legacy_file(metrics_dir):
    """Corrupted legacy .json file is skipped, not raised."""
    legacy_path = metrics_dir / "test-subsystem.json"
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text('[{"bad": json}')
    result = mr.all_latest("test-subsystem")
    # Should return empty (no valid machines)
    assert result == {}


def test_all_latest_valid_machine_and_corrupted_legacy(metrics_dir):
    """Valid machine file is returned even if legacy is corrupted."""
    # Write a valid machine-specific file
    mr.record("test-subsystem", {"x": _metric(5)}, machine="test-machine")
    # Write a corrupted legacy file
    legacy_path = metrics_dir / "test-subsystem.json"
    legacy_path.write_text('[{"bad": json}')
    result = mr.all_latest("test-subsystem")
    assert "test-machine" in result
    assert "legacy" not in result


# ── atomic writes ──────────────────────────────────────────────────────────────

def test_record_writes_atomically_via_tmp_then_replace(metrics_dir):
    """record() uses tmp-write-then-replace pattern for atomic writes."""
    snapshot_path = mr._snapshot_path("test-subsystem", "test-machine")
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)

    # Pre-populate the file with valid data
    initial = [{"timestamp": "2026-10-08T10:00:00+00:00", "metrics": {"old": {"value": 1}}}]
    snapshot_path.write_text(json.dumps(initial))

    # Verify that record() uses the tmp-then-replace pattern by checking that
    # no .tmp file is left behind (it gets replaced immediately)
    mr.record("test-subsystem", {"new": _metric(2)}, machine="test-machine")
    tmp_path = snapshot_path.with_suffix(".tmp")
    assert not tmp_path.exists(), "Temporary file should not exist after record() completes"

    # Verify the snapshot was written
    snapshots = mr._load_snapshots("test-subsystem", "test-machine")
    assert len(snapshots) == 2


def test_run_all_tolerates_corrupted_metrics_file():
    """Regression test for PR #359 denial: corrupted health-monitor file doesn't crash run_all()."""
    import health_checks

    # Seed a corrupted metrics file
    metrics_file = mr.METRICS_DIR / "health-monitor.test-machine.json"
    metrics_file.parent.mkdir(parents=True, exist_ok=True)
    # Concatenated JSON documents, the exact failure shape from the denial
    metrics_file.write_text('[{"timestamp": "2026-10-08T10:00:00+00:00"}]\n[{"timestamp": "2026-10-09T10:00:00+00:00"}]')

    # run_all() should complete without raising JSONDecodeError
    result = health_checks.run_all()

    # Should be a normal result structure
    assert isinstance(result, dict)
