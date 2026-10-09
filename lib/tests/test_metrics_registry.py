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
