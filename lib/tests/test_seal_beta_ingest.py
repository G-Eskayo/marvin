"""Tests for seal_beta_ingest.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_seal_beta_ingest.py -v
"""
from __future__ import annotations

import json
import pytest
import sys
from datetime import datetime, timezone
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import seal_beta_ingest as sbi  # noqa: E402


# ── find_report_files ────────────────────────────────────────────────────

def test_find_report_files_missing_directory():
    """Missing directory returns empty list, not error."""
    result = sbi.find_report_files(Path("/nonexistent/path"))
    assert result == []


def test_find_report_files_permission_error(tmp_path, monkeypatch):
    """Permission error on glob raises PermissionError."""
    def mock_glob(self, pattern):
        raise PermissionError("no access")

    attach_dir = tmp_path / "attachments"
    attach_dir.mkdir()
    monkeypatch.setattr(Path, "glob", mock_glob)

    with pytest.raises(PermissionError):
        sbi.find_report_files(attach_dir)


def test_find_report_files_finds_and_sorts(tmp_path, monkeypatch):
    """Finds seal-feedback-*.json files recursively and returns sorted list."""
    attach_dir = tmp_path / "attachments"
    attach_dir.mkdir()
    subdir = attach_dir / "subdir"
    subdir.mkdir()

    files = [
        attach_dir / "seal-feedback-002.json",
        subdir / "seal-feedback-001.json",
        attach_dir / "seal-feedback-003.json",
        attach_dir / "other-file.json",
    ]

    for f in files[:-1]:
        f.touch()
    files[-1].touch()

    monkeypatch.setattr(sbi, "HOME", tmp_path)
    result = sbi.find_report_files(attach_dir)

    assert len(result) == 3
    assert all("seal-feedback" in f.name for f in result)
    assert result == sorted(result)


# ── load_report ──────────────────────────────────────────────────────────

def test_load_report_missing_file():
    """Missing file returns error."""
    report, err = sbi.load_report(Path("/nonexistent/file.json"))
    assert err is not None
    assert "JSON parse error" in err or "No such file" in err


def test_load_report_invalid_json(tmp_path):
    """Invalid JSON returns parse error."""
    f = tmp_path / "bad.json"
    f.write_text("{invalid json")
    report, err = sbi.load_report(f)
    assert err is not None
    assert "JSON parse error" in err


def test_load_report_missing_schema(tmp_path):
    """Missing schema field returns error."""
    f = tmp_path / "report.json"
    data = {"device": {"model": "iPhone15,3"}, "app": {"build": "1"}, "conversations": []}
    f.write_text(json.dumps(data))
    report, err = sbi.load_report(f)
    assert err is not None
    assert "schema" in err


def test_load_report_wrong_schema_version(tmp_path):
    """Wrong schema version returns error."""
    f = tmp_path / "report.json"
    data = {"schema": 2, "device": {"model": "iPhone15,3"}, "app": {"build": "1"}, "conversations": []}
    f.write_text(json.dumps(data))
    report, err = sbi.load_report(f)
    assert err is not None
    assert "schema" in err


def test_load_report_missing_device(tmp_path):
    """Missing device field returns error."""
    f = tmp_path / "report.json"
    data = {"schema": 1, "app": {"build": "1"}, "conversations": []}
    f.write_text(json.dumps(data))
    report, err = sbi.load_report(f)
    assert err is not None
    assert "device" in err


def test_load_report_missing_device_model(tmp_path):
    """Missing device.model returns error."""
    f = tmp_path / "report.json"
    data = {"schema": 1, "device": {}, "app": {"build": "1"}, "conversations": []}
    f.write_text(json.dumps(data))
    report, err = sbi.load_report(f)
    assert err is not None
    assert "device.model" in err


def test_load_report_missing_app_build(tmp_path):
    """Missing app.build returns error."""
    f = tmp_path / "report.json"
    data = {"schema": 1, "device": {"model": "iPhone15,3"}, "app": {}, "conversations": []}
    f.write_text(json.dumps(data))
    report, err = sbi.load_report(f)
    assert err is not None
    assert "app.build" in err


def test_load_report_conversations_not_list(tmp_path):
    """conversations field must be a list."""
    f = tmp_path / "report.json"
    data = {
        "schema": 1,
        "device": {"model": "iPhone15,3"},
        "app": {"build": "1"},
        "conversations": "not a list",
    }
    f.write_text(json.dumps(data))
    report, err = sbi.load_report(f)
    assert err is not None
    assert "conversations is not a list" in err


def test_load_report_valid(tmp_path):
    """Valid report loads successfully."""
    f = tmp_path / "report.json"
    data = {
        "schema": 1,
        "device": {"model": "iPhone15,3"},
        "app": {"build": "1"},
        "conversations": [],
    }
    f.write_text(json.dumps(data))
    report, err = sbi.load_report(f)
    assert err is None
    assert report == data


# ── validate_conversation ────────────────────────────────────────────────

def _valid_conversation() -> dict:
    """Factory for a valid conversation."""
    return {
        "id": "conv-1",
        "rating": 5,
        "ratingSkipped": False,
        "lag": {"p50Seconds": 0.5, "p95Seconds": 1.0, "samples": 100},
        "rewriteRate": 0.8,
        "speakers": {"relabelsPerMinute": 0.5},
        "ending": {"kind": "natural"},
        "battery": {"dropPercentPer30Min": 5.0, "maxThermalState": "nominal"},
        "minutes": 5.0,
    }


def test_validate_conversation_valid():
    """Valid conversation passes validation."""
    row = _valid_conversation()
    is_valid, err = sbi.validate_conversation(row)
    assert is_valid
    assert err is None


def test_validate_conversation_rating_null():
    """Null rating is allowed."""
    row = _valid_conversation()
    row["rating"] = None
    is_valid, err = sbi.validate_conversation(row)
    assert is_valid
    assert err is None


def test_validate_conversation_missing_id():
    """Missing id fails validation."""
    row = _valid_conversation()
    del row["id"]
    is_valid, err = sbi.validate_conversation(row)
    assert not is_valid
    assert "missing field: id" in err


def test_validate_conversation_missing_rating():
    """Missing rating fails validation."""
    row = _valid_conversation()
    del row["rating"]
    is_valid, err = sbi.validate_conversation(row)
    assert not is_valid
    assert "missing field: rating" in err


def test_validate_conversation_missing_ratingSkipped():
    """Missing ratingSkipped fails validation."""
    row = _valid_conversation()
    del row["ratingSkipped"]
    is_valid, err = sbi.validate_conversation(row)
    assert not is_valid
    assert "missing field: ratingSkipped" in err


def test_validate_conversation_missing_lag():
    """Missing lag fails validation."""
    row = _valid_conversation()
    del row["lag"]
    is_valid, err = sbi.validate_conversation(row)
    assert not is_valid
    assert "missing field: lag" in err


def test_validate_conversation_missing_speakers():
    """Missing speakers fails validation."""
    row = _valid_conversation()
    del row["speakers"]
    is_valid, err = sbi.validate_conversation(row)
    assert not is_valid
    assert "missing field: speakers" in err


def test_validate_conversation_missing_ending():
    """Missing ending fails validation."""
    row = _valid_conversation()
    del row["ending"]
    is_valid, err = sbi.validate_conversation(row)
    assert not is_valid
    assert "missing field: ending" in err


def test_validate_conversation_missing_battery():
    """Missing battery fails validation."""
    row = _valid_conversation()
    del row["battery"]
    is_valid, err = sbi.validate_conversation(row)
    assert not is_valid
    assert "missing field: battery" in err


def test_validate_conversation_missing_minutes():
    """Missing minutes fails validation."""
    row = _valid_conversation()
    del row["minutes"]
    is_valid, err = sbi.validate_conversation(row)
    assert not is_valid
    assert "missing field: minutes" in err


def test_validate_conversation_empty_id():
    """Empty id fails validation."""
    row = _valid_conversation()
    row["id"] = ""
    is_valid, err = sbi.validate_conversation(row)
    assert not is_valid


def test_validate_conversation_non_bool_ratingSkipped():
    """Non-bool ratingSkipped fails validation."""
    row = _valid_conversation()
    row["ratingSkipped"] = "yes"
    is_valid, err = sbi.validate_conversation(row)
    assert not is_valid
    assert "ratingSkipped must be boolean" in err


def test_validate_conversation_invalid_thermal_state():
    """Invalid maxThermalState (not a valid string) fails validation."""
    row = _valid_conversation()
    row["battery"]["maxThermalState"] = "unknown"
    is_valid, err = sbi.validate_conversation(row)
    assert not is_valid
    assert "maxThermalState" in err


def test_validate_conversation_missing_lag_p50():
    """Missing lag.p50Seconds fails validation."""
    row = _valid_conversation()
    del row["lag"]["p50Seconds"]
    is_valid, err = sbi.validate_conversation(row)
    assert not is_valid
    assert "lag.p50Seconds" in err


def test_validate_conversation_missing_speakers_relabelsPerMinute():
    """Missing speakers.relabelsPerMinute fails validation."""
    row = _valid_conversation()
    del row["speakers"]["relabelsPerMinute"]
    is_valid, err = sbi.validate_conversation(row)
    assert not is_valid
    assert "speakers.relabelsPerMinute" in err


def test_validate_conversation_missing_ending_kind():
    """Missing ending.kind fails validation."""
    row = _valid_conversation()
    del row["ending"]["kind"]
    is_valid, err = sbi.validate_conversation(row)
    assert not is_valid
    assert "ending.kind" in err


def test_validate_conversation_missing_battery_dropPercentPer30Min():
    """Missing battery.dropPercentPer30Min fails validation."""
    row = _valid_conversation()
    del row["battery"]["dropPercentPer30Min"]
    is_valid, err = sbi.validate_conversation(row)
    assert not is_valid
    assert "battery.dropPercentPer30Min" in err


# ── device_plain_name ────────────────────────────────────────────────────

def test_device_plain_name_known_model():
    """Known model identifiers map to plain names."""
    assert sbi.device_plain_name("iPhone15,3") == "iPhone 15 Pro"
    assert sbi.device_plain_name("iPhone16,1") == "iPhone 16"
    assert sbi.device_plain_name("iPhone18,1") == "iPhone 17"


def test_device_plain_name_unknown_model():
    """Unknown identifier returns itself as fallback."""
    assert sbi.device_plain_name("iPhone999,9") == "iPhone999,9"


def test_device_plain_name_empty():
    """Empty identifier returns 'unknown-device'."""
    assert sbi.device_plain_name("") == "unknown-device"


# ── load_seen_ids ────────────────────────────────────────────────────────

def test_load_seen_ids_missing_file():
    """Missing reports file returns empty set."""
    result = sbi.load_seen_ids(Path("/nonexistent/reports.jsonl"))
    assert result == set()


def test_load_seen_ids_empty_file(tmp_path):
    """Empty reports file returns empty set."""
    reports = tmp_path / "reports.jsonl"
    reports.write_text("")
    result = sbi.load_seen_ids(reports)
    assert result == set()


def test_load_seen_ids_with_rows(tmp_path):
    """Loads IDs from existing reports.jsonl."""
    reports = tmp_path / "reports.jsonl"
    rows = [
        {"id": "conv-1", "rating": 5},
        {"id": "conv-2", "rating": 4},
        {"other_field": "no id here"},
    ]
    reports.write_text("\n".join(json.dumps(r) for r in rows))
    result = sbi.load_seen_ids(reports)
    assert result == {"conv-1", "conv-2"}


# ── is_low_sample ────────────────────────────────────────────────────────

def test_is_low_sample_under_30():
    """Conversation with < 30 samples is low sample."""
    conv = {"minutes": 5.0, "lag": {"samples": 5}}
    assert sbi.is_low_sample(conv) is True


def test_is_low_sample_exactly_10():
    """Conversation with exactly 10 samples is low sample (< 30 threshold)."""
    conv = {"minutes": 5.0, "lag": {"samples": 10}}
    assert sbi.is_low_sample(conv) is True


def test_is_low_sample_at_boundary_30():
    """Conversation with exactly 30 samples and >= 1.0 minute is not low sample."""
    conv = {"minutes": 1.0, "lag": {"samples": 30}}
    assert sbi.is_low_sample(conv) is False


def test_is_low_sample_over_30():
    """Conversation with > 30 samples and >= 1.0 minute is not low sample."""
    conv = {"minutes": 5.0, "lag": {"samples": 100}}
    assert sbi.is_low_sample(conv) is False


def test_is_low_sample_low_duration():
    """Conversation with < 1.0 minute duration is low sample regardless of sample count."""
    conv = {"minutes": 0.5, "lag": {"samples": 100}}
    assert sbi.is_low_sample(conv) is True


def test_is_low_sample_missing_lag():
    """Missing lag defaults to 0 samples (low sample)."""
    conv = {"minutes": 5.0}
    assert sbi.is_low_sample(conv) is True


def test_is_low_sample_missing_minutes():
    """Missing minutes defaults to 0 (low sample)."""
    conv = {"lag": {"samples": 100}}
    assert sbi.is_low_sample(conv) is True


# ── aggregate ────────────────────────────────────────────────────────────

def test_aggregate_empty_list():
    """Aggregating empty list returns zero count and None medians."""
    result = sbi.aggregate([])
    assert result["count"] == 0
    assert result["median_rating"] is None
    assert result["median_lag_p50"] is None


def test_aggregate_single_row():
    """Single row returns correct values."""
    rows = [
        {
            "rating": 5,
            "ratingSkipped": False,
            "lag": {"p50Seconds": 0.5, "p95Seconds": 1.0, "samples": 100},
            "rewriteRate": 0.8,
            "speakers": {"relabelsPerMinute": 0.5},
            "ending": {"kind": "natural"},
            "battery": {"dropPercentPer30Min": 5.0, "maxThermalState": "nominal"},
            "minutes": 5.0,
        }
    ]
    result = sbi.aggregate(rows)
    assert result["count"] == 1
    assert result["median_rating"] == 5
    assert result["skips"] == 0
    assert result["unrated"] == 0


def test_aggregate_with_null_ratings():
    """Null ratings are excluded from median but counted as unrated."""
    rows = [
        {
            "rating": None,
            "ratingSkipped": False,
            "lag": {"p50Seconds": 0.5, "p95Seconds": 1.0, "samples": 100},
            "rewriteRate": 0.8,
            "speakers": {"relabelsPerMinute": 0.5},
            "ending": {"kind": "natural"},
            "battery": {"dropPercentPer30Min": 5.0, "maxThermalState": "nominal"},
            "minutes": 5.0,
        },
        {
            "rating": 5,
            "ratingSkipped": False,
            "lag": {"p50Seconds": 0.5, "p95Seconds": 1.0, "samples": 100},
            "rewriteRate": 0.8,
            "speakers": {"relabelsPerMinute": 0.5},
            "ending": {"kind": "natural"},
            "battery": {"dropPercentPer30Min": 5.0, "maxThermalState": "nominal"},
            "minutes": 5.0,
        },
    ]
    result = sbi.aggregate(rows)
    assert result["count"] == 2
    assert result["unrated"] == 1
    assert result["median_rating"] == 5


def test_aggregate_with_skipped_ratings():
    """Skipped ratings are counted separately."""
    rows = [
        {
            "rating": 5,
            "ratingSkipped": True,
            "lag": {"p50Seconds": 0.5, "p95Seconds": 1.0, "samples": 100},
            "rewriteRate": 0.8,
            "speakers": {"relabelsPerMinute": 0.5},
            "ending": {"kind": "natural"},
            "battery": {"dropPercentPer30Min": 5.0, "maxThermalState": "nominal"},
            "minutes": 5.0,
        },
    ]
    result = sbi.aggregate(rows)
    assert result["count"] == 1
    assert result["skips"] == 1


def test_aggregate_excludes_low_sample_from_lag():
    """Low-sample rows excluded from lag percentile calculation."""
    rows = [
        {
            "rating": 5,
            "ratingSkipped": False,
            "lag": {"p50Seconds": 10.0, "p95Seconds": 20.0, "samples": 5},
            "rewriteRate": 0.8,
            "speakers": {"relabelsPerMinute": 0.5},
            "ending": {"kind": "natural"},
            "battery": {"dropPercentPer30Min": 5.0, "maxThermalState": "nominal"},
            "minutes": 5.0,
        },
        {
            "rating": 5,
            "ratingSkipped": False,
            "lag": {"p50Seconds": 0.5, "p95Seconds": 1.0, "samples": 100},
            "rewriteRate": 0.8,
            "speakers": {"relabelsPerMinute": 0.5},
            "ending": {"kind": "natural"},
            "battery": {"dropPercentPer30Min": 5.0, "maxThermalState": "nominal"},
            "minutes": 5.0,
        },
    ]
    result = sbi.aggregate(rows)
    assert result["count"] == 2
    assert result["median_lag_p50"] == 0.5  # Only high-sample row's value


def test_aggregate_endings_breakdown():
    """Endings breakdown correctly tallied."""
    rows = [
        {
            "rating": 5,
            "ratingSkipped": False,
            "lag": {"p50Seconds": 0.5, "p95Seconds": 1.0, "samples": 100},
            "rewriteRate": 0.8,
            "speakers": {"relabelsPerMinute": 0.5},
            "ending": {"kind": "natural"},
            "battery": {"dropPercentPer30Min": 5.0, "maxThermalState": "nominal"},
            "minutes": 5.0,
        },
        {
            "rating": 5,
            "ratingSkipped": False,
            "lag": {"p50Seconds": 0.5, "p95Seconds": 1.0, "samples": 100},
            "rewriteRate": 0.8,
            "speakers": {"relabelsPerMinute": 0.5},
            "ending": {"kind": "timeout"},
            "battery": {"dropPercentPer30Min": 5.0, "maxThermalState": "nominal"},
            "minutes": 5.0,
        },
    ]
    result = sbi.aggregate(rows)
    assert result["endings"]["natural"] == 1
    assert result["endings"]["timeout"] == 1


def test_aggregate_worst_thermal_state():
    """Worst (highest rank) thermal state selected as string label."""
    rows = [
        {
            "rating": 5,
            "ratingSkipped": False,
            "lag": {"p50Seconds": 0.5, "p95Seconds": 1.0, "samples": 100},
            "rewriteRate": 0.8,
            "speakers": {"relabelsPerMinute": 0.5},
            "ending": {"kind": "natural"},
            "battery": {"dropPercentPer30Min": 5.0, "maxThermalState": "fair"},
            "minutes": 5.0,
        },
        {
            "rating": 5,
            "ratingSkipped": False,
            "lag": {"p50Seconds": 0.5, "p95Seconds": 1.0, "samples": 100},
            "rewriteRate": 0.8,
            "speakers": {"relabelsPerMinute": 0.5},
            "ending": {"kind": "natural"},
            "battery": {"dropPercentPer30Min": 5.0, "maxThermalState": "critical"},
            "minutes": 5.0,
        },
    ]
    result = sbi.aggregate(rows)
    assert result["worst_thermal_state"] == "critical"


# ── ingest_file ──────────────────────────────────────────────────────────

def test_ingest_file_invalid_report(tmp_path):
    """Invalid report file logs to quarantine, returns error."""
    report_file = tmp_path / "bad-report.json"
    report_file.write_text("{invalid}")

    reports_jsonl = tmp_path / "reports.jsonl"
    quarantine_jsonl = tmp_path / "quarantine.jsonl"

    result = sbi.ingest_file(report_file, reports_jsonl, quarantine_jsonl)

    assert result["valid"] == 0
    assert result["invalid"] == 0
    assert result["error"] is not None
    assert quarantine_jsonl.exists()


def test_ingest_file_valid_conversations(tmp_path):
    """Valid conversations are appended to reports.jsonl."""
    report_file = tmp_path / "report.json"
    data = {
        "schema": 1,
        "device": {"model": "iPhone15,3"},
        "app": {"build": "1.0"},
        "conversations": [
            {
                "id": "conv-1",
                "rating": 5,
                "ratingSkipped": False,
                "lag": {"p50Seconds": 0.5, "p95Seconds": 1.0, "samples": 100},
                "rewriteRate": 0.8,
                "speakers": {"relabelsPerMinute": 0.5},
                "ending": {"kind": "natural"},
                "battery": {"dropPercentPer30Min": 5.0, "maxThermalState": "nominal"},
                "minutes": 5.0,
            },
        ],
    }
    report_file.write_text(json.dumps(data))

    reports_jsonl = tmp_path / "reports.jsonl"
    quarantine_jsonl = tmp_path / "quarantine.jsonl"

    result = sbi.ingest_file(report_file, reports_jsonl, quarantine_jsonl)

    assert result["valid"] == 1
    assert result["invalid"] == 0
    assert result["duplicate"] == 0
    assert reports_jsonl.exists()
    assert len(reports_jsonl.read_text().splitlines()) == 1


def test_ingest_file_deduplicates(tmp_path):
    """Duplicate conversation IDs are skipped."""
    reports_jsonl = tmp_path / "reports.jsonl"
    existing = {"id": "conv-1", "device_model": "iPhone15,3"}
    reports_jsonl.write_text(json.dumps(existing) + "\n")

    report_file = tmp_path / "report.json"
    data = {
        "schema": 1,
        "device": {"model": "iPhone15,3"},
        "app": {"build": "1.0"},
        "conversations": [
            {
                "id": "conv-1",
                "rating": 5,
                "ratingSkipped": False,
                "lag": {"p50Seconds": 0.5, "p95Seconds": 1.0, "samples": 100},
                "rewriteRate": 0.8,
                "speakers": {"relabelsPerMinute": 0.5},
                "ending": {"kind": "natural"},
                "battery": {"dropPercentPer30Min": 5.0, "maxThermalState": "nominal"},
                "minutes": 5.0,
            },
            {
                "id": "conv-2",
                "rating": 4,
                "ratingSkipped": False,
                "lag": {"p50Seconds": 0.5, "p95Seconds": 1.0, "samples": 100},
                "rewriteRate": 0.8,
                "speakers": {"relabelsPerMinute": 0.5},
                "ending": {"kind": "natural"},
                "battery": {"dropPercentPer30Min": 5.0, "maxThermalState": "nominal"},
                "minutes": 5.0,
            },
        ],
    }
    report_file.write_text(json.dumps(data))

    quarantine_jsonl = tmp_path / "quarantine.jsonl"

    result = sbi.ingest_file(report_file, reports_jsonl, quarantine_jsonl)

    assert result["valid"] == 1
    assert result["duplicate"] == 1
    assert len(reports_jsonl.read_text().splitlines()) == 2


def test_ingest_file_invalid_conversations(tmp_path):
    """Invalid conversations are logged to quarantine."""
    report_file = tmp_path / "report.json"
    data = {
        "schema": 1,
        "device": {"model": "iPhone15,3"},
        "app": {"build": "1.0"},
        "conversations": [
            {
                "id": "conv-1",
                "rating": 5,
                "ratingSkipped": False,
                "lag": {"p50Seconds": 0.5, "p95Seconds": 1.0, "samples": 100},
                "rewriteRate": 0.8,
                "speakers": {"relabelsPerMinute": 0.5},
                "ending": {"kind": "natural"},
                "battery": {"dropPercentPer30Min": 5.0, "maxThermalState": "nominal"},
                "minutes": 5.0,
            },
            {
                "id": "conv-2",
                "rating": 4,
                # Missing ratingSkipped - invalid
                "lag": {"p50Seconds": 0.5, "p95Seconds": 1.0, "samples": 100},
                "rewriteRate": 0.8,
                "speakers": {"relabelsPerMinute": 0.5},
                "ending": {"kind": "natural"},
                "battery": {"dropPercentPer30Min": 5.0, "maxThermalState": "nominal"},
                "minutes": 5.0,
            },
        ],
    }
    report_file.write_text(json.dumps(data))

    reports_jsonl = tmp_path / "reports.jsonl"
    quarantine_jsonl = tmp_path / "quarantine.jsonl"

    result = sbi.ingest_file(report_file, reports_jsonl, quarantine_jsonl)

    assert result["valid"] == 1
    assert result["invalid"] == 1
    assert quarantine_jsonl.exists()


# ── summarize ────────────────────────────────────────────────────────────

def test_summarize_empty_reports(tmp_path):
    """Empty reports file produces empty summary."""
    reports_jsonl = tmp_path / "reports.jsonl"

    summary = sbi.summarize(reports_jsonl)

    assert summary["by_device"] == {}
    assert summary["by_build"] == {}
    assert "generated_at" in summary
    assert summary["last_report_seen_at"] is None


def test_summarize_builds_tree(tmp_path):
    """Summarize builds by-device and by-build trees."""
    reports_dir = tmp_path / "reports"
    reports_jsonl = reports_dir / "reports.jsonl"

    rows = [
        {
            "id": "conv-1",
            "rating": 5,
            "ratingSkipped": False,
            "lag": {"p50Seconds": 0.5, "p95Seconds": 1.0, "samples": 100},
            "rewriteRate": 0.8,
            "speakers": {"relabelsPerMinute": 0.5},
            "ending": {"kind": "natural"},
            "battery": {"dropPercentPer30Min": 5.0, "maxThermalState": "nominal"},
            "minutes": 5.0,
            "device_model": "iPhone15,3",
            "app_build": "1.0",
        },
        {
            "id": "conv-2",
            "rating": 4,
            "ratingSkipped": False,
            "lag": {"p50Seconds": 0.5, "p95Seconds": 1.0, "samples": 100},
            "rewriteRate": 0.8,
            "speakers": {"relabelsPerMinute": 0.5},
            "ending": {"kind": "natural"},
            "battery": {"dropPercentPer30Min": 5.0, "maxThermalState": "nominal"},
            "minutes": 5.0,
            "device_model": "iPhone15,3",
            "app_build": "1.0",
        },
    ]
    reports_dir.mkdir(parents=True, exist_ok=True)
    reports_jsonl.write_text("\n".join(json.dumps(r) for r in rows))

    summary = sbi.summarize(reports_jsonl)

    assert "iPhone15,3" in summary["by_device"]
    assert "1.0" in summary["by_build"]
    assert summary["by_device"]["iPhone15,3"]["plain_name"] == "iPhone 15 Pro"
    assert summary["by_device"]["iPhone15,3"]["builds"]["1.0"]["count"] == 2
    assert summary["by_device"]["iPhone15,3"]["builds"]["1.0"]["median_rating"] == 4.5


# ── Regression tests (1–10) ──────────────────────────────────────────────

def test_regression_1_thermal_rank_exists():
    """THERMAL_RANK mapping exists with correct values."""
    assert sbi.THERMAL_RANK == {
        "nominal": 0,
        "fair": 1,
        "serious": 2,
        "critical": 3,
    }


def test_regression_2_validate_rejects_numeric_thermal():
    """validate_conversation rejects numeric maxThermalState."""
    row = _valid_conversation()
    row["battery"]["maxThermalState"] = 1  # numeric, not string
    is_valid, err = sbi.validate_conversation(row)
    assert not is_valid
    assert "maxThermalState must be non-empty string" in err


def test_regression_3_validate_accepts_all_thermal_states():
    """validate_conversation accepts all valid thermal state strings."""
    for state in ["nominal", "fair", "serious", "critical"]:
        row = _valid_conversation()
        row["battery"]["maxThermalState"] = state
        is_valid, err = sbi.validate_conversation(row)
        assert is_valid, f"State {state} should be valid"


def test_regression_4_validate_rejects_unknown_thermal():
    """validate_conversation rejects unknown thermal state strings."""
    row = _valid_conversation()
    row["battery"]["maxThermalState"] = "overheating"
    is_valid, err = sbi.validate_conversation(row)
    assert not is_valid


def test_regression_5_is_low_sample_minutes_threshold():
    """is_low_sample returns True if minutes < 1.0."""
    conv = {"minutes": 0.9, "lag": {"samples": 100}}
    assert sbi.is_low_sample(conv) is True


def test_regression_6_is_low_sample_samples_threshold():
    """is_low_sample returns True if samples < 30."""
    conv = {"minutes": 10.0, "lag": {"samples": 29}}
    assert sbi.is_low_sample(conv) is True


def test_regression_7_aggregate_returns_thermal_string():
    """aggregate returns worst_thermal_state as string label."""
    rows = [
        {
            "rating": 5,
            "ratingSkipped": False,
            "lag": {"p50Seconds": 0.5, "p95Seconds": 1.0, "samples": 100},
            "rewriteRate": 0.8,
            "speakers": {"relabelsPerMinute": 0.5},
            "ending": {"kind": "natural"},
            "battery": {"dropPercentPer30Min": 5.0, "maxThermalState": "serious"},
            "minutes": 5.0,
        },
    ]
    result = sbi.aggregate(rows)
    assert result["worst_thermal_state"] == "serious"
    assert isinstance(result["worst_thermal_state"], str)


def test_regression_8_aggregate_empty_thermal_states():
    """aggregate returns None if no valid thermal states."""
    rows = [
        {
            "rating": 5,
            "ratingSkipped": False,
            "lag": {"p50Seconds": 0.5, "p95Seconds": 1.0, "samples": 100},
            "rewriteRate": 0.8,
            "speakers": {"relabelsPerMinute": 0.5},
            "ending": {"kind": "natural"},
            "battery": {"dropPercentPer30Min": 5.0},  # No maxThermalState
            "minutes": 5.0,
        },
    ]
    result = sbi.aggregate(rows)
    assert result["worst_thermal_state"] is None


def test_regression_9_ingest_uses_allowlist():
    """ingest_file uses allowlist, excludes note/startedAt from enriched."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        report_file = tmp_path / "report.json"
        data = {
            "schema": 1,
            "device": {"model": "iPhone15,3"},
            "app": {"build": "1.0"},
            "conversations": [
                {
                    "id": "conv-1",
                    "rating": 5,
                    "ratingSkipped": False,
                    "lag": {"p50Seconds": 0.5, "p95Seconds": 1.0, "samples": 100},
                    "rewriteRate": 0.8,
                    "speakers": {"relabelsPerMinute": 0.5},
                    "ending": {"kind": "natural"},
                    "battery": {"dropPercentPer30Min": 5.0, "maxThermalState": "nominal"},
                    "minutes": 5.0,
                    "note": "user feedback",
                    "startedAt": "2026-01-01T00:00:00Z",
                    "extra_field": "should not appear",
                },
            ],
        }
        report_file.write_text(json.dumps(data))

        reports_jsonl = tmp_path / "reports.jsonl"
        quarantine_jsonl = tmp_path / "quarantine.jsonl"

        sbi.ingest_file(report_file, reports_jsonl, quarantine_jsonl)

        saved_line = reports_jsonl.read_text().strip()
        saved_row = json.loads(saved_line)

        # Allowlist fields should be present
        assert "id" in saved_row
        assert "rating" in saved_row
        assert "battery" in saved_row

        # Excluded fields should not be present
        assert "note" not in saved_row
        assert "startedAt" not in saved_row
        assert "extra_field" not in saved_row


def test_regression_10_iphone18_maps_to_17():
    """iPhone18,1 maps to 'iPhone 17', not 'iPhone 18'."""
    assert sbi.device_plain_name("iPhone18,1") == "iPhone 17"


# ── Gap-fill tests (11–23) ────────────────────────────────────────────────

def test_gap_11_validate_empty_thermal_string():
    """validate_conversation rejects empty string thermal state."""
    row = _valid_conversation()
    row["battery"]["maxThermalState"] = ""
    is_valid, err = sbi.validate_conversation(row)
    assert not is_valid
    assert "maxThermalState must be non-empty string" in err


def test_gap_12_validate_whitespace_thermal():
    """validate_conversation rejects whitespace-only thermal state."""
    row = _valid_conversation()
    row["battery"]["maxThermalState"] = "  "
    is_valid, err = sbi.validate_conversation(row)
    assert not is_valid


def test_gap_13_is_low_sample_exactly_at_threshold():
    """is_low_sample boundary: minutes=1.0, samples=30 is not low."""
    conv = {"minutes": 1.0, "lag": {"samples": 30}}
    assert sbi.is_low_sample(conv) is False


def test_gap_14_is_low_sample_zero_minutes_many_samples():
    """is_low_sample: zero minutes makes it low regardless of samples."""
    conv = {"minutes": 0, "lag": {"samples": 1000}}
    assert sbi.is_low_sample(conv) is True


def test_gap_15_aggregate_mixed_thermal_states():
    """aggregate picks worst thermal state from mixed states."""
    rows = [
        {
            "rating": 5,
            "ratingSkipped": False,
            "lag": {"p50Seconds": 0.5, "p95Seconds": 1.0, "samples": 100},
            "rewriteRate": 0.8,
            "speakers": {"relabelsPerMinute": 0.5},
            "ending": {"kind": "natural"},
            "battery": {"dropPercentPer30Min": 5.0, "maxThermalState": "nominal"},
            "minutes": 5.0,
        },
        {
            "rating": 5,
            "ratingSkipped": False,
            "lag": {"p50Seconds": 0.5, "p95Seconds": 1.0, "samples": 100},
            "rewriteRate": 0.8,
            "speakers": {"relabelsPerMinute": 0.5},
            "ending": {"kind": "natural"},
            "battery": {"dropPercentPer30Min": 5.0, "maxThermalState": "fair"},
            "minutes": 5.0,
        },
        {
            "rating": 5,
            "ratingSkipped": False,
            "lag": {"p50Seconds": 0.5, "p95Seconds": 1.0, "samples": 100},
            "rewriteRate": 0.8,
            "speakers": {"relabelsPerMinute": 0.5},
            "ending": {"kind": "natural"},
            "battery": {"dropPercentPer30Min": 5.0, "maxThermalState": "serious"},
            "minutes": 5.0,
        },
    ]
    result = sbi.aggregate(rows)
    assert result["worst_thermal_state"] == "serious"


def test_gap_16_aggregate_ignores_invalid_thermal_states():
    """aggregate ignores unmapped thermal state strings."""
    rows = [
        {
            "rating": 5,
            "ratingSkipped": False,
            "lag": {"p50Seconds": 0.5, "p95Seconds": 1.0, "samples": 100},
            "rewriteRate": 0.8,
            "speakers": {"relabelsPerMinute": 0.5},
            "ending": {"kind": "natural"},
            "battery": {"dropPercentPer30Min": 5.0, "maxThermalState": "invalid_state"},
            "minutes": 5.0,
        },
        {
            "rating": 5,
            "ratingSkipped": False,
            "lag": {"p50Seconds": 0.5, "p95Seconds": 1.0, "samples": 100},
            "rewriteRate": 0.8,
            "speakers": {"relabelsPerMinute": 0.5},
            "ending": {"kind": "natural"},
            "battery": {"dropPercentPer30Min": 5.0, "maxThermalState": "fair"},
            "minutes": 5.0,
        },
    ]
    result = sbi.aggregate(rows)
    assert result["worst_thermal_state"] == "fair"


def test_gap_17_ingest_preserves_allowlist_fields():
    """ingest_file preserves all allowlist fields correctly."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        report_file = tmp_path / "report.json"
        data = {
            "schema": 1,
            "device": {"model": "iPhone16,1"},
            "app": {"build": "2.0"},
            "conversations": [
                {
                    "id": "test-conv",
                    "rating": 3,
                    "ratingSkipped": True,
                    "lag": {"p50Seconds": 1.2, "p95Seconds": 2.3, "samples": 45},
                    "rewriteRate": 0.6,
                    "speakers": {"relabelsPerMinute": 0.3},
                    "ending": {"kind": "timeout"},
                    "battery": {"dropPercentPer30Min": 10.0, "maxThermalState": "fair"},
                    "minutes": 3.5,
                },
            ],
        }
        report_file.write_text(json.dumps(data))

        reports_jsonl = tmp_path / "reports.jsonl"
        quarantine_jsonl = tmp_path / "quarantine.jsonl"

        sbi.ingest_file(report_file, reports_jsonl, quarantine_jsonl)

        saved_line = reports_jsonl.read_text().strip()
        saved_row = json.loads(saved_line)

        assert saved_row["id"] == "test-conv"
        assert saved_row["rating"] == 3
        assert saved_row["ratingSkipped"] is True
        assert saved_row["device_model"] == "iPhone16,1"
        assert saved_row["app_build"] == "2.0"


def test_gap_18_validate_all_required_battery_fields():
    """validate_conversation checks both battery fields."""
    row = _valid_conversation()
    del row["battery"]["dropPercentPer30Min"]
    is_valid, err = sbi.validate_conversation(row)
    assert not is_valid
    assert "dropPercentPer30Min" in err


def test_gap_19_aggregate_all_thermal_rank_values():
    """aggregate correctly ranks all THERMAL_RANK values."""
    for state, rank in sbi.THERMAL_RANK.items():
        rows = [
            {
                "rating": 5,
                "ratingSkipped": False,
                "lag": {"p50Seconds": 0.5, "p95Seconds": 1.0, "samples": 100},
                "rewriteRate": 0.8,
                "speakers": {"relabelsPerMinute": 0.5},
                "ending": {"kind": "natural"},
                "battery": {"dropPercentPer30Min": 5.0, "maxThermalState": state},
                "minutes": 5.0,
            },
        ]
        result = sbi.aggregate(rows)
        assert result["worst_thermal_state"] == state


def test_gap_20_is_low_sample_float_minutes():
    """is_low_sample handles float minutes correctly."""
    conv = {"minutes": 0.99999, "lag": {"samples": 100}}
    assert sbi.is_low_sample(conv) is True

    conv2 = {"minutes": 1.00001, "lag": {"samples": 100}}
    assert sbi.is_low_sample(conv2) is False


def test_gap_21_summarize_aggregate_with_thermal_states():
    """summarize correctly aggregates thermal states in summary."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        reports_dir = tmp_path / "reports"
        reports_jsonl = reports_dir / "reports.jsonl"

        rows = [
            {
                "id": "conv-a",
                "rating": 5,
                "ratingSkipped": False,
                "lag": {"p50Seconds": 0.5, "p95Seconds": 1.0, "samples": 100},
                "rewriteRate": 0.8,
                "speakers": {"relabelsPerMinute": 0.5},
                "ending": {"kind": "natural"},
                "battery": {"dropPercentPer30Min": 5.0, "maxThermalState": "fair"},
                "minutes": 5.0,
                "device_model": "iPhone17,1",
                "app_build": "3.0",
            },
            {
                "id": "conv-b",
                "rating": 4,
                "ratingSkipped": False,
                "lag": {"p50Seconds": 0.5, "p95Seconds": 1.0, "samples": 100},
                "rewriteRate": 0.8,
                "speakers": {"relabelsPerMinute": 0.5},
                "ending": {"kind": "natural"},
                "battery": {"dropPercentPer30Min": 5.0, "maxThermalState": "critical"},
                "minutes": 5.0,
                "device_model": "iPhone17,1",
                "app_build": "3.0",
            },
        ]
        reports_dir.mkdir(parents=True, exist_ok=True)
        reports_jsonl.write_text("\n".join(json.dumps(r) for r in rows))

        summary = sbi.summarize(reports_jsonl)

        build_agg = summary["by_build"]["3.0"]
        assert build_agg["worst_thermal_state"] == "critical"


def test_gap_22_validate_thermal_case_sensitive():
    """validate_conversation: thermal state is case-sensitive."""
    row = _valid_conversation()
    row["battery"]["maxThermalState"] = "Nominal"  # Capitalized
    is_valid, err = sbi.validate_conversation(row)
    assert not is_valid


def test_gap_23_ingest_file_with_missing_optional_fields():
    """ingest_file handles conversations missing optional non-required fields."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        report_file = tmp_path / "report.json"
        # Minimal valid conversation (only required fields)
        data = {
            "schema": 1,
            "device": {"model": "iPhone15,3"},
            "app": {"build": "1.0"},
            "conversations": [
                {
                    "id": "minimal-conv",
                    "rating": None,  # Null is allowed
                    "ratingSkipped": False,
                    "lag": {"p50Seconds": 0.5, "p95Seconds": 1.0, "samples": 100},
                    "rewriteRate": 0.8,
                    "speakers": {"relabelsPerMinute": 0.5},
                    "ending": {"kind": "natural"},
                    "battery": {"dropPercentPer30Min": 5.0, "maxThermalState": "nominal"},
                    "minutes": 5.0,
                },
            ],
        }
        report_file.write_text(json.dumps(data))

        reports_jsonl = tmp_path / "reports.jsonl"
        quarantine_jsonl = tmp_path / "quarantine.jsonl"

        result = sbi.ingest_file(report_file, reports_jsonl, quarantine_jsonl)

        assert result["valid"] == 1
        assert result["invalid"] == 0
        assert reports_jsonl.read_text().strip()  # File has content
